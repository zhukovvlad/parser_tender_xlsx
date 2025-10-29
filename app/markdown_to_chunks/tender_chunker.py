"""
markdown_to_chunks/tender_chunker.py

Модуль для разделения Markdown-документа на смысловые чанки с использованием
библиотеки langchain-text-splitters и их последующей ручной очистки текста и метаданных.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_text_splitters import MarkdownHeaderTextSplitter

# Определяем заголовки, по которым будет происходить разделение текста,
# и соответствующие им ключи для метаданных, извлекаемых сплиттером.
HEADERS_TO_SPLIT_ON: List[Tuple[str, str]] = [
    ("#", "тендер"),  # H1 -> source_metadata["тендер"]
    ("##", "лоты"),  # H2 -> source_metadata["лоты"]
    ("###", "подрядчики"),  # H3 -> source_metadata["подрядчики"]
    ("####", "детальное_предложение"),  # H4 -> source_metadata["детальное_предложение"]
    ("#####", "разделы"),  # H5 -> source_metadata["разделы"]
    ("######", "позиции"),  # H6 -> source_metadata["позиции"]
]


def _manual_clean_text_content(text: Optional[str]) -> str:
    """
    Выполняет ручную очистку текстового контента.
    (Код этой функции остается без изменений)
    """
    if text is None:
        return ""
    cleaned_text = str(text)
    # 1. Markdown-разметка
    cleaned_text = re.sub(r"(\*\*|__)(.+?)(\1)", r"\2", cleaned_text)
    cleaned_text = re.sub(r"(?<![\wА-Яа-я])(\*|_)(.+?)(\1)(?![\wА-Яа-я])", r"\2", cleaned_text)
    # 2. Горизонтальные разделители (только Markdown HR - линии из 3+ дефисов)
    cleaned_text = re.sub(r"(?m)^\s*-{3,}\s*$", " ", cleaned_text)
    cleaned_text = cleaned_text.strip()
    # 3. Обрамляющие кавычки и пунктуация
    previous_text_state = None
    while cleaned_text != previous_text_state:
        previous_text_state = cleaned_text
        cleaned_text = cleaned_text.strip()
        made_change_this_iter = False
        if len(cleaned_text) >= 2:
            if cleaned_text[-1] in [".", ",", ";", "!", "?", ":"] and cleaned_text[-2] in ['"', "'", "»"]:
                cleaned_text = cleaned_text[:-1].strip()
                made_change_this_iter = True
                continue
            if (
                (cleaned_text.startswith('"') and cleaned_text.endswith('"'))
                or (cleaned_text.startswith("'") and cleaned_text.endswith("'"))
                or (cleaned_text.startswith("«") and cleaned_text.endswith("»"))
            ):
                cleaned_text = cleaned_text[1:-1]
                made_change_this_iter = True
        if not made_change_this_iter and cleaned_text == previous_text_state:
            break
    cleaned_text = cleaned_text.strip()
    # 4. Нормализация пробелов
    cleaned_text = re.sub(r"\s+", " ", cleaned_text)
    # 5. Финальный strip
    return cleaned_text.strip()


def _determine_h4_category(h4_header_text: Optional[str]) -> Optional[str]:
    """
    Определяет категорию H4-секции на основе очищенного текста ее заголовка.
    """
    if not h4_header_text:  # h4_header_text здесь уже должен быть очищен через _manual_clean_text_content
        return None

    text_lower = h4_header_text.lower()  # Очищенный текст уже не содержит Markdown
    if "основные сведения" in text_lower:
        return "сведения_о_подрядчике"
    elif "коммерческие условия" in text_lower:
        return "коммерческие_условия"
    elif "общие итоги" in text_lower:
        return "общие_итоги_подрядчика"
    elif "детализация позиций" in text_lower:
        return "детализация_позиций"
    return "другая_секция_h4"  # Категория по умолчанию для прочих H4


def create_chunks_from_markdown_text(
    markdown_text: str,
    tender_metadata: Dict[str, Any],
    lot_db_id: int,
    headers_to_split_on: Optional[List[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    """
    Разделяет Markdown-документ ОДНОГО лота на чанки и обогащает их метаданными.

    Args:
        markdown_text (str): Полный текст Markdown-документа для ОДНОГО лота.
        tender_metadata (Dict[str, Any]): Словарь с глобальными метаданными тендера.
        lot_db_id (int): Уникальный идентификатор лота из базы данных.
        headers_to_split_on (Optional[List[Tuple[str, str]]], optional):
            Конфигурация для `MarkdownHeaderTextSplitter`.

    Returns:
        List[Dict[str, Any]]: Список чанков для данного лота. Каждый чанк - это словарь
            с ключами "text" и "metadata". Метаданные включают глобальную информацию
            о тендере, ID лота и информацию, извлеченную из заголовков.
    """
    if headers_to_split_on is None:
        headers_to_split_on_actual = HEADERS_TO_SPLIT_ON
    else:
        headers_to_split_on_actual = headers_to_split_on

    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on_actual)
    docs_from_splitter = splitter.split_text(markdown_text)

    processed_chunks: List[Dict[str, Any]] = []

    # Извлекаем глобальные метаданные (они уже должны быть очищены на предыдущем этапе)
    base_tender_id = tender_metadata.get("tender_id")
    base_tender_title = tender_metadata.get("tender_title")
    base_tender_object = tender_metadata.get("tender_object")
    base_tender_address = tender_metadata.get("tender_address")
    base_executor_name = tender_metadata.get("executor_name")
    base_executor_phone = tender_metadata.get("executor_phone")
    base_executor_date = tender_metadata.get("executor_date")

    for doc in docs_from_splitter:
        source_metadata = doc.metadata  # Метаданные из заголовков от сплиттера langchain-text-splitters

        # Формируем словарь метаданных для текущего чанка, начиная с глобальных
        chunk_meta: Dict[str, Any] = {
            "tender_id": base_tender_id,
            "lot_id": lot_db_id,  # Добавляем точный ID лота из БД
            "tender_title": (base_tender_title.lower() if base_tender_title else None),  # Приводим к нижнему регистру
            "tender_object": base_tender_object.lower() if base_tender_object else None,
            "tender_address": (base_tender_address.lower() if base_tender_address else None),
            "executor_name": base_executor_name.lower() if base_executor_name else None,
            "executor_phone": base_executor_phone,  # Не преобразуем телефоны - структурированные данные
            "executor_date": base_executor_date,  # Не преобразуем даты - структурированные данные
        }

        # Добавляем и очищаем метаданные, извлеченные из заголовков Markdown текущего чанка
        if lot_title_raw := source_metadata.get("лоты"):
            chunk_meta["lot_title"] = _manual_clean_text_content(lot_title_raw).lower()

        if contractor_title_raw := source_metadata.get("подрядчики"):
            chunk_meta["contractor_title"] = _manual_clean_text_content(contractor_title_raw).lower()

        h4_full_text_raw = source_metadata.get("детальное_предложение")
        if h4_full_text_raw:
            cleaned_h4_title = _manual_clean_text_content(h4_full_text_raw).lower()
            chunk_meta["contractor_category_title"] = cleaned_h4_title

            h4_category = _determine_h4_category(cleaned_h4_title)
            if h4_category:
                chunk_meta["contractor_category"] = h4_category

        if section_h5_title_raw := source_metadata.get("разделы"):
            chunk_meta["contractor_section_title"] = _manual_clean_text_content(section_h5_title_raw).lower()

        if position_h6_title_raw := source_metadata.get("позиции"):
            chunk_meta["contractor_position_title"] = _manual_clean_text_content(position_h6_title_raw).lower()

        def _is_valid_metadata_value(value: Any) -> bool:
            if value is None:
                return False
            if isinstance(value, str):
                return value.strip() != ""
            return True

        final_cleaned_chunk_meta = {key: value for key, value in chunk_meta.items() if _is_valid_metadata_value(value)}

        cleaned_text_content = _manual_clean_text_content(doc.page_content)

        if cleaned_text_content:
            processed_chunks.append({"text": cleaned_text_content, "metadata": final_cleaned_chunk_meta})

    return processed_chunks
