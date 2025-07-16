# markdown_utils/positions_report.py
import re
from pathlib import Path
from typing import Dict, List

def sanitize_filename(name: str) -> str:
    """Очищает строку для использования в качестве имени файла."""
    name = re.sub(r'Лот №\d+\s*-\s*', '', name)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.replace(" ", "_").strip()[:50]

def create_hierarchical_report(positions_data: dict, output_filename: Path, lot_name: str):
    """Создает иерархический MD-отчет по позициям одного лота."""
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(f"# Детализированный отчет по позициям для лота - {lot_name}\n")
        f.write("---" + "\n\n")

        chapter_headers = {
            str(item.get("chapter_number")): item 
            for item in positions_data.values() 
            if item.get("is_chapter")
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
    processed_data: Dict, 
    output_dir: Path, 
    base_name: str
) -> List[Path]:
    """
    Оркестратор: создает детализированные отчеты для каждого лота в JSON.
    Возвращает список путей к созданным файлам.
    """
    created_files: List[Path] = []
    lots_data = processed_data.get("lots", {})
    if not lots_data:
        print("   -> ⚠️ В данных не найдены лоты для создания детализированных отчетов.")
        return created_files

    for lot_key, lot_info in lots_data.items():
        lot_name = lot_info.get("lot_title", lot_key)
        contractor_data = lot_info.get("proposals", {}).get("contractor_1")
        
        if not (contractor_data and contractor_data.get("contractor_items", {}).get("positions")):
            continue
            
        positions = contractor_data["contractor_items"]["positions"]
        
        # Очищаем ключ лота, оставляя только цифры, на случай если он "Лот 1"
        lot_number = re.sub(r'\D', '', lot_key)
        if not lot_number: # Если номер извлечь не удалось, используем сам ключ
            lot_number = lot_key.replace(" ", "_")

        output_filename = output_dir / f"{base_name}_{lot_number}_positions.md"
        
        try:
            create_hierarchical_report(positions, output_filename, lot_name)
            print(f"   -> Детализированный MD-отчет создан: {output_filename.name}")
            created_files.append(output_filename)
        except Exception as e:
            print(f"   -> ❌ Ошибка при создании отчета для лота '{lot_name}': {e}")
            
    return created_files