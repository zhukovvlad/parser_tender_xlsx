"""
Модуль для парсинга тендерных данных из XLSX файла и сохранения их в JSON.

Этот скрипт принимает на вход путь к XLSX файлу, содержащему тендерную документацию,
обрабатывает его с помощью библиотеки openpyxl и вспомогательных модулей из пакета 'helpers',
а затем формирует и сохраняет результат в виде JSON файла.

Основные используемые библиотеки:
- openpyxl: для чтения данных из XLSX файлов.
- json: для работы с JSON данными.
- argparse: для парсинга аргументов командной строки.

Вспомогательные модули (предположительно из пакета 'helpers'):
- read_headers: для чтения информации из заголовка документа.
- read_contractors: для чтения информации о контрагентах/участниках.
- read_lots_and_boundaries: для чтения информации о лотах и их границах, включая предложения.
- read_executer_block: для чтения информации об исполнителе из конца документа.

Запуск из командной строки:
python parse.py <путь_к_xlsx_файлу> <путь_к_выходному_json_файлу>

Аргументы:
  xlsx_path         Путь к входному XLSX файлу.
  output_json_path  Путь для сохранения выходного JSON файла.
"""
import openpyxl
import json
import argparse

# Предполагается, что эти модули находятся в директории 'helpers' относительно этого файла.
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
from helpers.read_contractors import read_contractors
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block

def parse_file(xlsx_path, output_json_path):
  """
  Основная функция для парсинга XLSX файла и сохранения результата в JSON.

  Загружает XLSX файл, последовательно извлекает из него различные блоки данных
  (заголовки, информация об исполнителе, лоты с предложениями),
  агрегирует их в единую структуру и сохраняет в указанный JSON файл.

  Args:
    xlsx_path (str): Путь к входному XLSX файлу.
    output_json_path (str): Путь для сохранения выходного JSON файла.
  
  Side effects:
    - Печатает результат вызова `read_contractors(ws)` в консоль (возможно, для отладки).
    - Создает или перезаписывает JSON файл по пути `output_json_path`.
    - Печатает сообщение об успешном сохранении JSON файла в консоль.
  """
  wb = openpyxl.load_workbook(xlsx_path, data_only=True) # data_only=True для получения значений ячеек, а не формул
  ws = wb.active  # Получаем активный лист
  
  # Внимание: следующая строка выводит информацию о контрагентах в консоль.
  # Это может быть отладочной информацией. Функция read_contractors, вероятно,
  # также вызывается внутри read_lots_and_boundaries через get_proposals.
  print(read_contractors(ws)) 
  
  result = {
    **read_headers(ws),  # Читаем и распаковываем заголовки в общий результат
    "executor": read_executer_block(ws),  # Читаем информацию об исполнителе
    "lots": read_lots_and_boundaries(ws),   # Читаем информацию о лотах и предложениях
    }
  
  result = normalize_lots_json_structure(result)  # Нормализуем структуру лотов
  result = replace_div0_with_null(result)  # Заменяем 'DIV/0' и подобные значения на None
    
  with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2) # Сохраняем в JSON с отступами и поддержкой UTF-8
  print(f"JSON saved to {output_json_path}")

if __name__ == "__main__":
  # Настройка парсера аргументов командной строки
  parser = argparse.ArgumentParser(description="Парсер тендерного файла XLSX в JSON.")
  parser.add_argument("xlsx_path", type=str, help="Путь к входному XLSX файлу.")
  parser.add_argument("output_json_path", type=str, help="Путь для сохранения выходного JSON файла.")
  args = parser.parse_args()

  # Вызов основной функции с переданными аргументами
  parse_file(args.xlsx_path, args.output_json_path)