"""
markdown_utils/positions_report.py

Назначение:
Этот модуль отвечает за генерацию детализированных Markdown-отчетов по
позициям работ для каждого лота в рамках одного тендера.

Основная функциональность:
-   Проходит по всем лотам, извлеченным из основного JSON-объекта тендера.
-   Для каждого лота создает отдельный MD-файл.
-   Имя каждого файла формируется на основе уникальных идентификаторов (ID)
    тендера и лота, полученных из базы данных, что обеспечивает строгую
    связь между файловыми артефактами и записями в системе.
-   Внутри каждого отчета восстанавливает иерархическую структуру разделов
    и подразделов, представляя позиции в удобном для чтения виде.

Основная функция:
- `generate_reports_for_all_lots`: Оркестратор, который принимает полные
  данные тендера и ID, полученные от API, и запускает процесс генерации
  отчетов для всех лотов.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List


def sanitize_filename(name: str) -> str:
    """
    Очищает строку для использования в качестве имени файла.

    Удаляет специфичные для проекта префиксы (например, "Лот №..."),
    запрещенные в именах файлов символы, заменяет пробелы на подчеркивания
    и обрезает строку до 50 символов.

    Примечание: В текущей реализации эта функция является вспомогательной и
    не используется в основном потоке, так как имена файлов генерируются
    на основе числовых ID из базы данных.

    Args:
        name (str): Исходная строка для очистки.

    Returns:
        str: Очищенная и безопасная для использования в качестве имени файла строка.
    """
    name = re.sub(r"Лот №\d+\s*-\s*", "", name)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.replace(" ", "_").strip()[:50]


def create_hierarchical_report(positions_data: dict, output_filename: Path, lot_name: str):
    """
    Создает и записывает в файл иерархический MD-отчет по позициям одного лота.

    Функция принимает "плоский" словарь с позициями, где могут быть вперемешку
    разделы и сами работы, и восстанавливает их вложенную структуру,
    формируя для каждой работы полный иерархический путь (например,
    "Раздел 1 / Подраздел 1.1 / Позиция 1.1.1").

    Args:
        positions_data (dict): Словарь, содержащий данные о позициях и разделах
                               одного конкретного лота.
        output_filename (Path): Полный путь к файлу, в который будет записан отчет.
        lot_name (str): Человекочитаемое название лота для использования в заголовке отчета.

    Side Effects:
        - Создает или перезаписывает файл по пути `output_filename`.
    """
    # Проверяем, существует ли файл (для логирования)
    file_exists = output_filename.exists()
    action = "Обновление" if file_exists else "Создание"
    
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(f"# Детализированный отчет по позициям для лота - {lot_name}\n")
        f.write("---" + "\n\n")

        # ... (остальная логика функции без изменений) ...
        chapter_headers = {
            str(item.get("chapter_number")): item for item in positions_data.values() if item.get("is_chapter")
        }

        for key in sorted(positions_data.keys(), key=int):
            item = positions_data[key]

            if item.get("is_chapter"):
                continue

            path_parts = []

            item_title = item.get("job_title", "")
            item_number = str(item.get("number", ""))
            path_parts.insert(0, f"{item_number}. {item_title}")

            current_ref = str(item.get("chapter_ref"))

            while current_ref and current_ref in chapter_headers:
                parent_chapter = chapter_headers[current_ref]
                parent_title = parent_chapter.get("job_title", "")
                parent_number = str(parent_chapter.get("chapter_number", ""))
                path_parts.insert(0, f"{parent_number}. {parent_title}")
                current_ref = str(parent_chapter.get("chapter_ref"))

            full_hierarchical_title = " / ".join(path_parts)
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


def generate_reports_for_all_lots(
    processed_data: Dict[str, Any],
    output_dir: Path,
    tender_db_id: str,
    lot_ids_map: Dict[str, int],
) -> List[Path]:
    """
    Оркестратор: создает детализированные MD-отчеты для каждого лота.

    Функция итерирует по лотам в предоставленных данных, для каждого из них
    извлекает ID из `lot_ids_map` и формирует уникальное имя файла.
    Затем вызывает `create_hierarchical_report` для генерации содержимого отчета.

    Args:
        processed_data (Dict[str, Any]): Полные данные тендера в виде словаря.
        output_dir (Path): Директория для сохранения сгенерированных отчетов.
        tender_db_id (str): Уникальный ID тендера из базы данных, используется
                              как префикс в имени файла.
        lot_ids_map (Dict[str, int]): Словарь-сопоставление, где ключ - это
                                     ключ лота из JSON (например, "LOT_1"),
                                     а значение - его уникальный ID из БД.

    Returns:
        List[Path]: Список объектов Path, указывающих на все успешно
                    созданные файлы отчетов.
    """
    created_files: List[Path] = []
    lots_data = processed_data.get("lots", {})
    if not lots_data:
        logging.warning("В данных не найдены лоты для создания детализированных отчетов.")
        return created_files

    for lot_key, lot_info in lots_data.items():
        lot_name = lot_info.get("lot_title", lot_key)

        lot_db_id = lot_ids_map.get(lot_key)

        if not lot_db_id:
            logging.warning(f"Не найден ID из БД для лота '{lot_key}'. Пропуск генерации отчета по позициям.")
            continue

        # Предполагаем, что данные подрядчика находятся по этому пути.
        contractor_data = lot_info.get("proposals", {}).get("contractor_1")

        if not (contractor_data and contractor_data.get("contractor_items", {}).get("positions")):
            logging.info(f"Для лота '{lot_name}' не найдены позиции у подрядчика 'contractor_1'. Пропуск.")
            continue

        positions = contractor_data["contractor_items"]["positions"]

        # Имя файла формируется на основе ID из БД для гарантии уникальности.
        # Пример: 3_45_positions.md (где 3 - ID тендера, 45 - ID лота).
        output_filename = output_dir / f"{tender_db_id}_{lot_db_id}_positions.md"

        try:
            create_hierarchical_report(positions, output_filename, lot_name)
            logging.info(f"    -> Детализированный MD-отчет создан/обновлен: {output_filename.name}")
            created_files.append(output_filename)
        except Exception as e:
            logging.error(f"    -> Ошибка при создании отчета для лота '{lot_name}': {e}")

    return created_files
