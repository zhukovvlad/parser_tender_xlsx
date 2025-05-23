"""
Модуль для считывания информации о заголовках контрагентов из листа Excel.

Этот модуль предоставляет функцию, которая сканирует определенный диапазон строк
на листе Excel для обнаружения строки, содержащей заголовки контрагентов.
Ключевым маркером для такой строки является наличие ячейки с текстом,
начинающимся с фразы, определенной в `constants.TABLE_PARSE_CONTRACTOR_TITLE`
(например, "наименование контрагента").

Для каждой непустой ячейки в найденной строке заголовков собирается информация,
включая ее значение, координаты и данные об объединении ячеек (если применимо).
"""

from typing import List, Dict, Any, Optional
from openpyxl.worksheet.worksheet import Worksheet

# Локальные импорты (из той же директории helpers)
from constants import TABLE_PARSE_CONTRACTOR_TITLE
from .build_merged_shape_map import build_merged_shape_map


def read_contractors(ws: Worksheet) -> Optional[List[Dict[str, Any]]]:
    """
    Ищет на листе Excel строку, содержащую заголовки с наименованиями контрагентов,
    и извлекает информацию о каждой ячейке-заголовке из этой строки.

    Функция сканирует строки листа в предопределенном диапазоне (с 4-й по 10-ю
    включительно). Строка считается строкой заголовков контрагентов, если одна
    из ее ячеек содержит текст, который (после удаления начальных/конечных
    пробелов и приведения к нижнему регистру) начинается с текста константы
    `TABLE_PARSE_CONTRACTOR_TITLE` (также приведенного к нижнему регистру).

    После нахождения такой строки, функция собирает информацию по каждой непустой
    ячейке в этой строке. Для каждой такой ячейки-заголовка определяется:
    - ее значение (`value`)
    - координаты (`coordinate`)
    - номер колонки (`column_start`)
    - номер строки, в которой найдены заголовки (`row_start`)
    - информация об объединении ячеек (`merged_shape`), если ячейка является
      частью объединенного диапазона (с использованием `build_merged_shape_map`).

    Args:
        ws (Worksheet): Лист Excel (объект openpyxl.worksheet.worksheet.Worksheet),
            на котором осуществляется поиск.

    Returns:
        Optional[List[Dict[str, Any]]]:
            - Список словарей, если строка заголовков контрагентов найдена.
              Каждый словарь в списке представляет одну непустую ячейку-заголовок
              из найденной строки (включая ячейку, послужившую маркером,
              и последующие ячейки с именами подрядчиков или другой информацией).
              Структура словаря:
                {
                    "value": Any,  # Значение из ячейки-заголовка
                    "coordinate": str,  # Координата ячейки (например, "D4")
                    "column_start": int,  # Номер колонки ячейки (1-индексация)
                    "row_start": int,  # Номер строки, где найдены заголовки (1-индексация)
                    "merged_shape": Optional[Dict[str, int]] # Словарь {"rowspan": x, "colspan": y},
                                                            # если ячейка объединена. Отсутствует, если не объединена.
                }
            - `None`, если строка заголовков контрагентов не найдена в диапазоне
              строк с 4-й по 10-ю.
    """
    # Префикс для поиска, приводим к нижнему регистру для регистронезависимого сравнения
    search_prefix_lower = TABLE_PARSE_CONTRACTOR_TITLE.lower()

    # Получаем карту всех объединенных ячеек на листе для быстрого доступа
    merged_cells_map = build_merged_shape_map(ws)

    # Итерируемся по заданному диапазону строк (с 4-й по 10-ю) для поиска заголовков
    for row_tuple in ws.iter_rows(min_row=4, max_row=10, max_col=ws.max_column):
        # row_tuple - это кортеж объектов openpyxl.cell.Cell для текущей строки
        for cell in row_tuple:
            cell_value = cell.value
            # Проверяем, содержит ли ячейка искомый префикс (регистронезависимо)
            if isinstance(cell_value, str) and \
               cell_value.strip().lower().startswith(search_prefix_lower):
                
                # Если префикс найден, эта строка считается строкой заголовков контрагентов.
                # Собираем информацию о каждой непустой ячейке в этой найденной строке.
                contractor_headers_list: List[Dict[str, Any]] = []
                for header_cell in row_tuple: # Итерируемся по всем ячейкам найденной строки
                    if header_cell.value is not None: # Обрабатываем только непустые ячейки
                        cell_info: Dict[str, Any] = {
                            "value": header_cell.value,
                            "coordinate": header_cell.coordinate,
                            "column_start": header_cell.column, # 1-индексированная колонка
                            "row_start": header_cell.row,       # 1-индексированная строка (будет одинакова для всех header_cell)
                        }

                        # Если ячейка является частью объединенного диапазона, добавляем информацию об этом
                        if header_cell.coordinate in merged_cells_map:
                            cell_info["merged_shape"] = merged_cells_map[header_cell.coordinate]
                        
                        contractor_headers_list.append(cell_info)
                
                # Возвращаем список информации о ячейках-заголовках, если он не пуст.
                # (он будет не пуст, так как как минимум ячейка с префиксом будет добавлена)
                if contractor_headers_list:
                    return contractor_headers_list
                # Если строка, содержащая префикс, не содержит никаких непустых ячеек 
                # (включая саму ячейку с префиксом, что маловероятно), поиск продолжается.
                # Однако, по текущей логике, если префикс найден, список всегда будет содержать хотя бы один элемент.

    # Если ни одна строка в заданном диапазоне не содержит искомый префикс
    return None