"""
postprocess.py (Отрефакторенная версия)

Модуль для постобработки JSON-данных, полученных после парсинга.

Содержит набор функций для очистки, стандартизации и обогащения данных.
Ключевые возможности включают:
- Нормализация структуры лотов путем отделения "Расчетной стоимости".
- Рекурсивная замена ошибок деления на ноль на None.
- Аннотация позиций иерархическими полями (is_chapter, chapter_ref).

Функции спроектированы так, чтобы минимизировать побочные эффекты,
возвращая новые, измененные копии данных вместо модификации на месте.
"""

import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..constants import (
    JSON_KEY_BASELINE_PROPOSAL, JSON_KEY_CHAPTER_NUMBER,
    JSON_KEY_CHAPTER_REF, JSON_KEY_CONTRACTOR_ADDITIONAL_INFO,
    JSON_KEY_CONTRACTOR_INDEX, JSON_KEY_CONTRACTOR_ITEMS,
    JSON_KEY_CONTRACTOR_POSITIONS, JSON_KEY_CONTRACTOR_SUMMARY,
    JSON_KEY_CONTRACTOR_TITLE, JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
    JSON_KEY_IS_CHAPTER, JSON_KEY_LOTS, JSON_KEY_PROPOSALS,
    JSON_KEY_TOTAL_COST, TABLE_PARSE_BASELINE_COST
)

DIV_ZERO_ERROR_STRINGS = {"div/0", "#div/0!", "деление на 0"}

class DataIntegrityError(Exception):
    """Вызывается, когда структура данных не соответствует ожиданиям."""
    pass


# --- Вспомогательные ("приватные") функции ---

def _separate_proposals(
    proposals_in_lot: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Разделяет словарь предложений на "Расчетную стоимость" и "реальные" предложения.

    Args:
        proposals_in_lot: Исходный словарь предложений из одного лота.

    Returns:
        Кортеж из двух элементов:
        1. Словарь с данными "Расчетной стоимости" или None, если не найден.
        2. Словарь с "реальными" предложениями, где ключ - название подрядчика.
    """
    baseline_proposal = None
    actual_proposals = {}

    for _, proposal_data in proposals_in_lot.items():
        title = str(proposal_data.get(JSON_KEY_CONTRACTOR_TITLE, "")).strip().lower()
        if title == TABLE_PARSE_BASELINE_COST:
            baseline_proposal = proposal_data
        elif title: # Добавляем только предложения с непустым названием
            actual_proposals[proposal_data[JSON_KEY_CONTRACTOR_TITLE]] = proposal_data

    return baseline_proposal, actual_proposals


def _is_value_zero(value: Any) -> bool:
    """
    Проверяет, является ли значение "нулевым" по набору правил.
    Учитывает числовые, строковые и None представления нуля.
    """
    if value in (None, 0, "0", "0.0", "", "0,0"):
        return True
    if isinstance(value, str) and value.strip().lower() in {"0", "0.0", "0,0", "none"}:
        return True
    return False


def _is_baseline_valid(baseline_proposal: Optional[Dict[str, Any]]) -> bool:
    """
    Проверяет, содержит ли "Расчетная стоимость" хотя бы одно ненулевое итоговое значение.

    Args:
        baseline_proposal: Словарь с данными "Расчетной стоимости".

    Returns:
        True, если найдено хотя бы одно значащее итоговое значение, иначе False.
    """
    if not baseline_proposal:
        return False

    summary_data = baseline_proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
    all_total_values = []
    for summary_block in summary_data.values():
        if isinstance(summary_block, dict):
            total_cost_detail = summary_block.get(JSON_KEY_TOTAL_COST, {})
            if isinstance(total_cost_detail, dict):
                all_total_values.extend(total_cost_detail.values())

    return any(not _is_value_zero(val) for val in all_total_values)


def _clean_deviation_fields(proposals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Возвращает глубокую копию словаря предложений, удалив из всех позиций
    и итогов поля, связанные с отклонением от расчетной стоимости.
    """
    cleaned_proposals = copy.deepcopy(proposals)
    for proposal in cleaned_proposals.values():
        items_data = proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {})
        if not isinstance(items_data, dict):
            continue

        for pos_item in items_data.get(JSON_KEY_CONTRACTOR_POSITIONS, {}).values():
            if isinstance(pos_item, dict):
                pos_item.pop(JSON_KEY_DEVIATION_FROM_CALCULATED_COST, None)

        if JSON_KEY_CONTRACTOR_SUMMARY in items_data:
            items_data[JSON_KEY_CONTRACTOR_SUMMARY].pop(JSON_KEY_DEVIATION_FROM_CALCULATED_COST, None)
            
    return cleaned_proposals


# --- Основные публичные функции ---

