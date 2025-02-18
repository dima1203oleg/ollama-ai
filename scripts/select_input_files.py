#!/usr/bin/env python3

import os
import glob
import pandas as pd
from typing import List, Set

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

def process_file(input_file: str) -> None:
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
        
        # Маппинг колонок
        column_mapping = {
            'Дата оформлення': 'date',
            'Опис товару': 'product',
            'Кількість': 'quantity', 
            'Фактурна варість, валюта контракту': 'value',
            'Країна походження': 'country',
            'Митниця оформлення': 'customs',
            'Тип декларації': 'declaration_type',
            'Відправник': 'sender',
            'Одержувач': 'receiver',
            'ЄДРПОУ одержувача': 'receiver_code',
            'Номер митної декларації': 'declaration_number',
            'Торгуюча країна': 'trading_country',
            'Країна відправлення': 'sending_country',
            'Умови поставки': 'delivery_terms',
            'Місце поставки': 'delivery_place',
            'Одиниця виміру': 'unit',
            'Маса, брутто, кг': 'weight_gross',
            'Маса, нетто, кг': 'weight_net',
            'Вага по митній декларації': 'customs_weight',
            'Особ.перем.': 'special_mark',
            'Контракт': 'contract',
            'Торг.марк.': 'trademark',
            'Код товару': 'product_code',
            'Розрахункова фактурна вартість, дол. США / кг': 'calculated_invoice_value_usd_kg',
            'Вага.один.': 'weight_unit',
            'Вага різн.': 'weight_diff',
            'Розрахункова митна вартість, нетто дол. США / кг': 'calculated_customs_value_net_usd_kg',
            'Розрахункова митна вартість, дол. США / дод. од.': 'calculated_customs_value_usd_add',
            'Розрахункова митна вартість,брутто дол. США / кг': 'calculated_customs_value_gross_usd_kg',
            'Мін.База Дол/кг.': 'min_base_usd_kg',
            'Різн.мін.база': 'min_base_diff',
            'КЗ Нетто Дол/кг.': 'cz_net_usd_kg',
            'Різн.КЗ Дол/кг': 'cz_diff_usd_kg',
            'пільгова': 'preferential',
            'повна': 'full'
        }

        # Создаем новый DataFrame с переименованными колонками
        processed_df = df[column_mapping.keys()].rename(columns=column_mapping)
        
        # Преобразование даты
        processed_df['date'] = pd.to_datetime(processed_df['date'], format='%d.%m.%y').dt.strftime('%Y-%m-%d')
        
        # Заполняем пустые значения
        for col in processed_df.columns:
            if col in ['quantity', 'value', 'weight_gross', 'weight_net', 'customs_weight']:
                processed_df[col] = processed_df[col].fillna(0)
            else:
                processed_df[col] = processed_df[col].fillna('')

        # Сохранение результата
        if os.path.exists(output_file):
            processed_df.to_csv(output_file, mode='w', index=False)
        else:
            processed_df.to_csv(output_file, index=False)
            
        print(f"Файл успешно обработан: {os.path.basename(input_file)}")
        print(f"Обработано {len(processed_df)} записей")
        
    except Exception as e:
        print(f"Ошибка при обработке файла {os.path.basename(input_file)}")
        print(f"Детали ошибки: {str(e)}")

def main():
    files = list_input_files()
    if not files:
        print("Директория input пуста или не существует")
        return
    
    display_files(files)
    selected = get_user_selection(len(files))
    
    print("\nНачало обработки файлов...")
    for idx in selected:
        input_file = files[idx-1]
        print(f"\nОбработка файла: {os.path.basename(input_file)}")
        process_file(input_file)
    
    print("\nОбработка завершена")

if __name__ == "__main__":
    main()