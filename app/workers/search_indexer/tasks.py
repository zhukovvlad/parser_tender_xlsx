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


def _parse_int_env(var_name: str, default: int) -> int:
    """
    Безопасно парсит целочисленную переменную окружения.

    Валидирует значение (положительное целое) и возвращает default
    при отсутствии, пустом значении, невалидном формате или <= 0.

    Используется для портов, таймаутов и других числовых настроек.

    Args:
        var_name: Имя переменной окружения
        default: Значение по умолчанию

    Returns:
        int: Валидированное положительное целое число
    """
    raw_value = os.getenv(var_name, "").strip()

    if not raw_value:
        return default

    try:
        parsed = int(raw_value)
    except ValueError:
        logger.warning(
            "%s=%s не является валидным числом. " "Используется значение по умолчанию: %d",
            var_name,
            raw_value,
            default,
        )
        return default
    else:
        if parsed <= 0:
            logger.warning(
                "%s=%s должен быть положительным числом. " "Используется значение по умолчанию: %d",
                var_name,
                raw_value,
                default,
            )
            return default
        return parsed


# Redis URL для распределённой блокировки
_REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
_REDIS_PORT = _parse_int_env("REDIS_PORT", 6379)

# Ключ для Redis-lock (не допускает параллельных задач индексации)
_INDEXER_LOCK_KEY = "search_indexer:run_lock"


# Timeout для задачи (в секундах)
INDEXER_TIMEOUT = _parse_int_env("SEARCH_INDEXER_TIMEOUT", 1800)  # 30 минут

# TTL для Redis-lock: task timeout + запас 120 с на graceful shutdown/cleanup.
# Если TTL == timeout, lock может истечь до finally-блока при медленном завершении.
_INDEXER_LOCK_TTL = INDEXER_TIMEOUT + 120

# ──────────────────────────────────────────────────────────────────────
# Синглтон воркера (ленивая инициализация per-process)
# ──────────────────────────────────────────────────────────────────────

# Не создаём воркер при импорте — избегаем побочных эффектов
# при autodiscovery и тестировании.
worker_instance: SearchIndexerWorker | None = None
worker_instance_pid: int | None = None

# Lock для защиты от одновременной инициализации из нескольких корутин.
# NB: asyncio.Lock достаточен, т.к. Celery в production использует prefork
# (один поток на процесс). При переходе на gevent/eventlet потребуется
# thread-safe примитив.
_worker_init_lock = asyncio.Lock()


async def get_worker_instance_async():
    """
    Получает или создает Search Indexer Worker instance для текущего процесса.

    Использует double-checked locking: быстрая проверка без блокировки,
    затем повторная проверка под asyncio.Lock для защиты от гонок.

    В многопроцессной модели каждый дочерний процесс должен создать свой экземпляр.

    Returns:
        SearchIndexerWorker | None: Экземпляр воркера или None при фатальной ошибке.
    """
    global worker_instance, worker_instance_pid

    current_pid = os.getpid()

    # Fast path: worker already initialized for this process
    if worker_instance is not None and worker_instance_pid == current_pid and worker_instance.is_initialized:
        return worker_instance

    # Slow path: acquire lock, re-check, then initialize
    async with _worker_init_lock:
        # Re-check after acquiring lock (another coroutine may have initialized)
        if worker_instance is not None and worker_instance_pid == current_pid and worker_instance.is_initialized:
            return worker_instance

        # Закрываем старый инстанс (унаследованный от родительского процесса)
        if worker_instance is not None:
            try:
                await worker_instance.shutdown()
            except Exception as exc:
                logger.warning("Не удалось закрыть старый worker instance: %s", exc)
            worker_instance = None
            worker_instance_pid = None

        new_worker = None
        try:
            logger.info(
                "Создаем новый Search Indexer Worker instance для процесса %s...",
                current_pid,
            )
            new_worker = SearchIndexerWorker()
            await new_worker.initialize()
            # Присваиваем глобальным переменным только после успешной инициализации
            worker_instance = new_worker
            worker_instance_pid = current_pid
            logger.info(
                "Search Indexer Worker успешно инициализирован в процессе %s.",
                current_pid,
            )
            return worker_instance
        except Exception as e:
            # Закрываем частично инициализированный воркер (напр. pool создан,
            # но EmbeddingClient упал)
            if new_worker is not None:
                try:
                    await new_worker.shutdown()
                except Exception as shutdown_exc:
                    logger.warning(
                        "Не удалось закрыть частично инициализированный " "worker: %s",
                        shutdown_exc,
                    )
            logger.critical(
                f"Ошибка инициализации Search Indexer Worker " f"в процессе {current_pid}: {e}",
                exc_info=True,
            )
            return None


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
    logger.info("Сигнал 'worker_ready' получен. " "Запуск инициализации Search Indexer Worker...")
    global worker_instance, worker_instance_pid
    worker_instance = None
    worker_instance_pid = None
    try:
        worker_instance = SearchIndexerWorker()
        worker_instance_pid = os.getpid()
        run_async(worker_instance.initialize())
        logger.info("Инициализация Search Indexer Worker завершена успешно.")
    except Exception as e:
        logger.critical(
            f"Критическая ошибка при инициализации Search Indexer " f"в 'worker_ready': {e}",
            exc_info=True,
        )
        if worker_instance is not None:
            try:
                run_async(worker_instance.shutdown())
            except Exception as shutdown_exc:
                logger.warning(
                    "Не удалось закрыть частично инициализированный " "worker в 'worker_ready': %s",
                    shutdown_exc,
                )
            worker_instance = None
            worker_instance_pid = None


