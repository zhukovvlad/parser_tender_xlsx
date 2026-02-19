# -*- coding: utf-8 -*-
# app/workers/search_indexer/tasks.py

"""
Celery задачи для Search Indexer Worker.

Архитектура:
------------
- Использует run_async() для безопасного запуска async кода в Celery
- Поддерживает многопроцессную модель Celery (каждый процесс создает свой Worker)
- Ленивая инициализация DB Pool + Embedding Client через worker_ready signal

Задачи:
-------
1. run_search_indexing_task — обработка pending_indexing позиций (по событию / периодическая)
2. reset_stale_indexing_claims — сброс зависших 'indexing' claims

Управление Event Loop:
---------------------
Все async функции оборачиваются через run_async(), который:
- Создает новый event loop если его нет
- Запускает в отдельном потоке если loop уже активен
- Избегает конфликтов с Celery event loop

Инициализация:
-------------
- Import-time: worker_instance = None (без побочных эффектов)
- worker_ready signal: создаёт и инициализирует Worker через run_async()
- Дочерние процессы: создают свой Worker по требованию
"""

import asyncio
import os

from celery import shared_task, signals

from app.utils.async_runner import run_async

from .logger import get_search_indexer_logger
from .worker import SearchIndexerWorker

logger = get_search_indexer_logger("tasks")


def _parse_timeout_env(var_name: str, default: int) -> int:
    """
    Безопасно парсит timeout из переменной окружения.

    Валидирует значение и возвращает default при ошибках.

    Args:
        var_name: Имя переменной окружения
        default: Значение по умолчанию (секунды)

    Returns:
        int: Таймаут в секундах (валидированный положительный int)
    """
    raw_value = os.getenv(var_name, "").strip()

    if not raw_value:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            f"{var_name}={raw_value} не является валидным числом. "
            f"Используется значение по умолчанию: {default}"
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


# Timeout для задачи (в секундах)
INDEXER_TIMEOUT = _parse_timeout_env("SEARCH_INDEXER_TIMEOUT", 1800)  # 30 минут

# ──────────────────────────────────────────────────────────────────────
# Синглтон воркера (ленивая инициализация per-process)
# ──────────────────────────────────────────────────────────────────────

# Не создаём воркер при импорте — избегаем побочных эффектов
# при autodiscovery и тестировании.
worker_instance: SearchIndexerWorker | None = None
worker_instance_pid: int | None = None


async def get_worker_instance_async():
    """
    Получает или создает Search Indexer Worker instance для текущего процесса.

    В многопроцессной модели каждый дочерний процесс должен создать свой экземпляр.

    Returns:
        SearchIndexerWorker | None: Экземпляр воркера или None при фатальной ошибке.
    """
    global worker_instance, worker_instance_pid

    current_pid = os.getpid()

    if (
        worker_instance is None
        or worker_instance_pid != current_pid
        or not worker_instance.is_initialized
    ):
        # Закрываем старый инстанс (унаследованный от родительского процесса)
        if worker_instance is not None:
            try:
                await worker_instance.shutdown()
            except Exception as exc:
                logger.warning(
                    "Не удалось закрыть старый worker instance: %s", exc
                )
            worker_instance = None
            worker_instance_pid = None

        try:
            logger.info(
                "Создаем новый Search Indexer Worker instance для процесса %s...",
                current_pid,
            )
            worker_instance = SearchIndexerWorker()
            worker_instance_pid = current_pid
            await worker_instance.initialize()
            logger.info(
                "Search Indexer Worker успешно инициализирован в процессе %s.",
                current_pid,
            )
            return worker_instance
        except Exception as e:
            logger.critical(
                f"Ошибка инициализации Search Indexer Worker "
                f"в процессе {current_pid}: {e}",
                exc_info=True,
            )
            return None

    return worker_instance


# ──────────────────────────────────────────────────────────────────────
# Signal Handler — инициализация при старте Celery воркера
# ──────────────────────────────────────────────────────────────────────


@signals.worker_ready.connect
def setup_search_indexer(sender, **kwargs):
    """
    Signal handler для инициализации Search Indexer при старте Celery воркера.

    Вызывается автоматически когда воркер готов принимать задачи.
    Инициализирует DB Pool и Embedding Client через run_async().

    Args:
        sender: Celery worker instance (автоматически)
        **kwargs: Дополнительные параметры signal (автоматически)
    """
    logger.info(
        "Сигнал 'worker_ready' получен. "
        "Запуск инициализации Search Indexer Worker..."
    )
    global worker_instance, worker_instance_pid
    try:
        worker_instance = SearchIndexerWorker()
        worker_instance_pid = os.getpid()
        run_async(worker_instance.initialize())
        logger.info("Инициализация Search Indexer Worker завершена успешно.")
    except Exception as e:
        logger.critical(
            f"Критическая ошибка при инициализации Search Indexer "
            f"в 'worker_ready': {e}",
            exc_info=True,
        )
        if worker_instance:
            worker_instance.is_initialized = False


# ──────────────────────────────────────────────────────────────────────
# Celery-задача: Индексация pending_indexing позиций
# ──────────────────────────────────────────────────────────────────────


async def run_search_indexing_task_async():
    """
    Обработка одного батча pending_indexing позиций (асинхронная).
    """
    worker = await get_worker_instance_async()

    if not worker or not worker.is_initialized:
        logger.error(
            "Search Indexer Worker не инициализирован. "
            "Задача индексации пропущена."
        )
        return {"status": "error", "message": "Worker not initialized"}

    logger.info("--- (Search Indexer) Запуск задачи индексации ---")
    try:
        result = await asyncio.wait_for(
            worker.run_indexing(), timeout=INDEXER_TIMEOUT
        )
        logger.info(f"--- (Search Indexer) Задача завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.error(
            "Search Indexer превысил timeout (%ds)", INDEXER_TIMEOUT
        )
        return {
            "status": "error",
            "message": f"Timeout after {INDEXER_TIMEOUT}s",
        }
    except Exception:
        logger.exception("Критическая ошибка в Search Indexer")
        return {"status": "error", "message": "Internal error"}


@shared_task(name="app.workers.search_indexer.tasks.run_search_indexing_task")
def run_search_indexing_task():
    """
    Синхронная Celery задача индексации позиций.

    Запускает run_search_indexing_task_async() через run_async()
    для безопасного выполнения async кода в Celery воркере.

    Returns:
        dict: Результат выполнения задачи:
            - processed: количество обработанных позиций
            - duplicates: количество найденных кандидатов на дубликат
            - skipped: позиции без описания (активированы без эмбеддинга)
    """
    return run_async(run_search_indexing_task_async())


# ──────────────────────────────────────────────────────────────────────
# Celery-задача: Сброс зависших 'indexing' claims
# ──────────────────────────────────────────────────────────────────────


async def reset_stale_indexing_claims_async():
    """Сбрасывает зависшие 'indexing' claims (асинхронная)."""
    worker = await get_worker_instance_async()
    if not worker or not worker.is_initialized:
        logger.error("Worker не инициализирован. Сброс зависших claims пропущен.")
        return {"status": "error", "reset": 0}
    count = await worker.reset_stale_claims()
    return {"status": "ok", "reset": count}


@shared_task(
    name="app.workers.search_indexer.tasks.reset_stale_indexing_claims"
)
def reset_stale_indexing_claims():
    """Сброс зависших 'indexing' записей обратно в 'pending_indexing'."""
    return run_async(reset_stale_indexing_claims_async())
