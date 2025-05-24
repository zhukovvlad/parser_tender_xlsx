"""
scripts/tender_chunk.py

Скрипт для разделения Markdown-документа (отчета по тендеру) на смысловые чанки
с использованием библиотеки Langchain и сохранения их в JSON-файл.

Назначение:
Этот скрипт является частью конвейера обработки тендерной документации. Он берет
Markdown-файл, сгенерированный на предыдущих этапах (например, `parse.py` и
`markdown_utils/json_to_markdown.py`), и подготавливает его содержимое для
последующей загрузки в векторные базы данных или для других задач, требующих
разделения текста на управляемые фрагменты (чанки).

Принцип работы:
1.  Загружает Markdown-текст из указанного входного файла (по умолчанию 'test_1.md').
2.  Определяет структуру заголовков Markdown, по которым будет производиться разделение.
3.  Использует `langchain.text_splitter.MarkdownHeaderTextSplitter` для разделения
    текста на чанки. Каждый чанк содержит как сам текстовый фрагмент (`page_content`),
    так и метаданные, извлеченные из заголовков, под которыми этот фрагмент находился.
4.  Для каждого чанка метаданные дополнительно обрабатываются:
    -   Из заголовка первого уровня ("тендер") извлекаются ID и название тендера.
    -   Формируется стандартизированный словарь метаданных для чанка.
5.  Результат (список чанков, каждый с текстом и метаданными) сохраняется
    в JSON-файл (по умолчанию 'tender_chunks.json'). Этот файл затем может
    обрабатываться следующим скриптом (например, Файл 15 - `clean_tender_chunks.py`)
    для финальной очистки перед созданием эмбеддингов.

Конфигурация:
-   Имена входного/выходного файлов и правила разделения по заголовкам
    в текущей версии жестко заданы в коде, но могут быть вынесены
    в аргументы командной строки или конфигурационный файл для большей гибкости.
"""

import re
import json
from typing import List, Dict, Any, Tuple, Optional

# Предполагается, что библиотека langchain установлена (см. requirements.txt)
from langchain.text_splitter import MarkdownHeaderTextSplitter

# --- Конфигурация скрипта ---
# Имена файлов можно сделать аргументами командной строки для гибкости
INPUT_MARKDOWN_FILE = "test_1.md" # Или путь к .md файлу, сгенерированному parse.py
OUTPUT_CHUNKS_FILE = "tender_chunks.json"

# Определяем заголовки, по которым будет происходить разделение текста,
# и соответствующие им ключи для метаданных.
# Формат: (символ_заголовка, имя_ключа_в_метаданных)
HEADERS_TO_SPLIT_ON: List[Tuple[str, str]] = [
    ("#", "тендер"),                  # Заголовок H1 -> ключ "тендер"
    ("##", "лоты"),                   # Заголовок H2 -> ключ "лоты"
    ("###", "подрядчики"),            # Заголовок H3 -> ключ "подрядчики"
    ("####", "детальное_предложение"), # Заголовок H4 -> ключ "детальное_предложение"
    ("#####", "разделы"),             # Заголовок H5 -> ключ "разделы"
    ("######", "позиции")             # Заголовок H6 -> ключ "позиции"
]
# ----------------------------------

def extract_tender_id_and_title(tender_header_text: str) -> Tuple[Optional[str], str]:
    """
    Извлекает ID и название тендера из строки заголовка первого уровня.

    Ожидаемый формат строки: "Тендер №<ID> «<Название тендера>»"
    или "Тендер <ID> «<Название тендера>»". Кавычки вокруг названия опциональны.

    Args:
        tender_header_text (str): Текст заголовка H1, содержащий информацию о тендере.

    Returns:
        Tuple[Optional[str], str]: Кортеж (tender_id, tender_title).
            tender_id может быть None, если не найден.
            tender_title будет либо извлеченным названием, либо исходной строкой
            заголовка, если разбор не удался.
    """
    if not tender_header_text:
        return None, ""
        
    # Регулярное выражение для извлечения ID (группа 1) и названия (группа 2)
    # № - опционально, кавычки вокруг названия - опциональны
    match = re.match(r"Тендер\s+№?(\S+)\s+\"{0,2}(.*?)\"{0,2}$", tender_header_text.strip())
    if match:
        tender_id = match.group(1)
        tender_title = match.group(2).strip()
        return tender_id, tender_title
    else:
        # Если точный формат не совпал, пытаемся извлечь хотя бы ID, если он в начале
        parts = tender_header_text.split(" ", 2) # "Тендер", "№ID", "Название"
        if len(parts) > 1 and parts[0].lower() == "тендер":
            id_candidate = parts[1].replace("№", "")
            title_candidate = parts[2] if len(parts) > 2 else id_candidate # Если нет названия, используем ID или сам заголовок
            return id_candidate, title_candidate.strip()

    # Если не удалось разобрать, возвращаем None для ID и исходный текст как название (после strip)
    return None, tender_header_text.strip()