# ──────────────────────────────────────────────────────────────────────
# Celery-задача: Индексация pending_indexing позиций
# ──────────────────────────────────────────────────────────────────────


async def run_search_indexing_task_async():
    """
    Обработка одного батча pending_indexing позиций (асинхронная).
    """
    worker = await get_worker_instance_async()

    if not worker or not worker.is_initialized:
        logger.error("Search Indexer Worker не инициализирован. " "Задача индексации пропущена.")
        return {"status": "error", "message": "Worker not initialized"}

    logger.info("--- (Search Indexer) Запуск задачи индексации ---")
    try:
        result = await asyncio.wait_for(worker.run_indexing(), timeout=INDEXER_TIMEOUT)
        logger.info(f"--- (Search Indexer) Задача завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.error("Search Indexer превысил timeout (%ds)", INDEXER_TIMEOUT)
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

    Использует Redis SET NX для distributed lock —
    гарантирует, что одновременно работает только один экземпляр задачи.
    Это предотвращает race condition, когда два воркера обрабатывают
    одни и те же pending_indexing строки.

    Запускает run_search_indexing_task_async() через run_async()
    для безопасного выполнения async кода в Celery воркере.

    Returns:
        dict: Результат выполнения задачи:
            - processed: количество обработанных позиций
            - duplicates: количество найденных кандидатов на дубликат
            - skipped: позиции без описания (активированы без эмбеддинга)
    """
    import redis

    r = redis.Redis(
        host=_REDIS_HOST,
        port=_REDIS_PORT,
        db=0,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    lock = r.lock(
        _INDEXER_LOCK_KEY,
        timeout=_INDEXER_LOCK_TTL,
    )
    acquired = lock.acquire(blocking=False)  # не ждём — сразу отказ если занят
    if not acquired:
        logger.info("Задача индексации пропущена: другой экземпляр уже работает.")
        return {
            "status": "skipped",
            "message": "Another instance is running",
            "processed": 0,
            "duplicates": 0,
            "skipped": 0,
        }

    try:
        return run_async(
            run_search_indexing_task_async(),
            timeout=_INDEXER_LOCK_TTL,
        )
    finally:
        try:
            lock.release()
        except redis.exceptions.LockNotOwnedError:
            logger.warning(
                "Redis-lock уже истёк (TTL=%d с) до завершения задачи",
                _INDEXER_LOCK_TTL,
            )
        except Exception:
            logger.warning("Не удалось освободить Redis-lock", exc_info=True)
