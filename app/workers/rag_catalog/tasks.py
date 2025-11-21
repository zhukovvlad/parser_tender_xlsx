# -*- coding: utf-8 -*-
# app/workers/rag_catalog/tasks.py

import asyncio
import logging
import os

from celery import signals

from .logger import get_rag_logger
from .worker import RagWorker

logger = get_rag_logger("tasks")


# Ленивый импорт celery_app для избежания круговой зависимости
# Импортируем здесь, чтобы он был доступен для декораторов задач
def get_celery_app():
    """Ленивый импорт celery app"""
    from app.celery_app import celery_app

    return celery_app


# --- (Эта функция остается на месте) ---
def _parse_timeout_env(var_name: str, default: int) -> int:
    """
    Безопасно парсит timeout из environment variable.
    """
    raw_value = os.getenv(var_name, "").strip()

    if not raw_value:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            f"{var_name}={raw_value} не является валидным числом. " f"Используется значение по умолчанию: {default}"
        )
        return default
    else:
        if parsed <= 0:
            logger.warning(
                f"{var_name}={raw_value} должен быть положительным числом. "
                f"Используется значение по умолчанию: {default}"
            )
            return default
        return parsed


# --- Конец функции ---

# Timeout для задач (в секундах)
MATCHER_TIMEOUT = _parse_timeout_env("RAG_MATCHER_TIMEOUT", 600)  # 10 минут
INDEXER_TIMEOUT = _parse_timeout_env("RAG_INDEXER_TIMEOUT", 1800)  # 30 минут
DEDUPLICATOR_TIMEOUT = _parse_timeout_env("RAG_DEDUPLICATOR_TIMEOUT", 3600)  # 60 минут

# --- (ИЗМЕНЕНИЕ 1) ---
# Просто инициализируем. БЕЗ `asyncio.run()`.
try:
    worker_instance = RagWorker()
    worker_instance_pid = os.getpid()  # Запоминаем PID главного процесса
    logger.info(
        "RAG Worker-инстанс создан в процессе %s. "
        "File Search Store будет инициализирован по сигналу 'worker_ready'.",
        worker_instance_pid,
    )
except Exception as e:
    logger.critical(f"Критическая ошибка: Не удалось создать инстанс RAG Worker: {e}", exc_info=True)
    worker_instance = None
    worker_instance_pid = None


# Функция для получения/создания worker instance (ленивая инициализация для дочерних процессов)
async def get_worker_instance_async():
    """
    Получает или создает RAG Worker instance для текущего процесса (асинхронная версия).
    В многопроцессной модели каждый дочерний процесс должен создать свой экземпляр.

    Returns:
        RagWorker | None: Экземпляр воркера или None в случае фатальной ошибки инициализации.
    """
    global worker_instance, worker_instance_pid

    current_pid = os.getpid()

    # Проверяем, нужно ли создать новый экземпляр для дочернего процесса
    if worker_instance is None or worker_instance_pid != current_pid or not worker_instance.is_catalog_initialized:
        # Создаем новый экземпляр для дочернего процесса
        try:
            logger.info("Создаем новый RAG Worker instance для процесса %s...", current_pid)
            worker_instance = RagWorker()
            worker_instance_pid = current_pid
            # Асинхронно инициализируем store (БЕЗ asyncio.run!)
            await worker_instance.initialize_store()
            logger.info("RAG Worker успешно инициализирован в процессе %s.", current_pid)
            return worker_instance
        except Exception as e:
            logger.critical(f"Ошибка инициализации RAG Worker в процессе {current_pid}: {e}", exc_info=True)
            return None

    return worker_instance


# --- (ИЗМЕНЕНИЕ 2) ---
# Создаем "startup" Signal Handler через worker_ready вместо on_after_configure
@signals.worker_ready.connect
def setup_rag_store(sender, **kwargs):
    """
    Вызывается при старте воркера (когда воркер готов принимать задачи).
    Инициализирует File Search Store и запускает первый matcher.
    """
    logger.info("Сигнал 'worker_ready' получен. Запуск инициализации File Search Store...")
    if worker_instance:
        try:
            # Используем asyncio.run() ЗДЕСЬ.
            asyncio.run(worker_instance.initialize_store())
            logger.info("Инициализация File Search Store завершена успешно.")

            # Запускаем первый matcher сразу после инициализации
            # logger.info("Запускаем первый matcher сразу после старта воркера...")
            # celery_app = get_celery_app()
            # celery_app.send_task('app.workers.rag_catalog.tasks.run_matching_task')
            # logger.info("Первый matcher отправлен в очередь.")

        except Exception as e:
            logger.critical(
                f"Критическая ошибка при инициализации Store в 'worker_ready': {e}",
                exc_info=True,
            )
            # (Важно) Помечаем воркер как неинициализированный
            if worker_instance:
                worker_instance.is_catalog_initialized = False
    else:
        logger.error("RAG Worker-инстанс = None. Инициализация Store пропущена.")


