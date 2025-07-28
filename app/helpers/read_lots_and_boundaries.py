# helpers/read_lots_and_boundaries.py

"""
Модуль для определения границ лотов и запуска процесса сбора данных.

Назначение:
    Этот модуль выполняет ключевую роль в разделении данных по лотам. Его
    основная функция, `read_lots_and_boundaries`, отвечает за первичное
    сканирование листа Excel с целью идентификации точных диапазонов строк
    для каждого лота.

    После определения этих границ, он выступает в роли "стартовой площадки",
    вызывая более низкоуровневую функцию `get_proposals` для каждого
    найденного лота и передавая ей вычисленные границы. Это гарантирует,
    что весь последующий парсинг будет происходить в контексте
    одного, изолированного лота.
"""

from typing import Dict, Any, List
from openpyxl.worksheet.worksheet import Worksheet

# Импорт констант
from ..constants import (
    JSON_KEY_LOT_INDEX,
    JSON_KEY_LOT_TITLE,
    JSON_KEY_PROPOSALS,
    PARSE_TABLE_LOT_NUMBER,
    START_INDEXING_LOT_ROW
)
# Локальный импорт. ПРИМЕЧАНИЕ: эту функцию нужно будет изменить следующей.
from .get_proposals import get_proposals


def read_lots_and_boundaries(ws: Worksheet) -> Dict[str, Dict[str, Any]]:
    """
    Находит все лоты на листе, определяет их границы и запускает сбор данных.

    Функция реализует двухэтапный подход для обеспечения точного разделения
    данных по лотам.

    Логика работы:
    1.  **Этап 1: Поиск начальных строк.** Функция сначала проходит по листу
        Excel (начиная со строки `START_INDEXING_LOT_ROW`) и ищет ячейки
        в 4-й колонке ('D'), которые служат маркерами начала нового лота
        (например, содержат текст "лот №"). Для каждого найденного маркера
        в список `lot_starts` сохраняется его название и номер строки.

    2.  **Этап 2: Определение границ и делегирование.** Затем функция
        обрабатывает список `lot_starts`. Для каждого лота в списке:
        - Определяется его конечная строка (`end_row`). Для всех лотов,
          кроме последнего, `end_row` — это номер строки, где начинается
          следующий лот, минус один. Для последнего лота — это последняя
          строка на листе.
        - Вызывается функция `get_proposals`, которой передаются
          вычисленные границы `start_row` и `end_row`.
        - Результат, возвращённый `get_proposals`, сохраняется в итоговый
          словарь `found_lots_data`.

    Args:
        ws (Worksheet): Активный лист Excel для анализа.

    Returns:
        Dict[str, Dict[str, Any]]: Словарь, где ключи — это сгенерированные
        идентификаторы лотов (например, "lot_1"), а значения — словари,
        содержащие название лота и словарь с предложениями подрядчиков,
        корректно отфильтрованными для данного лота.
    """
    max_sheet_row = ws.max_row
    lot_starts: List[Dict[str, Any]] = []

    # --- ШАГ 1: Находим начальные строки всех лотов ---
    for current_row_num in range(START_INDEXING_LOT_ROW, max_sheet_row + 1):
        cell_value_col_d = ws.cell(row=current_row_num, column=4).value

        if isinstance(cell_value_col_d, str) and \
           cell_value_col_d.strip().lower().startswith(PARSE_TABLE_LOT_NUMBER.lower()):
            
            lot_starts.append({
                'start_row': current_row_num,
                'title': cell_value_col_d.strip()
            })

    if not lot_starts:
        return {}

    # --- ШАГ 2: Определяем границы и извлекаем данные для каждого лота ---
    found_lots_data: Dict[str, Dict[str, Any]] = {}
    
    for i, lot_info in enumerate(lot_starts):
        start_row = lot_info['start_row']
        lot_title = lot_info['title']

        # Определяем конечную строку
        if i + 1 < len(lot_starts):
            # Если это не последний лот, он заканчивается перед началом следующего
            end_row = lot_starts[i + 1]['start_row'] - 1
        else:
            # Если это последний лот, он заканчивается в конце листа
            end_row = max_sheet_row

        # ПРИМЕЧАНИЕ: Следующий шаг - изменить get_proposals, чтобы он принимал
        # start_row и end_row.
        proposals = get_proposals(
            ws,
            start_row=start_row,
            end_row=end_row
        )

        lot_key = f"{JSON_KEY_LOT_INDEX}{i + 1}"
        found_lots_data[lot_key] = {
            JSON_KEY_LOT_TITLE: lot_title,
            JSON_KEY_PROPOSALS: proposals
        }
            
    return found_lots_data