"""
markdown_to_chunks/tender_chunker.py

Модуль для разделения Markdown-документа на смысловые чанки с использованием
библиотеки Langchain и их последующей ручной очистки текста и метаданных.

Назначение:
Этот модуль предоставляет функции для обработки Markdown-текста, сгенерированного
на предыдущих этапах обработки тендерной документации. Основная задача -
подготовить текстовые данные и их метаданные для последующей загрузки в векторные
базы данных или для других задач, требующих разделения текста на управляемые фрагменты (чанки).
Текстовое содержимое чанков и значения извлеченных метаданных (включая заголовки
разных уровней) подвергаются ручной очистке.

Основная функция:
- `create_chunks_from_markdown_text`: Принимает строку с Markdown-текстом и
  словарь с глобальными метаданными тендера. Разделяет текст на чанки,
  очищает текст и все поля метаданных каждого чанка, используя предоставленные
  глобальные метаданные для общей информации о тендере и извлекая специфичные
  метаданные из заголовков Markdown. Добавляет категоризацию для H4-секций.

Конфигурация разделения (`HEADERS_TO_SPLIT_ON`) определена как константа
внутри модуля.
"""

import re
from typing import List, Dict, Any, Tuple, Optional

from langchain.text_splitter import MarkdownHeaderTextSplitter

# Определяем заголовки, по которым будет происходить разделение текста,
# и соответствующие им ключи для метаданных, извлекаемых сплиттером.
HEADERS_TO_SPLIT_ON: List[Tuple[str, str]] = [
    ("#", "тендер"),                  # H1 -> source_metadata["тендер"]
    ("##", "лоты"),                   # H2 -> source_metadata["лоты"]
    ("###", "подрядчики"),            # H3 -> source_metadata["подрядчики"]
    ("####", "детальное_предложение"), # H4 -> source_metadata["детальное_предложение"]
    ("#####", "разделы"),             # H5 -> source_metadata["разделы"]
    ("######", "позиции")             # H6 -> source_metadata["позиции"]
]

def _manual_clean_text_content(text: Optional[str]) -> str:
    """
    Выполняет ручную очистку текстового контента от некоторых
    распространенных элементов Markdown и нормализует пробелы.
    Если на вход подан None, возвращает пустую строку.

    Логика очистки:
    1. Удаляет Markdown-разметку (жирный `**`, `__`; курсив `*`, `_` вокруг слов).
    2. Заменяет горизонтальные разделители `---` на пробел.
    3. Итеративно удаляет распространенные пары обрамляющих кавычек 
       (одинарные, двойные, «ёлочки») и пробелы вокруг них. Также пытается
       удалить одиночную пунктуацию на конце строки, если она идет сразу
       после закрывающей кавычки (например, "текст».").
    4. Нормализует все последовательности пробельных символов в один пробел.
    5. Удаляет начальные и конечные пробелы.
    """
    if text is None:
        return ""
    cleaned_text = str(text)
    # 1. Markdown-разметка
    cleaned_text = re.sub(r'(\*\*|__)(.+?)(\1)', r'\2', cleaned_text)
    cleaned_text = re.sub(r'(?<![\wА-Яа-я])(\*|_)(.+?)(\1)(?![\wА-Яа-я])', r'\2', cleaned_text)
    # 2. Горизонтальные разделители
    cleaned_text = cleaned_text.replace("---", " ")
    cleaned_text = cleaned_text.strip()
    # 3. Обрамляющие кавычки и пунктуация
    previous_text_state = None
    while cleaned_text != previous_text_state:
        previous_text_state = cleaned_text
        cleaned_text = cleaned_text.strip()
        made_change_this_iter = False
        if len(cleaned_text) >= 2:
            if cleaned_text[-1] in ['.', ',', ';', '!', '?', ':'] and cleaned_text[-2] in ['"', "'", '»']:
                cleaned_text = cleaned_text[:-1].strip()
                made_change_this_iter = True
                continue
            if (cleaned_text.startswith('"') and cleaned_text.endswith('"')) or \
               (cleaned_text.startswith("'") and cleaned_text.endswith("'")) or \
               (cleaned_text.startswith('«') and cleaned_text.endswith('»')):
                cleaned_text = cleaned_text[1:-1]
                made_change_this_iter = True
        if not made_change_this_iter and cleaned_text == previous_text_state:
            break
    cleaned_text = cleaned_text.strip()
    # 4. Нормализация пробелов
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    # 5. Финальный strip
    return cleaned_text.strip()


def _determine_h4_category(h4_header_text: Optional[str]) -> Optional[str]:
    """
    Определяет категорию H4-секции на основе очищенного текста ее заголовка.
    """
    if not h4_header_text: # h4_header_text здесь уже должен быть очищен через _manual_clean_text_content
        return None
    
    text_lower = h4_header_text.lower() # Очищенный текст уже не содержит Markdown
    if "основные сведения" in text_lower:
        return "сведения_о_подрядчике"
    elif "коммерческие условия" in text_lower:
        return "коммерческие_условия"
    elif "общие итоги" in text_lower: 
        return "общие_итоги_подрядчика"
    elif "детализация позиций" in text_lower:
        return "детализация_позиций"
    return "другая_секция_h4" # Категория по умолчанию для прочих H4


