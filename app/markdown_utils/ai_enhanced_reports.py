"""
Модуль для генерации MD отчетов с интеграцией AI данных.

Этот модуль создает обогащенные markdown отчеты, которые содержат:
1. Базовые данные из Excel файла (используя json_to_markdown.py)
2. AI данные, вставленные после названия лота, но перед расчетной стоимостью
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from .json_to_markdown import generate_markdown_for_lots

log = logging.getLogger(__name__)


def regenerate_reports_with_ai_data(
    tender_data: Dict[str, Any], ai_results: List[Dict], db_id: str, lot_ids_map: Dict[str, int]
) -> bool:
    """
    Создает MD отчеты с интеграцией AI данных.

    Args:
        tender_data: Базовые данные тендера из Excel
        ai_results: Результаты AI обработки
        db_id: ID тендера в БД
        lot_ids_map: Маппинг лотов к их ID в БД

    Returns:
        True если отчеты успешно созданы
    """
    log.info(f"🔄 Создание MD отчетов с AI данными для тендера {db_id}")

    try:
        # Генерируем MD отчеты с интегрированными AI данными
        lot_markdowns, initial_metadata = generate_markdown_for_lots(
            data=tender_data, ai_results=ai_results, lot_ids_map=lot_ids_map
        )

        # Обрабатываем каждый лот
        success_count = 0
        for lot_key, markdown_lines in lot_markdowns.items():
            real_lot_id = lot_ids_map.get(lot_key)
            if not real_lot_id:
                log.warning(f"⚠️ Не найден реальный ID для лота {lot_key}")
                continue

            # Сохраняем обогащенный MD файл
            if _save_enriched_markdown(markdown_lines, db_id, real_lot_id):
                success_count += 1

                # Создаем chunks файл
                _create_chunks_file(markdown_lines, db_id, real_lot_id, initial_metadata, lot_key)

        log.info(f"✅ MD отчеты с AI данными созданы для тендера {db_id}: {success_count} файлов")
        return success_count > 0

    except Exception as e:
        log.error(f"❌ Ошибка при создании MD отчетов с AI данными: {e}")
        return False


def _save_enriched_markdown(markdown_lines: List[str], tender_id: str, lot_id: int) -> bool:
    """
    Сохраняет обогащенный markdown файл.

    Returns:
        True если файл успешно сохранен
    """
    try:
        output_dir = Path("tenders_md")
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{tender_id}_{lot_id}.md"
        filepath = output_dir / filename

        # Проверяем, существует ли файл (для логирования)
        file_exists = filepath.exists()
        action = "обновлен" if file_exists else "создан"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown_lines))

        log.info(f"📄 Обогащенный MD файл {action}: {filepath}")
        return True

    except Exception as e:
        log.error(f"❌ Ошибка сохранения MD файла для лота {lot_id}: {e}")
        return False


def _create_chunks_file(
    markdown_lines: List[str], tender_id: str, lot_id: int, initial_metadata: Dict[str, Any], lot_key: str
):
    """
    Создает chunks файл из обогащенного markdown.
    Требует установленный langchain-text-splitters для работы.
    """
    try:
        # Ленивый импорт - только когда реально нужно создавать chunks
        from ..markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text
        
        # Объединяем markdown в один текст
        markdown_text = "\n".join(markdown_lines)

        # Подготавливаем метаданные для chunks
        tender_metadata = {
            "tender_id": str(tender_id),
            "lot_id": lot_id,
            "tender_title": initial_metadata.get("tender_title", f"тендер {tender_id}"),
            "executor_name": initial_metadata.get("executor_name", "не указан"),
            "lot_title": f"{lot_key}: данные лота",
        }

        # Создаем chunks
        chunks = create_chunks_from_markdown_text(markdown_text, tender_metadata, lot_id)

        # Сохраняем chunks файл атомарно (через временный файл)
        output_dir = Path("tenders_chunks")
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{tender_id}_{lot_id}_chunks.json"
        filepath = output_dir / filename
        tmp_path = output_dir / (filename + ".tmp")
        
        try:
            # Пишем во временный файл с flush и fsync для долговечности
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(chunks, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # Атомарная замена (предотвращает частичные файлы при сбоях)
            tmp_path.replace(filepath)
        except Exception:
            # Удаляем временный файл при ошибке
            if tmp_path.exists():
                tmp_path.unlink()
            raise

        log.info(f"📦 Создан chunks файл: {filepath}")

    except ImportError as e:
        log.warning(
            f"⚠️ Пропуск создания chunks для лота {lot_id}: langchain-text-splitters не установлен ({e}). "
            "Установите: pip install langchain-text-splitters>=0.3.9"
        )
    except Exception as e:
        log.error(f"❌ Ошибка создания chunks файла для лота {lot_id}: {e}")
