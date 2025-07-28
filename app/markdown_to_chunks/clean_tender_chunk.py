"""
Скрипт для очистки и дополнительного парсинга метаданных в файле с чанками тендера.

Назначение:
Этот скрипт загружает JSON-файл, предположительно 'tender_chunks.json', который
содержит текстовые чанки, полученные после разделения Markdown-отчета о тендере
(например, с помощью langchain.text_splitter.MarkdownHeaderTextSplitter из Файла 18).

Для каждого чанка скрипт выполняет следующие операции над его метаданными:
1.  Очистка поля "contractor": Удаляет префикс "Подрядчик:" (регистронезависимо),
    если он присутствует.
2.  Разбор поля "position": Если поле содержит строку вида "N. **Название позиции**...",
    извлекает номер ("position_number") и название ("position_title") позиции.
3.  Разбор поля "section": Если поле содержит строку вида "📘 Раздел N: Название...",
    извлекает ID раздела ("section_id") и, если есть, название раздела ("section_title").

Результат (список чанков с обновленными метаданными) сохраняется
в новый JSON-файл 'tender_chunks_cleaned.json'.

Входной файл ('tender_chunks.json') должен представлять собой JSON-массив объектов,
где каждый объект имеет ключи "text" (строка) и "metadata" (словарь).
Ключи "contractor", "position", "section" в словаре "metadata" являются опциональными.

Выходной файл ('tender_chunks_cleaned.json') будет иметь ту же структуру,
но с потенциально измененными или добавленными полями в "metadata".
"""

import re
import json
from typing import List, Dict, Any, Optional

# Имена входного и выходного файлов жестко заданы в скрипте
INPUT_FILENAME = "tender_chunks.json"
OUTPUT_FILENAME = "tender_chunks_cleaned.json"


def clean_and_parse_chunk_metadata(
    chunks_data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Обрабатывает список чанков, очищая и дополняя их метаданные.

    Args:
        chunks_data: Список словарей, где каждый словарь представляет чанк
                     с ключами "text" и "metadata".

    Returns:
        Список словарей с обновленными метаданными.
    """
    processed_chunks: List[Dict[str, Any]] = []

    for chunk in chunks_data:
        # Предполагается, что ключи "text" и "metadata" всегда присутствуют.
        # Создаем копию метаданных, чтобы не изменять исходный объект чанка,
        # если chunks_data используется где-то еще (хотя в данном скрипте это не так).
        # Однако, если чанки большие, это может быть неэффективно.
        # В данном случае, исходный скрипт модифицировал 'meta' на месте и добавлял
        # новый словарь в cleaned_chunks. Это нормально.
        meta = chunk.get("metadata", {}).copy()  # Работаем с копией метаданных
        text_content = chunk.get("text", "")

        # 1. Очистка поля "contractor"
        contractor_val: Optional[str] = meta.get("contractor")
        if contractor_val and isinstance(contractor_val, str):
            # Регистронезависимое удаление префикса "Подрядчик:" и пробелов вокруг
            match_contractor_prefix = re.match(
                r"Подрядчик:\s*(.*)", contractor_val, re.IGNORECASE
            )
            if match_contractor_prefix:
                meta["contractor"] = match_contractor_prefix.group(1).strip()
            # Альтернативно, если всегда "Подрядчик:" с большой буквы, как в вашем replace:
            # if contractor_val.lower().startswith("подрядчик:"):
            #     # Удаляем точную длину префикса "Подрядчик:" (10 символов)
            #     meta["contractor"] = contractor_val[len("Подрядчик:"):].strip()

        # 2. Обработка поля "position"
        position_val: Optional[str] = meta.get("position")
        if position_val and isinstance(position_val, str):
            # Пример строки: '6. **Название позиции** (относится к разделу 2)'
            # Извлекаем номер и название позиции (текст между **)
            match_position = re.match(r"(\d+)\.\s+\*\*(.*?)\*\*", position_val.strip())
            if match_position:
                try:
                    meta["position_number"] = int(match_position.group(1))
                    meta["position_title"] = match_position.group(2).strip()
                except ValueError:
                    # Если номер позиции не удалось преобразовать в int, пропускаем
                    print(
                        f"Warning: Could not parse position_number from '{match_position.group(1)}'"
                    )

        # 3. Обработка поля "section"
        section_val: Optional[str] = meta.get("section")
        if section_val and isinstance(section_val, str):
            # Пример строки: '📘 Раздел 1: Название раздела' или '📘 Раздел 1'
            # Извлекаем ID раздела и, опционально, его название
            match_section = re.match(
                r"📘\s*Раздел\s*(\d+)(?::\s*(.*))?", section_val.strip()
            )
            if match_section:
                try:
                    meta["section_id"] = int(match_section.group(1))
                    # Если есть вторая группа (название раздела после двоеточия)
                    if match_section.group(2) and match_section.group(2).strip():
                        meta["section_title"] = match_section.group(2).strip()
                except ValueError:
                    print(
                        f"Warning: Could not parse section_id from '{match_section.group(1)}'"
                    )

        processed_chunks.append(
            {"text": text_content, "metadata": meta}  # Добавляем обновленные метаданные
        )

    return processed_chunks


def main():
    """
    Главная функция скрипта: загрузка, обработка и сохранение данных чанков.
    """
    print(f"Загрузка данных из {INPUT_FILENAME}...")
    try:
        with open(INPUT_FILENAME, "r", encoding="utf-8") as f:
            chunks_from_file: List[Dict[str, Any]] = json.load(f)
    except FileNotFoundError:
        print(f"Ошибка: Файл '{INPUT_FILENAME}' не найден.")
        return
    except json.JSONDecodeError:
        print(f"Ошибка: Не удалось декодировать JSON из файла '{INPUT_FILENAME}'.")
        return

    print(f"Обработка {len(chunks_from_file)} чанков...")
    cleaned_chunks_data = clean_and_parse_chunk_metadata(chunks_from_file)

    print(
        f"Сохранение {len(cleaned_chunks_data)} обработанных чанков в {OUTPUT_FILENAME}..."
    )
    try:
        with open(OUTPUT_FILENAME, "w", encoding="utf-8") as f:
            json.dump(cleaned_chunks_data, f, ensure_ascii=False, indent=2)
        print("Сохранение успешно завершено.")
    except IOError:
        print(f"Ошибка: Не удалось записать данные в файл '{OUTPUT_FILENAME}'.")


if __name__ == "__main__":
    main()
