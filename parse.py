"""
Модуль для полного цикла обработки тендерных данных: парсинг из XLSX,
постобработка извлеченных данных, сохранение результата в JSON и генерация
Markdown-отчета.

Этот скрипт принимает на вход путь к XLSX файлу, содержащему тендерную
документацию. Он обрабатывает его с помощью библиотеки openpyxl и
вспомогательных модулей из пакета 'helpers'. После первоначального парсинга
данные проходят через этапы постобработки (нормализация структуры лотов,
замена ошибок деления на ноль). Финальный, обработанный JSON сохраняется
в файл, и на его основе также генерируется структурированный Markdown-файл.

Основные используемые библиотеки:
- openpyxl: для чтения данных из XLSX файлов.
- json: для работы с JSON данными.
- argparse: для парсинга аргументов командной строки.

Вспомогательные модули (из пакета 'helpers/'):
- Модули парсинга (например, `read_headers`, `read_lots_and_boundaries`):
  отвечают за извлечение конкретных блоков данных из XLSX.
- `postprocess` (содержит `normalize_lots_json_structure`, `replace_div0_with_null`):
  выполняет очистку и нормализацию структуры JSON-данных после парсинга.
- `json_to_markdown`: преобразует финальный JSON в Markdown-файл.

Запуск из командной строки:
python parse.py <путь_к_xlsx_файлу> <путь_к_выходному_json_файлу>

Аргументы:
  xlsx_path         Путь к входному XLSX файлу.
  output_json_path  Путь для сохранения выходного JSON файла. Markdown-файл
                    будет сохранен рядом с JSON с тем же именем, но расширением .md.
"""
import openpyxl
import json
import argparse
import os # os был в json_to_markdown, но если он используется здесь, то нужен импорт

# Предполагается, что эти модули находятся в директории 'helpers' и 'markdown_utils' относительно этого файла.
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
from helpers.read_contractors import read_contractors
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block

from markdown_utils.json_to_markdown import json_to_markdown


def parse_file(xlsx_path, output_json_path):
  """
  Основная функция для парсинга XLSX файла, постобработки данных,
  сохранения результата в JSON и генерации Markdown-отчета.

  Процесс включает следующие шаги:
  1. Загрузка XLSX файла и извлечение "сырых" данных по различным блокам
     (заголовки, информация об исполнителе, лоты с предложениями).
  2. Агрегация извлеченных данных в единую JSON-подобную структуру.
  3. Постобработка этой структуры:
     - Нормализация структуры лотов и предложений (`normalize_lots_json_structure`).
     - Замена строковых представлений ошибок деления на ноль на `None` (`replace_div0_with_null`).
  4. Сохранение финальной, обработанной структуры в указанный JSON файл.
  5. Генерация Markdown-файла на основе этой финальной JSON-структуры.

  Args:
    xlsx_path (str): Путь к входному XLSX файлу.
    output_json_path (str): Путь для сохранения выходного (обработанного) JSON файла.
                            Имя Markdown-файла будет производным от этого пути.
  
  Side effects:
    - Печатает результат вызова `read_contractors(ws)` в консоль (возможно, для отладки).
    - Создает или перезаписывает JSON файл (содержащий финальные, обработанные данные)
      по пути `output_json_path`.
    - Печатает сообщение об успешном сохранении JSON файла в консоль.
    - Создает или перезаписывает Markdown-файл в той же директории, что и
      `output_json_path`, с тем же базовым именем, но расширением .md.
    - Печатает сообщение об успешном сохранении Markdown файла в консоль
      (это сообщение выводится функцией `json_to_markdown`).
  """
  wb = openpyxl.load_workbook(xlsx_path, data_only=True)
  ws = wb.active
  
  # Внимание: отладочный вывод.
  print(read_contractors(ws)) 
  
  # 1 & 2. Первичный парсинг и агрегация
  result = {
    **read_headers(ws),
    "executor": read_executer_block(ws),
    "lots": read_lots_and_boundaries(ws),
    }
  
  # 3. Постобработка данных
  result = normalize_lots_json_structure(result)
  result = replace_div0_with_null(result)
    
  # 4. Сохранение финального JSON
  with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
  print(f"JSON saved to {output_json_path}")
  
  # 5. Генерация Markdown-отчета
  # json_to_markdown ожидает финальный, обработанный `result`
  json_to_markdown(result, output_json_path)

if __name__ == "__main__":
  parser = argparse.ArgumentParser(
      description="Парсер тендерного файла XLSX в JSON с последующей постобработкой и генерацией Markdown."
  )
  parser.add_argument("xlsx_path", type=str, help="Путь к входному XLSX файлу.")
  parser.add_argument("output_json_path", type=str, help="Путь для сохранения выходного JSON файла.")
  args = parser.parse_args()

  parse_file(args.xlsx_path, args.output_json_path)