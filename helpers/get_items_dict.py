"""
Модуль для генерации шаблонных словарей позиций тендера.

Предоставляет функцию для создания стандартизированной структуры данных (словаря)
для одной позиции работ или материалов. Структура включает как общие поля,
так и поля, специфичные для данных подрядчика, количество которых зависит
от параметра `contractor_colspan`. Это упрощает последующее заполнение
данными при парсинге.
"""

from typing import Dict, Any
from constants import (
    JSON_KEY_ARTICLE_SMR,
    JSON_KEY_CHAPTER_NUMBER,
    JSON_KEY_COMMENT_CONTRACTOR,
    JSON_KEY_COMMENT_ORGANIZER,
    JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
    JSON_KEY_INDIRECT_COSTS,
    JSON_KEY_JOB_TITLE,
    JSON_KEY_JOB_TITLE_NORMALIZED,
    JSON_KEY_MATERIALS,
    JSON_KEY_NUMBER,
    JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
    JSON_KEY_QUANTITY,
    JSON_KEY_SUGGESTED_QUANTITY,
    JSON_KEY_TOTAL,
    JSON_KEY_TOTAL_COST,
    JSON_KEY_UNIT,
    JSON_KEY_UNIT_COST,
    JSON_KEY_WORKS,
)

def get_items_dict(contractor_colspan: int) -> Dict[str, Any]:
    """
    Возвращает шаблонный словарь для представления одной позиции (строки)
    работ или материалов, включая специфичные для подрядчика поля.

    Структура возвращаемого словаря состоит из общей части, описывающей позицию
    (например, порядковый номер, наименование работ), и части с данными
    подрядчика, которая варьируется в зависимости от параметра `contractor_colspan`.
    Все значения в шаблонном словаре по умолчанию установлены в `None`.
    Блоки стоимостей (`unit_cost`, `total_cost`) являются вложенными словарями.

    Эта функция используется для создания базовой структуры, которая затем
    заполняется фактическими данными при парсинге строк из Excel.

    Args:
        contractor_colspan (int): Количество столбцов (colspan), которое занимают
            данные конкретного подрядчика на листе Excel. Это значение определяет
            набор полей, относящихся к подрядчику, которые будут включены
            в результирующий словарь. Поддерживаемые значения: 12, 11, 10, 9, 8.

    Returns:
        Dict[str, Any]: Словарь-шаблон, представляющий одну позицию. Содержит общие
            поля и поля, специфичные для подрядчика. Если передан
            неподдерживаемый `contractor_colspan`, словарь будет содержать
            общие поля и дополнительный ключ "error".

    Структура возвращаемого словаря:

    Общие поля (всегда присутствуют):
        - `JSON_KEY_NUMBER`: None (Порядковый номер)
        - `JSON_KEY_CHAPTER_NUMBER`: None (Номер раздела)
        - `JSON_KEY_ARTICLE_SMR`: None (Статья СМР)
        - `JSON_KEY_JOB_TITLE`: None (Наименование работ/материалов)
        - `JSON_KEY_COMMENT_ORGANIZER`: None (Комментарий организатора)
        - `JSON_KEY_UNIT`: None (Единица измерения)
        - `JSON_KEY_QUANTITY`: None (Количество от организатора)

    Поля, зависящие от `contractor_colspan` (добавляются к общим полям):

    Если `contractor_colspan` == 12:
        - `JSON_KEY_SUGGESTED_QUANTITY`: None (Предлагаемое количество подрядчиком)
        - `JSON_KEY_UNIT_COST`: {
            `JSON_KEY_MATERIALS`: None, `JSON_KEY_WORKS`: None,
            `JSON_KEY_INDIRECT_COSTS`: None, `JSON_KEY_TOTAL`: None
          } (Стоимость за единицу)
        - `JSON_KEY_TOTAL_COST`: {
            `JSON_KEY_MATERIALS`: None, `JSON_KEY_WORKS`: None,
            `JSON_KEY_INDIRECT_COSTS`: None, `JSON_KEY_TOTAL`: None
          } (Стоимость всего по предложению подрядчика)
        - `JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST`: None (Стоимость всего за объемы заказчика)
        - `JSON_KEY_COMMENT_CONTRACTOR`: None (Комментарий участника)
        - `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`: None (Отклонение от расчетной стоимости)

    Если `contractor_colspan` == 11:
        - `JSON_KEY_SUGGESTED_QUANTITY`: None
        - `JSON_KEY_UNIT_COST`: (аналогично colspan 12)
        - `JSON_KEY_TOTAL_COST`: (аналогично colspan 12)
        - `JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST`: None
        - `JSON_KEY_COMMENT_CONTRACTOR`: None  (Примечание: соответствует коду, ранее в докстринге отсутствовало)
        - `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`: None

    Если `contractor_colspan` == 10:
        - `JSON_KEY_UNIT_COST`: (аналогично colspan 12)
        - `JSON_KEY_TOTAL_COST`: (аналогично colspan 12)
        - `JSON_KEY_COMMENT_CONTRACTOR`: None
        - `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`: None

    Если `contractor_colspan` == 9:
        - `JSON_KEY_UNIT_COST`: (аналогично colspan 12)
        - `JSON_KEY_TOTAL_COST`: (аналогично colspan 12)
        - `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`: None

    Если `contractor_colspan` == 8:
        - `JSON_KEY_UNIT_COST`: (аналогично colspan 12)
        - `JSON_KEY_TOTAL_COST`: (аналогично colspan 12)

    Если `contractor_colspan` имеет другое (неподдерживаемое) значение:
        - "error": "Unknown contractor_colspan: {значение contractor_colspan}"
          (также будут присутствовать общие поля).
    """
    # Базовая структура элемента (общие поля для всех позиций)
    item: Dict[str, Any] = {
        JSON_KEY_NUMBER: None,
        JSON_KEY_CHAPTER_NUMBER: None,
        JSON_KEY_ARTICLE_SMR: None,
        JSON_KEY_JOB_TITLE: None,
        JSON_KEY_COMMENT_ORGANIZER: None,
        JSON_KEY_UNIT: None,
        JSON_KEY_QUANTITY: None
    }

    # Шаблон для вложенных блоков стоимости (единичной и общей)
    cost_block_template: Dict[str, Any] = {
        JSON_KEY_MATERIALS: None,
        JSON_KEY_WORKS: None,
        JSON_KEY_INDIRECT_COSTS: None,
        JSON_KEY_TOTAL: None
    }

    contractor_specific_data: Dict[str, Any] = {}

    # Определение специфичных для подрядчика полей на основе colspan
    if contractor_colspan == 12:
        contractor_specific_data = {
            JSON_KEY_SUGGESTED_QUANTITY: None,
            JSON_KEY_UNIT_COST: cost_block_template.copy(),
            JSON_KEY_TOTAL_COST: cost_block_template.copy(),
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST: None,
            JSON_KEY_COMMENT_CONTRACTOR: None,
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST: None
        }
    elif contractor_colspan == 11:
        contractor_specific_data = {
            JSON_KEY_SUGGESTED_QUANTITY: None,
            JSON_KEY_UNIT_COST: cost_block_template.copy(),
            JSON_KEY_TOTAL_COST: cost_block_template.copy(),
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST: None,
            JSON_KEY_COMMENT_CONTRACTOR: None, # Присутствует в коде, отражено в докстринге
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST: None
        }
    elif contractor_colspan == 10:
        contractor_specific_data = {
            JSON_KEY_UNIT_COST: cost_block_template.copy(),
            JSON_KEY_TOTAL_COST: cost_block_template.copy(),
            JSON_KEY_COMMENT_CONTRACTOR: None,
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST: None
        }
    elif contractor_colspan == 9:
        contractor_specific_data = {
            JSON_KEY_UNIT_COST: cost_block_template.copy(),
            JSON_KEY_TOTAL_COST: cost_block_template.copy(),
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST: None
        }
    elif contractor_colspan == 8:
        contractor_specific_data = {
            JSON_KEY_UNIT_COST: cost_block_template.copy(),
            JSON_KEY_TOTAL_COST: cost_block_template.copy()
        }
    else:
        # Обработка неподдерживаемого значения colspan
        contractor_specific_data = {"error": f"Unknown contractor_colspan: {contractor_colspan}"}

    # Объединяем общую часть (item) с частью, специфичной для подрядчика
    return {**item, **contractor_specific_data}