#!/usr/bin/env python3

import os
import glob
import pandas as pd
from typing import List, Set, Dict, Any
from opensearchpy import OpenSearch, helpers, OpenSearchException
import logging
import json
from datetime import datetime

# Исправляем конфигурацию логгера
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def init_opensearch() -> OpenSearch:
    """Инициализация подключения к OpenSearch"""
    try:
        client = OpenSearch(
            hosts=[{'host': 'localhost', 'port': 9200}],
            http_compress=True,
            use_ssl=False,
            verify_certs=False,
        )
        if not client.ping():
            raise ConnectionError("Could not connect to OpenSearch")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to OpenSearch: {str(e)}")
        raise

def setup_index(client: OpenSearch, index_name: str) -> None:
    """Подготовка индекса с проверкой маппинга"""
    try:
        # Читаем маппинг из файла
        mapping_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'opensearch/mapping.json')
        with open(mapping_file, 'r') as f:
            mapping_config = json.load(f)

        if client.indices.exists(index=index_name):
            # Проверяем соответствие маппинга
            current_mapping = client.indices.get_mapping(index=index_name)
            if current_mapping[index_name]['mappings'] != mapping_config['mappings']:
                logger.warning(f"Маппинг индекса {index_name} отличается от конфигурации")
                logger.info(f"Пересоздаем индекс {index_name} с правильным маппингом")
                client.indices.delete(index=index_name)
                client.indices.create(index=index_name, body=mapping_config)
        else:
            client.indices.create(index=index_name, body=mapping_config)
            logger.info(f"Создан новый индекс {index_name}")

    except Exception as e:
        logger.error(f"Ошибка при настройке индекса: {str(e)}")
        raise

