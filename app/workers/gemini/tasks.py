# app/workers/gemini/tasks.py

"""
Celery задачи для обработки тендерных позиций с помощью Gemini AI.
Интегрируется с существующим GeminiWorker.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

from celery import current_task
from celery.utils.log import get_task_logger

from ...celery_app import celery_app
from ...gemini_module.constants import TENDER_CATEGORIES, TENDER_CONFIGS, FALLBACK_CATEGORY
from .worker import GeminiWorker

# Логгер для Celery задач
logger = get_task_logger(__name__)


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def process_tender_positions(self, tender_id: str, lot_id: str, positions_file_path: str, api_key: str) -> Dict[str, Any]:
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
            state='PROCESSING',
            meta={
                'tender_id': tender_id,
                'lot_id': lot_id,
                'stage': 'initializing',
                'progress': 0
            }
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
            state='PROCESSING',
            meta={
                'tender_id': tender_id,
                'lot_id': lot_id,
                'stage': 'ai_processing',
                'progress': 25
            }
        )
        
        # Создаем воркер и обрабатываем
        worker = GeminiWorker(api_key)
        
        result = worker.process_positions_file(
            tender_id=tender_id,
            lot_id=lot_id,
            positions_file_path=positions_file_path,
            categories=TENDER_CATEGORIES,
            configs=TENDER_CONFIGS,
            fallback_category=FALLBACK_CATEGORY
        )
        
        # Обновляем прогресс
        self.update_state(
            state='PROCESSING',
            meta={
                'tender_id': tender_id,
                'lot_id': lot_id,
                'stage': 'finalizing',
                'progress': 90
            }
        )
        
        # Логируем результат
        if result.get("status") == "success":
            logger.info(f"✅ Successfully processed {tender_id}_{lot_id}. Category: {result.get('category')}")
            logger.info(f"📊 Extracted {len(result.get('ai_data', {}))} fields")
        else:
            logger.warning(f"⚠️ Processing completed with issues: {result.get('error')}")
        
        # Финальное обновление статуса
        self.update_state(
            state='SUCCESS',
            meta={
                'tender_id': tender_id,
                'lot_id': lot_id,
                'stage': 'completed',
                'progress': 100,
                'result': result
            }
        )
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error processing {tender_id}_{lot_id}: {str(e)}")
        
        # Обновляем статус ошибки
        self.update_state(
            state='FAILURE',
            meta={
                'tender_id': tender_id,
                'lot_id': lot_id,
                'stage': 'failed',
                'error': str(e),
                'progress': 0
            }
        )
        raise


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
            state='PROCESSING',
            meta={
                'tender_id': tender_id,
                'stage': 'batch_processing',
                'total_lots': len(lots_data),
                'processed_lots': 0,
                'progress': 0
            }
        )
        
        results = []
        
        # Запускаем все подзадачи параллельно (асинхронно)
        subtask_ids = []
        for i, lot_data in enumerate(lots_data):
            lot_id = lot_data.get("lot_id")
            positions_file = lot_data.get("positions_file_path")
            
            logger.info(f"📝 Starting async processing for lot {i+1}/{len(lots_data)}: {lot_id}")
            
            # Запускаем подзадачу асинхронно (без ожидания)
            subtask = process_tender_positions.delay(tender_id, lot_id, positions_file, api_key)
            subtask_ids.append(subtask.id)
        
        # Обновляем прогресс - все задачи отправлены
        self.update_state(
            state='PROCESSING',
            meta={
                'tender_id': tender_id,
                'stage': 'tasks_dispatched',
                'total_lots': len(lots_data),
                'dispatched_tasks': len(subtask_ids),
                'subtask_ids': subtask_ids,
                'progress': 50
            }
        )
        
        # Собираем результат batch операции
        batch_result = {
            'tender_id': tender_id,
            'total_lots': len(lots_data),
            'dispatched_tasks': len(subtask_ids),
            'subtask_ids': subtask_ids,
            'status': 'dispatched',
            'message': f'Запущено {len(subtask_ids)} асинхронных задач для обработки лотов'
        }
        
        self.update_state(
            state='SUCCESS',
            meta={
                'tender_id': tender_id,
                'stage': 'completed',
                'progress': 100,
                'batch_result': batch_result
            }
        )
        
        logger.info(f"✅ Batch processing dispatched for {tender_id}: {len(subtask_ids)} tasks started")
        return batch_result
        
    except Exception as e:
        logger.error(f"❌ Batch processing error for {tender_id}: {str(e)}")
        
        self.update_state(
            state='FAILURE',
            meta={
                'tender_id': tender_id,
                'stage': 'failed',
                'error': str(e),
                'progress': 0
            }
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
        # Здесь можно добавить логику очистки:
        # - Удаление старых файлов из temp_uploads
        # - Очистка старых результатов из Redis
        # - Архивирование логов
        
        cleanup_count = 0
        
        # Пример: очистка файлов старше 24 часов
        import time
        from pathlib import Path
        
        temp_dir = Path("temp_uploads")
        if temp_dir.exists():
            current_time = time.time()
            for file_path in temp_dir.iterdir():
                if file_path.is_file():
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > 86400:  # 24 часа
                        file_path.unlink()
                        cleanup_count += 1
        
        logger.info(f"✅ Cleanup completed. Removed {cleanup_count} old files")
        return {"cleaned_files": cleanup_count}
        
    except Exception as e:
        logger.error(f"❌ Cleanup error: {str(e)}")
        raise


# Настройка периодических задач
from celery.schedules import crontab

celery_app.conf.beat_schedule = {
    'cleanup-old-results': {
        'task': 'app.workers.gemini.tasks.cleanup_old_results',
        'schedule': crontab(hour=2, minute=0),  # Каждый день в 2:00
    },
}
celery_app.conf.timezone = 'UTC'