def normalize_lots_json_structure(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Оркестрирует полную нормализацию структуры данных по лотам.

    Выполняет следующие шаги для каждого лота:
    1. Отделяет предложение "Расчетная стоимость" от предложений реальных подрядчиков.
    2. Проверяет "Расчетную стоимость" на наличие значащих данных.
    3. Если "Расчетная стоимость" невалидна, очищает поля отклонений у подрядчиков.
    4. Аннотирует иерархией все позиции подрядчиков.
    5. Переиндексирует подрядчиков и формирует финальную структуру лота.

    Args:
        data: Исходный словарь с данными всего тендера.

    Returns:
        Новый словарь с полностью нормализованной структурой.
    """
    processed_data = copy.deepcopy(data)
    lots_data = processed_data.get(JSON_KEY_LOTS, {})

    for lot_key, lot_content in lots_data.items():
        proposals_in_lot = lot_content.get(JSON_KEY_PROPOSALS, {})
        
        baseline_proposal, actual_proposals = _separate_proposals(proposals_in_lot)
        
        if _is_baseline_valid(baseline_proposal) and baseline_proposal:
            baseline_proposal.pop(JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, None)
            lot_content[JSON_KEY_BASELINE_PROPOSAL] = baseline_proposal
        else:
            lot_content[JSON_KEY_BASELINE_PROPOSAL] = {JSON_KEY_CONTRACTOR_TITLE: "Расчетная стоимость отсутствует"}
            actual_proposals = _clean_deviation_fields(actual_proposals)
            
        reindexed_proposals = {}
        for idx, proposal in enumerate(actual_proposals.values(), 1):
            items = proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {})
            positions = items.get(JSON_KEY_CONTRACTOR_POSITIONS)
            
            if positions:
                annotated_positions = annotate_structure_fields(positions)
                items[JSON_KEY_CONTRACTOR_POSITIONS] = annotated_positions
            
            reindexed_proposals[f"{JSON_KEY_CONTRACTOR_INDEX}{idx}"] = proposal
            
        lot_content[JSON_KEY_PROPOSALS] = reindexed_proposals
        
    return processed_data


def replace_div0_with_null(data: Any) -> Any:
    """
    Рекурсивно заменяет строки ошибок деления на ноль на None.

    Args:
        data: Входная структура (словарь, список или примитивный тип).

    Returns:
        Новая структура данных того же типа, очищенная от ошибок.
    """
    if isinstance(data, dict):
        return {k: replace_div0_with_null(v) for k, v in data.items()}
    if isinstance(data, list):
        return [replace_div0_with_null(item) for item in data]
    if isinstance(data, str) and data.strip().lower() in DIV_ZERO_ERROR_STRINGS:
        return None
    return data


def annotate_structure_fields(positions: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Добавляет иерархические поля 'is_chapter' и 'chapter_ref' в каждую позицию.

    Сортирует позиции по числовым ключам для корректного определения
    принадлежности к разделам.

    Args:
        positions: Словарь позиций, где ключи - строковые номера.

    Returns:
        Новый словарь с аннотированными позициями.
    """
    if not isinstance(positions, dict):
        return {}

    # Работаем с копией, чтобы не изменять оригинал
    positions_copy = copy.deepcopy(positions)
    
    try:
        # Сортируем по числовым ключам для правильного порядка обработки
        sorted_items: List[Tuple[str, Dict[str, Any]]] = sorted(
            positions_copy.items(), key=lambda item: int(item[0])
        )
    except (ValueError, TypeError):
        logging.warning(
            f"Не удалось отсортировать позиции по числовым ключам: {list(positions.keys())}. "
            f"Логика 'chapter_ref' может быть нарушена."
        )
        sorted_items = list(positions_copy.items())

    current_chapter_number: Optional[str] = None
    for key, pos_item in sorted_items:
        if not isinstance(pos_item, dict):
            raise DataIntegrityError(
                f"Обнаружена некорректная позиция с ключом '{key}'. "
                f"Ожидался словарь, но получен тип {type(pos_item).__name__}."
            )

        section_num = pos_item.get(JSON_KEY_CHAPTER_NUMBER)
        is_chapter = bool(section_num)
        pos_item[JSON_KEY_IS_CHAPTER] = is_chapter

        if is_chapter:
            current_chapter_number = str(section_num)
            # Если это подраздел (напр., "1.1"), ссылка на родителя - "1"
            if "." in current_chapter_number:
                parent_ref = ".".join(current_chapter_number.split(".")[:-1])
                pos_item[JSON_KEY_CHAPTER_REF] = parent_ref
            else: # Раздел верхнего уровня
                pos_item[JSON_KEY_CHAPTER_REF] = None
        else:
            # Обычная позиция ссылается на текущий активный раздел
            pos_item[JSON_KEY_CHAPTER_REF] = current_chapter_number
            
    # Собираем итоговый словарь из измененных данных
    final_positions = {key: value for key, value in sorted_items}
    return final_positions