def create_chunks_from_markdown_text(
    markdown_text: str,
    global_initial_metadata: Dict[str, Any], 
    headers_to_split_on: Optional[List[Tuple[str, str]]] = None
) -> List[Dict[str, Any]]:
    """
    Разделяет Markdown-текст на чанки, очищает их текстовое содержимое и
    строковые метаданные, используя предоставленные глобальные метаданные.
    Добавляет категорию для H4-секций и использует описательные имена ключей
    для метаданных, извлеченных из заголовков.

    Args:
        markdown_text (str): Полный текст Markdown-документа для разделения.
        global_initial_metadata (Dict[str, Any]): Словарь с предварительно
            извлеченными и очищенными глобальными метаданными тендера.
            Ожидается, что содержит ключи "tender_id", "tender_title",
            "tender_object", "tender_address", "executor_name",
            "executor_phone", "executor_date".
        headers_to_split_on (Optional[List[Tuple[str, str]]], optional):
            Конфигурация для `MarkdownHeaderTextSplitter`. Если `None`,
            используется значение по умолчанию `HEADERS_TO_SPLIT_ON` из модуля.

    Returns:
        List[Dict[str, Any]]: Список чанков. Каждый чанк - это словарь
            с ключами "text" (очищенный текстовый контент) и "metadata"
            (очищенный словарь метаданных). Метаданные включают:
            - Глобальные поля: tender_id, tender_title, tender_object, tender_address,
              executor_name, executor_phone, executor_date.
            - Извлеченные из заголовков (очищенные): lot_title (H2),
              contractor_title (H3), contractor_category_title (H4),
              contractor_section_title (H5), contractor_position_title (H6).
            - Категория H4: contractor_category.
            Ключи добавляются в метаданные, только если их значение не None и не пустая строка.
    """
    if headers_to_split_on is None:
        headers_to_split_on_actual = HEADERS_TO_SPLIT_ON
    else:
        headers_to_split_on_actual = headers_to_split_on

    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on_actual)
    docs_from_splitter = splitter.split_text(markdown_text)

    processed_chunks: List[Dict[str, Any]] = []
    
    # Извлекаем глобальные метаданные (они уже должны быть очищены на предыдущем этапе)
    base_tender_id = global_initial_metadata.get("tender_id")
    base_tender_title = global_initial_metadata.get("tender_title")
    base_tender_object = global_initial_metadata.get("tender_object")
    base_tender_address = global_initial_metadata.get("tender_address")
    base_executor_name = global_initial_metadata.get("executor_name")
    base_executor_phone = global_initial_metadata.get("executor_phone")
    base_executor_date = global_initial_metadata.get("executor_date")

    for doc in docs_from_splitter:
        source_metadata = doc.metadata # Метаданные из заголовков от сплиттера Langchain

        # Формируем словарь метаданных для текущего чанка, начиная с глобальных
        chunk_meta: Dict[str, Any] = {
            "tender_id": base_tender_id, 
            "tender_title": base_tender_title.lower() if base_tender_title else None, # Приводим к нижнему регистру
            "tender_object": base_tender_object.lower() if base_tender_object else None,
            "tender_address": base_tender_address.lower() if base_tender_address else None,
            "executor_name": base_executor_name.lower() if base_executor_name else None,
            "executor_phone": base_executor_phone.lower() if base_executor_phone else None,
            "executor_date": base_executor_date.lower() if base_executor_date else None,
        }

        # Добавляем и очищаем метаданные, извлеченные из заголовков Markdown текущего чанка
        if lot_title_raw := source_metadata.get("лоты"): # H2
            chunk_meta["lot_title"] = _manual_clean_text_content(lot_title_raw).lower() # Приводим к нижнему регистру
        
        if contractor_title_raw := source_metadata.get("подрядчики"): # H3
            chunk_meta["contractor_title"] = _manual_clean_text_content(contractor_title_raw).lower() # Приводим к нижнему регистру

        # Обработка H4 заголовка (ключ "детальное_предложение" из HEADERS_TO_SPLIT_ON)
        h4_full_text_raw = source_metadata.get("детальное_предложение")
        if h4_full_text_raw:
            cleaned_h4_title = _manual_clean_text_content(h4_full_text_raw).lower() # Приводим к нижнему регистру
            chunk_meta["contractor_category_title"] = cleaned_h4_title # Очищенный текст H4
            
            h4_category = _determine_h4_category(cleaned_h4_title) # Категория на основе очищенного H4
            if h4_category: 
                chunk_meta["contractor_category"] = h4_category
        
        if section_h5_title_raw := source_metadata.get("разделы"): # H5
            chunk_meta["contractor_section_title"] = _manual_clean_text_content(section_h5_title_raw).lower() # Приводим к нижнему регистру

        if position_h6_title_raw := source_metadata.get("позиции"): # H6
            chunk_meta["contractor_position_title"] = _manual_clean_text_content(position_h6_title_raw).lower() # Приводим к нижнему регистру

        # Финальная очистка метаданных от ключей со значениями None или пустых строк
        final_cleaned_chunk_meta = {
            key: value for key, value in chunk_meta.items() if value # Оставляет не-None и непустые значения
        }
        
        # Очищаем основное текстовое содержимое чанка
        cleaned_text_content = _manual_clean_text_content(doc.page_content)

        # Добавляем чанк, только если основной текст после очистки не стал пустым
        if cleaned_text_content: 
            processed_chunks.append({
                "text": cleaned_text_content,
                "metadata": final_cleaned_chunk_meta
            })
            
    return processed_chunks