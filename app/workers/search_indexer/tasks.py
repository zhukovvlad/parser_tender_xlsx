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

Управление Event Loop:
---------------------
Все async функции оборачиваются через run_async(), который:
- Создает новый event loop если его нет
- Запускает в отдельном потоке если loop уже активен
- Избегает конфликтов с Celery event loop

Инициализация:
-------------
- Главный процесс: создает SearchIndexerWorker без инициализации
- worker_ready signal: инициализирует Worker через run_async()
- Дочерние процессы: создают свой Worker по требованию
"""

import asyncio
import os

from celery import signals

from app.utils.async_runner import run_async

from .logger import get_search_indexer_logger
from .worker import SearchIndexerWorker

logger = get_search_indexer_logger("tasks")


# Ленивый импорт celery_app для избежания круговой зависимости
def get_celery_app():
    """
    Ленивый импорт Celery приложения.

    Избегает циклических зависимостей при импорте модуля.
    Celery app импортируется только когда он действительно нужен.

    Returns:
        Celery: Инстанс Celery приложения
    """
    from app.celery_app import celery_app

    return celery_app


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

try:
    worker_instance = SearchIndexerWorker()
    worker_instance_pid = os.getpid()
    logger.info(
        "Search Indexer Worker-инстанс создан в процессе %s. "
        "DB Pool будет инициализирован по сигналу 'worker_ready'.",
        worker_instance_pid,
    )
except Exception as e:
    logger.critical(
        f"Критическая ошибка: Не удалось создать инстанс Search Indexer Worker: {e}",
        exc_info=True,
    )
    worker_instance = None
    worker_instance_pid = None


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
    if worker_instance:
        try:
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
    else:
        logger.error(
            "Search Indexer Worker-инстанс = None. Инициализация пропущена."
        )


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
        logger.exception(
            f"Search Indexer превысил timeout ({INDEXER_TIMEOUT}s)"
        )
        return {
            "status": "error",
            "message": f"Timeout after {INDEXER_TIMEOUT}s",
        }
    except Exception:
        logger.exception("Критическая ошибка в Search Indexer")
        return {"status": "error", "message": "Internal error"}


def run_search_indexing_task():
    """
    Синхронная обертка для Celery задачи индексации позиций.

    Запускает run_search_indexing_task_async() через run_async()
    для безопасного выполнения async кода в Celery воркере.

    Returns:
        dict: Результат выполнения задачи:
            - processed: количество обработанных позиций
            - duplicates: количество найденных кандидатов на дубликат
    """
    return run_async(run_search_indexing_task_async())


# Регистрируем задачу в Celery
celery_app = get_celery_app()
run_search_indexing_task = celery_app.task(
    name="app.workers.search_indexer.tasks.run_search_indexing_task",
)(run_search_indexing_task)
