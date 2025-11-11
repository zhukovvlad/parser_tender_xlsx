# app/workers/rag_catalog/tasks.py

import asyncio
from ...celery_app import app as celery_app
from .logger import get_rag_logger
from .worker import RagWorker

logger = get_rag_logger("tasks")

# --- Инициализация воркера ---
try:
    worker_instance = RagWorker()
    logger.info("RAG Worker (Matcher/Cleaner) инициализирован (кэш будет прогрет 'лениво').")
    
    # asyncio.run(worker_instance.initialize_catalog_cache()) # <-- (ИЗМЕНЕНИЕ: УБРАЛИ БЛОКИРОВКУ)
    
except Exception as e:
    logger.critical(f"Критическая ошибка: Не удалось инициализировать RAG Worker: {e}", exc_info=True)
    worker_instance = None

# --- ЗАДАЧА 1: Сопоставление (Частая) ---
@celery_app.task(name="app.workers.rag_catalog.tasks.run_matching_task")
def run_matching_task():
    """
    (Процесс 2) Периодическая задача для сопоставления 'NULL' position_items.
    """
    if not worker_instance:
        logger.error("RAG Worker не инициализирован, задача сопоставления пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    # --- (ИЗМЕНЕНИЕ: Ленивая проверка) ---
    if not worker_instance.is_catalog_initialized:
        logger.warning("RAG Matcher пропущен: Кэш каталога еще не инициализирован (ожидаем первый запуск run_cleaning_task).")
        return {"status": "skipped", "message": "Catalog not initialized"}
    # --- Конец проверки ---

    logger.info("--- (RAG) Запуск задачи Matcher (Процесс 2) ---")
    try:
        result = asyncio.run(worker_instance.run_matcher())
        logger.info(f"--- (RAG) Задача Matcher завершена: {result} ---")
        return result
    except Exception as e:
        logger.exception(f"Критическая ошибка в RAG Matcher: {e}")
        return {"status": "error", "message": str(e)}

# --- ЗАДАЧА 2: Очистка (Редкая) ---
@celery_app.task(name="app.workers.rag_catalog.tasks.run_cleaning_task")
def run_cleaning_task(force_reindex: bool = False):
    """
    (Процесс 3) Периодическая задача для очистки и дедупликации каталога.
    Также отвечает за ПЕРВУЮ инициализацию кэша.
    """
    if not worker_instance:
        logger.error("RAG Worker не инициализирован, задача очистки пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    logger.info(f"--- (RAG) Запуск задачи Cleaner (Процесс 3). Force Re-index: {force_reindex} ---")

    # --- (ИЗМЕНЕНИЕ: Логика инициализации) ---
    # Если кэш еще не готов, эта (ночная) задача
    # принудительно его инициализирует.
    if not worker_instance.is_catalog_initialized:
        logger.info("Первый запуск: принудительная инициализация кэша каталога.")
        force_reindex = True
    # --- Конец ---
        
    try:
        result = asyncio.run(worker_instance.run_cleaner(force_reindex=force_reindex))
        logger.info(f"--- (RAG) Задача Cleaner завершена: {result} ---")
        return result
    except Exception as e:
        logger.exception(f"Критическая ошибка в RAG Cleaner: {e}")
        return {"status": "error", "message": str(e)}