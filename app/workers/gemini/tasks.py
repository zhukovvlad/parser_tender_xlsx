# app/workers/gemini/tasks.py

"""
Celery задачи для обработки тендерных позиций с помощью Gemini AI.
Интегрируется с существующим GeminiWorker.
"""

import shutil
from pathlib import Path
from typing import Any, Dict

from celery.utils.log import get_task_logger

from ...celery_app import celery_app
from ...gemini_module.constants import (
    FALLBACK_CATEGORY,
    TENDER_CATEGORIES,
    TENDER_CONFIGS,
)
from ...go_module import update_lot_ai_results_sync
from ...json_to_server.ai_results_client import save_ai_results_offline
from .worker import GeminiWorker

# Логгер для Celery задач
logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    queue="ai_queue",  # Направляем в отдельную очередь для AI задач
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 5, "countdown": 60},
    rate_limit="10/m",  # Ограничение: не более 10 задач в минуту на воркер
)
def process_tender_positions(
    self, tender_id: str, lot_id: str, positions_file_path: str, api_key: str
) -> Dict[str, Any]:
    """
    Celery задача для обработки файла позиций лота с помощью Gemini AI.

    Args:
        self: Контекст задачи Celery (bind=True)
        tender_id: ID тендера в базе данных
        lot_id: ID лота в базе данных
        positions_file_path: Путь к файлу _positions.md
        api_key: Google API ключ для Gemini

    Returns:
        Dict с результатами обработки

    Raises:
        Exception: При ошибках обработки (с автоматическим retry)
    """
    task_id = self.request.id
    logger.info(f"🚀 Starting Gemini AI processing for tender {tender_id}, lot {lot_id} (task: {task_id})")

    try:
        # Обновляем статус задачи
        self.update_state(
            state="PROCESSING", meta={"tender_id": tender_id, "lot_id": lot_id, "stage": "initializing", "progress": 0}
        )

        # API ключ передается как параметр
        if not api_key:
            raise ValueError("API key is required but not provided")

        # Проверяем существование файла
        positions_file = Path(positions_file_path)
        if not positions_file.exists():
            raise FileNotFoundError(f"Positions file not found: {positions_file_path}")

        logger.info(f"📁 Processing file: {positions_file_path}")

        # Обновляем прогресс
        self.update_state(
            state="PROCESSING",
            meta={"tender_id": tender_id, "lot_id": lot_id, "stage": "ai_processing", "progress": 25},
        )

        # Создаем воркер и обрабатываем
        worker = GeminiWorker(api_key)

        result = worker.process_positions_file(
            tender_id=tender_id,
            lot_id=lot_id,
            positions_file_path=positions_file_path,
            categories=TENDER_CATEGORIES,
            configs=TENDER_CONFIGS,
            fallback_category=FALLBACK_CATEGORY,
        )

        # Обновляем прогресс
        self.update_state(
            state="PROCESSING", meta={"tender_id": tender_id, "lot_id": lot_id, "stage": "finalizing", "progress": 90}
        )

        # Логируем результат
        if result.get("status") == "success":
            logger.info(f"✅ Successfully processed {tender_id}_{lot_id}. Category: {result.get('category')}")
            logger.info(f"📊 Extracted {len(result.get('ai_data', {}))} fields")
        else:
            logger.warning(f"⚠️ Processing completed with issues: {result.get('error')}")

        # Сохранение результата в БД через Go-сервис (и оффлайн-фолбэк)
        if result.get("status") == "success":
            try:
                update_lot_ai_results_sync(
                    lot_db_id=str(lot_id),
                    tender_id=str(tender_id),  # Передаем tender_id
                    category=result.get("category", ""),
                    ai_data=result.get("ai_data", {}),
                    processed_at=result.get("processed_at", ""),
                )
                logger.info(f"💾 AI результаты успешно отправлены на Go для {tender_id}_{lot_id}")

                # Регенерируем отчеты с AI данными
                try:
                    from app.markdown_utils.regeneration_utils import regenerate_reports_for_lot

                    regenerate_reports_for_lot(
                        tender_id=tender_id,
                        lot_id=lot_id,
                        ai_result=result,
                        logger=logger,
                    )
                except Exception:
                    logger.exception(
                        "⚠️ Ошибка регенерации отчётов для лота %s_%s",
                        tender_id,
                        lot_id,
                    )
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отправить AI результаты на Go для {tender_id}_{lot_id}: {e}")
                # Сохраняем оффлайн при ошибке
                offline_path = save_ai_results_offline(
                    tender_id=tender_id,
                    lot_id=lot_id,
                    category=result.get("category", ""),
                    ai_data=result.get("ai_data", {}),
                    processed_at=result.get("processed_at", ""),
                    reason="request_failed",
                )
                logger.warning(f"📦 AI результаты сохранены оффлайн: {offline_path}")

        # Финальное обновление статуса
        self.update_state(
            state="SUCCESS",
            meta={"tender_id": tender_id, "lot_id": lot_id, "stage": "completed", "progress": 100, "result": result},
        )

        # Архивируем обработанный файл (перемещаем в finalized директорию)
        try:
            _archive_processed_file(positions_file_path)
        except Exception as e:
            logger.warning(f"⚠️ Could not archive file {positions_file_path}: {e}")

        return result

    except Exception as e:
        logger.error(f"❌ Error processing {tender_id}_{lot_id}: {str(e)}")

        # Обновляем статус ошибки
        self.update_state(
            state="FAILURE",
            meta={"tender_id": tender_id, "lot_id": lot_id, "stage": "failed", "error": str(e), "progress": 0},
        )
        raise


