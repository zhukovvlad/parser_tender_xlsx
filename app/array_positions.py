import argparse
import json
import re
from pathlib import Path


def sanitize_filename(name: str) -> str:
    """Очищает строку для использования в качестве имени файла."""
    name = re.sub(r"Лот №\d+\s*-\s*", "", name)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.replace(" ", "_").strip()[:50]


def create_hierarchical_report(positions_data: dict, output_filename: str, lot_name: str):
    """
    Создает иерархический MD-отчет, используя флаги is_chapter и chapter_ref.
    """
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(f"# Детализированный отчет по позициям для лота - {lot_name}\n")
        f.write("---" + "\n\n")

        # --- НАЧАЛО ИСПРАВЛЕННОЙ ЛОГИКИ ---

        # 1. Создаем "карту" разделов.
        # Ключ - номер раздела ('chapter_number'), значение - объект этого раздела.
        # Это надежно, так как 'chapter_number' у каждого раздела уникален.
        chapter_headers = {
            str(item.get("chapter_number")): item for item in positions_data.values() if item.get("is_chapter")
        }

        # 2. Итерируемся по позициям и обрабатываем только РАБОЧИЕ ПОЗИЦИИ
        for key in sorted(positions_data.keys(), key=int):
            item = positions_data[key]

            # Пропускаем сами разделы, они будут частью пути
            if item.get("is_chapter"):
                continue

            # Начинаем строить путь для текущей рабочей позиции
            path_parts = []

            # Сначала добавляем саму рабочую позицию
            item_title = item.get("job_title", "")
            item_number = str(item.get("number", ""))
            path_parts.insert(0, f"{item_number}. {item_title}")

            # Теперь движемся вверх по дереву разделов, используя chapter_ref
            current_ref = str(item.get("chapter_ref"))

            while current_ref and current_ref in chapter_headers:
                # Находим родительский раздел по его chapter_number
                parent_chapter = chapter_headers[current_ref]

                parent_title = parent_chapter.get("job_title", "")
                parent_number = str(
                    parent_chapter.get("chapter_number", "")
                )  # Используем chapter_number для заголовков

                # Добавляем родителя в начало пути
                path_parts.insert(0, f"{parent_number}. {parent_title}")

                # Переходим к следующему родителю (дедушке)
                current_ref = str(parent_chapter.get("chapter_ref"))

            # Объединяем все части пути
            full_hierarchical_title = " / ".join(path_parts)

            # Формируем итоговую строку для отчета
            output_parts = [f"**Наименование:** {full_hierarchical_title}"]

            unit = item.get("unit", "нет данных")
            quantity = item.get("quantity", "нет данных")
            comment = item.get("comment_organizer")

            output_parts.append(f"**Единица измерения:** {unit}")
            output_parts.append(f"**Количество:** {quantity}")

            if comment:
                output_parts.append(f"**Комментарий организатора:** {comment}")

            final_line = ". ".join(output_parts)
            f.write(final_line + "\n\n---\n\n")

    print(f"✅ Иерархический отчет успешно создан: {output_filename}")


def main():
    # Эта функция остается без изменений
    parser = argparse.ArgumentParser(description="Анализ файла тендера в формате JSON и создание отчетов по лотам.")
    parser.add_argument("filename", help="Путь к файлу JSON для анализа.")
    args = parser.parse_args()

    input_file = Path(args.filename)
    if not input_file.exists():
        print(f"❌ Ошибка: Файл не найден: {input_file}")
        return

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Произошла ошибка при чтении файла: {e}")
        return

    lots_data = data.get("lots", {})
    if not lots_data:
        print("⚠️ В файле не найдены лоты ('lots').")
        return

    for lot_key, lot_info in lots_data.items():
        print(f"\nОбрабатываю '{lot_key}'...")
        lot_name = lot_info.get("lot_title", lot_key)

        contractor_key_to_process = "contractor_1"
        contractor_data = lot_info.get("proposals", {}).get(contractor_key_to_process)

        if not contractor_data:
            print(f"  - ⚠️ Не найден подрядчик '{contractor_key_to_process}' в лоте '{lot_name}'. Пропускаю.")
            continue

        positions = contractor_data.get("contractor_items", {}).get("positions", {})

        if not positions:
            print(f"  - ⚠️ Не найдено позиций у подрядчика '{contractor_key_to_process}' в лоте '{lot_name}'.")
            continue

        output_filename = f"{input_file.stem}_positions.md"

        create_hierarchical_report(positions, output_filename, lot_name)


if __name__ == "__main__":
    main()