def create_chunks_from_markdown(markdown_text: str) -> List[Dict[str, Any]]:
    """
    Разделяет Markdown-текст на чанки и формирует для них метаданные.

    Args:
        markdown_text (str): Полный текст Markdown-документа.

    Returns:
        List[Dict[str, Any]]: Список чанков. Каждый чанк - это словарь
            с ключами "text" (текст чанка) и "metadata" (словарь метаданных).
    """
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=HEADERS_TO_SPLIT_ON)
    docs_from_splitter = splitter.split_text(markdown_text)

    embedding_chunks: List[Dict[str, Any]] = []
    for doc in docs_from_splitter:
        # doc.metadata содержит ключи, определенные в HEADERS_TO_SPLIT_ON
        # (например, "тендер", "лоты" и т.д.) со значениями из заголовков.
        source_metadata = doc.metadata

        # Извлекаем и парсим заголовок тендера (H1)
        tender_h1_text = source_metadata.get("тендер", "")
        tender_id_val, tender_title_val = extract_tender_id_and_title(tender_h1_text)

        # Формируем наш собственный, более структурированный словарь метаданных
        chunk_meta: Dict[str, Optional[str]] = {
            "tender_id": tender_id_val,
            "tender_title": tender_title_val,
            "lot": source_metadata.get("лоты"),
            "contractor": source_metadata.get("подрядчики"),
            # "detailed_proposal_context": source_metadata.get("детальное_предложение"), # Если нужно
            "section": source_metadata.get("разделы"),
            "position": source_metadata.get("позиции"),
        }
        
        # Очищаем метаданные от None значений для более компактного JSON
        cleaned_chunk_meta = {k: v for k, v in chunk_meta.items() if v is not None and v.strip() != ""}

        embedding_chunks.append({
            "text": doc.page_content.strip(),  # Текстовое содержимое чанка
            "metadata": cleaned_chunk_meta     # Очищенные метаданные
        })
    
    return embedding_chunks

def main():
    """
    Главная функция скрипта: загрузка Markdown, разделение на чанки и сохранение в JSON.
    """
    print(f"Загрузка Markdown-документа из файла: {INPUT_MARKDOWN_FILE}...")
    try:
        with open(INPUT_MARKDOWN_FILE, "r", encoding="utf-8") as f:
            markdown_content = f.read()
    except FileNotFoundError:
        print(f"Ошибка: Файл '{INPUT_MARKDOWN_FILE}' не найден.")
        return
    except Exception as e:
        print(f"Ошибка при чтении файла '{INPUT_MARKDOWN_FILE}': {e}")
        return

    print(f"Разделение документа на чанки (используя {len(HEADERS_TO_SPLIT_ON)} уровней заголовков)...")
    chunks_for_embedding = create_chunks_from_markdown(markdown_content)
    print(f"Получено {len(chunks_for_embedding)} чанков.")

    print(f"Сохранение чанков в файл: {OUTPUT_CHUNKS_FILE}...")
    try:
        with open(OUTPUT_CHUNKS_FILE, "w", encoding="utf-8") as f:
            json.dump(chunks_for_embedding, f, ensure_ascii=False, indent=2)
        print(f"Данные успешно сохранены в '{OUTPUT_CHUNKS_FILE}'.")
    except IOError as e:
        print(f"Ошибка при записи в файл '{OUTPUT_CHUNKS_FILE}': {e}")
    except Exception as e:
        print(f"Непредвиденная ошибка при сохранении JSON: {e}")


if __name__ == "__main__":
    main()