def process_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Обработка DataFrame перед индексацией"""
    try:
        # Создаем копию для обработки
        processed_df = df.copy()
        
        # Предварительная обработка дат
        if 'processing_date' in processed_df.columns:
            processed_df['processing_date'] = pd.to_datetime(
                processed_df['processing_date'],
                format='%d.%m.%y',
                errors='coerce'
            ).fillna(datetime.now())
            processed_df['processing_date'] = processed_df['processing_date'].dt.strftime('%Y-%m-%d')

        # Обработка числовых значений
        float_columns = [
            'quantity', 'invoice_value', 'gross_weight', 'net_weight', 'customs_weight',
            'calculated_invoice_value_usd_kg', 'unit_weight', 'weight_difference',
            'calculated_customs_value_net_usd_kg', 'calculated_customs_value_usd_add_unit',
            'calculated_customs_value_gross_usd_kg', 'min_base_usd_kg', 'min_base_difference',
            'customs_value_net_usd_kg', 'customs_value_difference_usd_kg',
            'preferential_rate', 'full_rate'
        ]
        
        for col in float_columns:
            if col in processed_df.columns:
                processed_df[col] = pd.to_numeric(
                    processed_df[col].astype(str).str.replace(',', '.'),
                    errors='coerce'
                ).fillna(0.0)

        # Заполняем пустые значения в текстовых полях
        for col in processed_df.columns:
            if col not in float_columns and col != 'processing_date':
                processed_df[col] = processed_df[col].fillna('')

        return processed_df
    except Exception as e:
        logger.error(f"Ошибка при обработке данных: {str(e)}")
        raise

def index_documents(client: OpenSearch, df: pd.DataFrame, index_name: str) -> None:
    """Индексация документов с проверкой ошибок"""
    try:
        processed_df = process_dataframe(df)
        actions = [
            {
                "_index": index_name,
                "_id": f"{row['declaration_number']}_{row['item_number']}",
                "_source": {k: v for k, v in row.items() if pd.notna(v)}
            }
            for _, row in processed_df.iterrows()
        ]
        
        success, failed = helpers.bulk(client, actions, raise_on_error=False, stats_only=True)
        logger.info(f"Индексировано документов: {success}, ошибок: {failed}")
        
        if failed > 0:
            logger.warning(f"Не удалось индексировать {failed} документов")
            
    except Exception as e:
        logger.error(f"Ошибка при индексации документов: {str(e)}")
        raise

def list_input_files() -> List[str]:
    """Получаем список всех файлов из директории input"""
    input_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'input')
    if not os.path.exists(input_path):
        return []
    return sorted(glob.glob(os.path.join(input_path, 'input*')))

def display_files(files: List[str]) -> None:
    """Отображаем файлы с номерами"""
    if not files:
        print("Файлы с префиксом 'input' не найдены")
        return
    
    print("\nДоступные файлы:")
    for idx, file in enumerate(files, 1):
        print(f"{idx}. {os.path.basename(file)}")

def get_user_selection(max_num: int) -> Set[int]:
    """Получаем выбор пользователя"""
    print("\nВыберите номера файлов (через пробел) или нажмите Enter для выбора всех:")
    selection = input().strip()
    
    if not selection:
        return set(range(1, max_num + 1))
    
    try:
        numbers = {int(num) for num in selection.split()}
        if not all(1 <= num <= max_num for num in numbers):
            raise ValueError
        return numbers
    except ValueError:
        print("Некорректный ввод. Будут выбраны все файлы.")
        return set(range(1, max_num + 1))

def process_file(input_file: str, client: OpenSearch, index_name: str) -> None:
    """Обработка входного файла и сохранение в data/customs_data.csv"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    os.makedirs(data_dir, exist_ok=True)
    output_file = os.path.join(data_dir, 'customs_data.csv')
    
    try:
        # Читаем CSV с учетом специального форматирования
        df = pd.read_csv(input_file, 
                        delimiter=';', 
                        encoding='utf-8',
                        decimal=',',
                        thousands=' ',
                        skiprows=1)
        
        print(f"Доступные колонки в файле: {df.columns.tolist()}")
        
        # Обновленный маппинг колонок
        column_mapping = {
            'Дата оформлення': 'processing_date',
            'Опис товару': 'product_description',
            'Кількість': 'quantity', 
            'Фактурна варість, валюта контракту': 'invoice_value',
            'Країна походження': 'origin_country',
            'Митниця оформлення': 'customs_office',
            'Тип декларації': 'declaration_type',
            'Відправник': 'sender',
            'Одержувач': 'recipient',
            'ЄДРПОУ одержувача': 'recipient_code',
            'Номер митної декларації': 'declaration_number',
            'Торгуюча країна': 'trading_country',
            'Країна відправлення': 'shipping_country',
            'Умови поставки': 'delivery_terms',
            'Місце поставки': 'delivery_location',
            'Одиниця виміру': 'unit',
            'Маса, брутто, кг': 'gross_weight',
            'Маса, нетто, кг': 'net_weight',
            'Вага по митній декларації': 'customs_weight',
            'Особ.перем.': 'special_mark',
            'Контракт': 'contract_type',
            'Торг.марк.': 'trade_mark',
            'Код товару': 'product_code',
            'Розрахункова фактурна вартість, дол. США / кг': 'calculated_invoice_value_usd_kg',
            'Вага.один.': 'unit_weight',
            'Вага різн.': 'weight_difference',
            'Розрахункова митна вартість, нетто дол. США / кг': 'calculated_customs_value_net_usd_kg',
            'Розрахункова митна вартість, дол. США / дод. од.': 'calculated_customs_value_usd_add_unit',
            'Розрахункова митна вартість,брутто дол. США / кг': 'calculated_customs_value_gross_usd_kg',
            'Мін.База Дол/кг.': 'min_base_usd_kg',
            'Різн.мін.база': 'min_base_difference',
            'КЗ Нетто Дол/кг.': 'customs_value_net_usd_kg',
            'Різн.КЗ Дол/кг': 'customs_value_difference_usd_kg',
            'пільгова': 'preferential_rate',
            'повна': 'full_rate'
        }

        # Создаем новый DataFrame с переименованными колонками
        processed_df = df[column_mapping.keys()].rename(columns=column_mapping)
        
        # Добавляем номер позиции
        processed_df['item_number'] = range(1, len(processed_df) + 1)
        
        # Преобразование даты
        processed_df['processing_date'] = pd.to_datetime(processed_df['processing_date'], format='%d.%m.%y').dt.strftime('%Y-%m-%d')
        
        # Заполняем пустые значения
        for col in processed_df.columns:
            if col in ['quantity', 'invoice_value', 'gross_weight', 'net_weight', 'customs_weight']:
                processed_df[col] = processed_df[col].fillna(0)
            else:
                processed_df[col] = processed_df[col].fillna('')

        # Сохранение результата
        if os.path.exists(output_file):
            processed_df.to_csv(output_file, mode='w', index=False)
        else:
            processed_df.to_csv(output_file, index=False)
            
        # Загружаем данные в OpenSearch
        index_documents(client, processed_df, index_name)
        
        logger.info(f"Файл успешно обработан: {os.path.basename(input_file)}")
        logger.info(f"Обработано {len(processed_df)} записей")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке файла {os.path.basename(input_file)}")
        logger.error(f"Детали ошибки: {str(e)}")

def main():
    """Main function to process files"""
    files = list_input_files()
    if not files:
        logger.error("Директория input пуста или не существует")
        return
    
    display_files(files)
    selected = get_user_selection(len(files))
    
    try:
        # Инициализация OpenSearch и подготовка индекса
        client = init_opensearch()
        index_name = "customs_declarations"
        setup_index(client, index_name)
        
        logger.info("\nНачало обработки файлов...")
        total_docs = 0
        
        for idx in selected:
            input_file = files[idx-1]
            logger.info(f"\nОбработка файла: {os.path.basename(input_file)}")
            process_file(input_file, client, index_name)
            
            # Принудительное обновление индекса
            client.indices.refresh(index=index_name)
            
            # Проверка индексации после каждого файла
            stats = client.indices.stats(index=index_name)
            doc_count = stats['indices'][index_name]['total']['docs']['count']
            total_docs += doc_count
            logger.info(f"Текущее количество документов в индексе: {doc_count}")
        
        # Финальная проверка после обработки всех файлов
        client.indices.refresh(index=index_name)
        stats = client.indices.stats(index=index_name)
        final_count = stats['indices'][index_name]['total']['docs']['count']
        logger.info(f"\nИндексация завершена. Всего документов в индексе: {final_count}")
        
        # Проверка маппинга
        mapping = client.indices.get_mapping(index=index_name)
        logger.debug(f"Текущий маппинг индекса: {json.dumps(mapping, indent=2)}")
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {str(e)}")
        return

if __name__ == "__main__":
    main()