# --- ЗАДАЧА 1: Сопоставление (Частая) ---
async def run_matching_task_async():
    """
    (Процесс 2) Периодическая задача для сопоставления 'NULL' position_items (асинхронная).
    """
    worker = await get_worker_instance_async()

    if not worker or not worker.is_catalog_initialized:
        logger.error("RAG Worker не инициализирован (Store не готов). Задача сопоставления пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    logger.info("--- (RAG) Запуск задачи Matcher (Процесс 2) ---")
    try:
        result = await asyncio.wait_for(worker.run_matcher(), timeout=MATCHER_TIMEOUT)
        logger.info(f"--- (RAG) Задача Matcher завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.exception(f"RAG Matcher превысил timeout ({MATCHER_TIMEOUT}s)")
        return {"status": "error", "message": f"Timeout after {MATCHER_TIMEOUT}s"}
    except Exception:
        logger.exception("Критическая ошибка в RAG Matcher")
        return {"status": "error", "message": "Internal error"}


def run_matching_task():
    """Синхронная обертка для асинхронной задачи"""
    return asyncio.run(run_matching_task_async())


# --- ЗАДАЧА 2: Индексация (Event-Driven) ---
async def run_indexing_task_async():
    """
    (Процесс 3А) Запускается по событию для индексации 'pending' позиций.
    """
    worker = await get_worker_instance_async()

    if not worker or not worker.is_catalog_initialized:
        logger.error("RAG Worker не инициализирован (Store не готов). Задача индексации пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    logger.info("--- (RAG) Запуск задачи Indexer (Процесс 3А) ---")
    try:
        result = await asyncio.wait_for(worker.run_indexer(), timeout=INDEXER_TIMEOUT)
        logger.info(f"--- (RAG) Задача Indexer завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.exception(f"RAG Indexer превысил timeout ({INDEXER_TIMEOUT}s)")
        return {"status": "error", "message": f"Timeout after {INDEXER_TIMEOUT}s"}
    except Exception:
        logger.exception("Критическая ошибка в RAG Indexer")
        return {"status": "error", "message": "Internal error"}


def run_indexing_task():
    """Синхронная обертка для асинхронной задачи индексации"""
    return asyncio.run(run_indexing_task_async())


# --- ЗАДАЧА 3: Дедупликация (По расписанию) ---
async def run_deduplication_task_async():
    """
    (Процесс 3Б) Запускается по расписанию для дедупликации 'active' позиций.
    """
    worker = await get_worker_instance_async()

    if not worker or not worker.is_catalog_initialized:
        logger.error("RAG Worker не инициализирован (Store не готов). Задача дедупликации пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    logger.info("--- (RAG) Запуск задачи Deduplicator (Процесс 3Б) ---")

    try:
        result = await asyncio.wait_for(worker.run_deduplicator(), timeout=DEDUPLICATOR_TIMEOUT)
        logger.info(f"--- (RAG) Задача Deduplicator завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.exception(f"RAG Deduplicator превысил timeout ({DEDUPLICATOR_TIMEOUT}s)")
        return {"status": "error", "message": f"Timeout after {DEDUPLICATOR_TIMEOUT}s"}
    except Exception:
        logger.exception("Критическая ошибка в RAG Deduplicator")
        return {"status": "error", "message": "Internal error"}


def run_deduplication_task():
    """Синхронная обертка для асинхронной задачи дедупликации"""
    return asyncio.run(run_deduplication_task_async())


# Регистрируем задачи в Celery
celery_app = get_celery_app()
run_matching_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_matching_task")(run_matching_task)
run_indexing_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_indexing_task")(run_indexing_task)
run_deduplication_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_deduplication_task")(
    run_deduplication_task
)