def _archive_processed_file(file_path: str):
    """
    Архивирует успешно обработанный файл из pending_sync_positions в tenders_positions.

    Args:
        file_path: Путь к обработанному файлу
    """
    import shutil
    from pathlib import Path

    source_path = Path(file_path)
    if not source_path.exists():
        return

    # Определяем целевую директорию
    if "pending_sync_positions" in str(source_path):
        target_dir = Path("tenders_positions")
        target_dir.mkdir(exist_ok=True)

        target_path = target_dir / source_path.name
        shutil.move(str(source_path), str(target_path))

        logger.info(f"📂 File archived: {source_path.name} -> tenders_positions/")


@celery_app.task(bind=True)
def process_tender_batch(self, tender_id: str, lots_data: list, api_key: str) -> Dict[str, Any]:
    """
    Celery задача для batch обработки всех лотов тендера.

    Args:
        self: Контекст задачи Celery
        tender_id: ID тендера
        lots_data: Список данных лотов с positions_file_path
        api_key: Google API ключ для Gemini

    Returns:
        Dict с результатами обработки всех лотов
    """
    task_id = self.request.id
    logger.info(f"🔄 Starting batch processing for tender {tender_id} with {len(lots_data)} lots (task: {task_id})")

    try:
        self.update_state(
            state="PROCESSING",
            meta={
                "tender_id": tender_id,
                "stage": "batch_processing",
                "total_lots": len(lots_data),
                "processed_lots": 0,
                "progress": 0,
            },
        )

        # Запускаем все подзадачи параллельно (асинхронно)
        subtask_ids = []
        for i, lot_data in enumerate(lots_data):
            lot_id = lot_data.get("lot_id")
            positions_file = lot_data.get("positions_file_path")

            logger.info(f"📝 Starting async processing for lot {i+1}/{len(lots_data)}: {lot_id}")

            # Запускаем подзадачу асинхронно с задержкой (Rate Limiting)
            # Сдвигаем запуск каждой следующей задачи на 4 секунды, чтобы не превысить RPM лимит
            delay_seconds = i * 4
            subtask = process_tender_positions.apply_async(
                args=[tender_id, lot_id, positions_file, api_key], countdown=delay_seconds
            )
            subtask_ids.append(subtask.id)

        # Обновляем прогресс - все задачи отправлены
        self.update_state(
            state="PROCESSING",
            meta={
                "tender_id": tender_id,
                "stage": "tasks_dispatched",
                "total_lots": len(lots_data),
                "dispatched_tasks": len(subtask_ids),
                "subtask_ids": subtask_ids,
                "progress": 50,
            },
        )

        # Собираем результат batch операции
        batch_result = {
            "tender_id": tender_id,
            "total_lots": len(lots_data),
            "dispatched_tasks": len(subtask_ids),
            "subtask_ids": subtask_ids,
            "status": "dispatched",
            "message": f"Запущено {len(subtask_ids)} асинхронных задач для обработки лотов",
        }

        self.update_state(
            state="SUCCESS",
            meta={"tender_id": tender_id, "stage": "completed", "progress": 100, "batch_result": batch_result},
        )

        logger.info(f"✅ Batch processing dispatched for {tender_id}: {len(subtask_ids)} tasks started")
        return batch_result

    except Exception as e:
        logger.error(f"❌ Batch processing error for {tender_id}: {str(e)}")

        self.update_state(
            state="FAILURE", meta={"tender_id": tender_id, "stage": "failed", "error": str(e), "progress": 0}
        )
        raise


@celery_app.task
def cleanup_old_results():
    """
    Периодическая задача для очистки старых результатов и временных файлов.
    Запускается по расписанию.
    """
    logger.info("🧹 Starting cleanup of old results and temporary files")

    try:
        cleanup_stats = {"temp_uploads": 0, "pending_sync_positions": 0, "redis_keys": 0}

        import time
        from pathlib import Path

        current_time = time.time()

        # 1. Очистка temp_uploads (файлы старше 24 часов)
        temp_dir = Path("temp_uploads")
        if temp_dir.exists():
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > 86400:  # 24 часа
                        file_path.unlink()
                        cleanup_stats["temp_uploads"] += 1

        # 2. Архивация обработанных positions файлов (старше 6 часов)
        pending_positions_dir = Path("pending_sync_positions")
        tenders_positions_dir = Path("tenders_positions")
        tenders_positions_dir.mkdir(exist_ok=True)

        if pending_positions_dir.exists():
            for file_path in pending_positions_dir.iterdir():
                if file_path.is_file() and file_path.suffix == ".md":
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > 21600:  # 6 часов
                        # Перемещаем в финальную директорию
                        target_path = tenders_positions_dir / file_path.name
                        shutil.move(str(file_path), str(target_path))
                        cleanup_stats["pending_sync_positions"] += 1
                        logger.info(f"📂 Archived: {file_path.name} -> tenders_positions/")

        # 3. Очистка старых Redis ключей (опционально)
        # Можно добавить очистку ключей задач старше определенного времени

        logger.info(f"✅ Cleanup completed: {cleanup_stats}")
        return cleanup_stats

    except Exception as e:
        logger.error(f"❌ Cleanup error: {str(e)}")
        raise
