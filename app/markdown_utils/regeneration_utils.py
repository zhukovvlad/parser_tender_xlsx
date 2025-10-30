"""
Модуль для регенерации отчетов (MD и chunks) с AI данными.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from app.markdown_utils.ai_enhanced_reports import regenerate_reports_with_ai_data


def regenerate_reports_for_lot(
    tender_id: str,
    lot_id: str,
    ai_result: Dict[str, Any],
    logger: logging.Logger,
):
    """
    Регенерирует обогащённые MD и chunks файлы для одного лота.
    
    Эта функция является универсальным "помощником", который:
    1. Загружает полные данные тендера из временного хранилища (temp_tender_data/)
    2. Интегрирует результаты обработки лота (AI данные или заглушку)
    3. Вызывает основной "движок" regenerate_reports_with_ai_data для создания финальных файлов
    
    Используется как для AI-результатов, так и для заглушек (режим без AI).

    Args:
        tender_id: ID тендера в базе данных
        lot_id: ID лота в базе данных (строка)
        ai_result: Результаты обработки лота, содержащие:
            - category: категория тендера ("Test mode" для заглушек)
            - ai_data: извлеченные данные (или {"message": "No data. Test mode"} для заглушек)
            - processed_at: время обработки
            - status: статус обработки ("success" для AI, "stub" для заглушек)
        logger: Экземпляр логгера для вывода сообщений
        
    Note:
        Требует наличия файла temp_tender_data/{tender_id}.json с полными данными тендера.
        Создает/обновляет файлы:
        - tenders_md/{tender_id}_{lot_id}.md (обогащенный markdown)
        - tenders_chunks/{tender_id}_{lot_id}_chunks.json (для векторного поиска)
    """
    # Ищем сохраненные данные тендера
    tender_data_path = Path("temp_tender_data") / f"{tender_id}.json"

    if not tender_data_path.exists():
        logger.warning(f"⚠️ Не найдены сохраненные данные тендера: {tender_data_path}")
        logger.info("ℹ️ Отчеты tenders_md/ и tenders_chunks/ не будут обновлены автоматически")
        return

    try:
        # Читаем сохраненные данные тендера
        with open(tender_data_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        tender_data = saved_data.get("tender_data")
        lot_ids_map = saved_data.get("lot_ids_map")

        if not tender_data or not lot_ids_map:
            logger.error(f"❌ Некорректный формат данных в {tender_data_path}")
            return

        # Формируем список AI результатов для функции регенерации
        ai_results_list = [
            {
                "lot_id": int(lot_id),
                "category": ai_result.get("category", ""),
                "ai_data": ai_result.get("ai_data", {}),
                "processed_at": ai_result.get("processed_at", ""),
                "status": "success",
            }
        ]

        # Регенерируем отчеты
        success = regenerate_reports_with_ai_data(
            tender_data=tender_data,
            ai_results=ai_results_list,
            db_id=str(tender_id),
            lot_ids_map=lot_ids_map,
        )

        if success:
            logger.info(f"✅ Отчеты tenders_md/ и tenders_chunks/ регенерированы для {tender_id}_{lot_id}")
        else:
            logger.warning(f"⚠️ Ошибка при регенерации отчетов для {tender_id}_{lot_id}")

    except Exception as e:
        logger.error(f"❌ Ошибка регенерации отчетов для {tender_id}_{lot_id}: {e}", exc_info=True)
