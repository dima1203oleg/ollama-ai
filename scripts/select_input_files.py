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
        # Сначала попробуем прочитать первую строку файла для определения структуры
        with open(input_file, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            if first_line == 'custom_1':  # Пропускаем первую строку, если она содержит 'custom_1'
                df = pd.read_csv(input_file, delimiter=';', encoding='utf-8', skiprows=1)
            else:
                df = pd.read_csv(input_file, delimiter=';', encoding='utf-8')

        print(f"Доступные колонки в файле: {df.columns.tolist()}")
        
        # Проверяем, есть ли нужные колонки
        required_columns = {
            'Дата оформлення': 'date',
            'Опис товару': 'product',
            'Кількість': 'quantity',
            'Фактурна варість, валюта контракту': 'value',
            'Країна походження': 'country',
            'Митниця оформлення': 'customs',
            'Тип декларації': 'declaration_type',
            'Відправник': 'sender',
            'Одержувач': 'receiver',
            'ЄДРПОУ одержувача': 'receiver_code'
        }
        
        # Проверяем наличие всех необходимых колонок
        missing_columns = [col for col in required_columns.keys() if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Отсутствуют следующие колонки: {', '.join(missing_columns)}")
        
        # Преобразование в нужный формат
        processed_df = pd.DataFrame({
            'date': pd.to_datetime(df['Дата оформлення'], format='%d.%m.%y').dt.strftime('%Y-%m-%d'),
            'product': df['Опис товару'],
            'quantity': pd.to_numeric(df['Кількість'].fillna(0)),
            'value': pd.to_numeric(df['Фактурна варість, валюта контракту'].fillna(0)),
            'country': df['Країна походження'],
            'customs': df['Митниця оформлення'],
            'declaration_type': df['Тип декларації'],
            'sender': df['Відправник'],
            'receiver': df['Одержувач'],
            'receiver_code': df['ЄДРПОУ одержувача']
        })
        
        # Сохранение результата
        if os.path.exists(output_file):
            processed_df.to_csv(output_file, mode='a', header=False, index=False)
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