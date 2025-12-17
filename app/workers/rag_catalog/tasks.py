# -*- coding: utf-8 -*-
# app/workers/rag_catalog/tasks.py

"""
Celery задачи для RAG Worker (Процессы 2 и 3).

Архитектура:
------------
- Использует run_async() для безопасного запуска async кода в Celery
- Поддерживает многопроцессную модель Celery (каждый процесс создает свой RagWorker)
- Ленивая инициализация File Search Store через worker_ready signal

Задачи:
-------
1. run_matching_task - Сопоставление позиций с каталогом (каждые 10 минут)
2. run_indexing_task - Индексация новых позиций в RAG (по событию)
3. run_deduplication_task - Поиск дубликатов в каталоге (ночная задача)

Управление Event Loop:
---------------------
Все async функции оборачиваются через run_async(), который:
- Создает новый event loop если его нет
- Запускает в отдельном потоке если loop уже активен
- Избегает конфликтов с Celery event loop

Инициализация:
-------------
- Главный процесс: создает RagWorker без инициализации Store
- worker_ready signal: инициализирует Store через run_async()
- Дочерние процессы: создают свой RagWorker и Store по требованию
"""

import asyncio
import os

from celery import signals

from app.utils.async_runner import run_async

from .logger import get_rag_logger
from .worker import RagWorker

logger = get_rag_logger("tasks")


# Ленивый импорт celery_app для избежания круговой зависимости
# Импортируем здесь, чтобы он был доступен для декораторов задач
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


# --- (Эта функция остается на месте) ---
def _parse_timeout_env(var_name: str, default: int) -> int:
    """
    Безопасно парсит timeout из переменной окружения.
    
    Валидирует значение и возвращает default при ошибках.
    
    Args:
        var_name: Имя переменной окружения
        default: Значение по умолчанию (секунды)
        
    Returns:
        int: Таймаут в секундах (валидированный положительный int)
        
    Note:
        Логирует предупреждения при невалидных значениях.
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
# Создаем RagWorker в главном процессе БЕЗ инициализации Store.
# Store будет инициализирован позже через run_async() в worker_ready signal.
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
            # Асинхронно инициализируем store через await (НЕ через run_async - мы уже внутри async!)
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
    Signal handler для инициализации RAG Store при старте Celery воркера.
    
    Вызывается автоматически когда воркер готов принимать задачи.
    Инициализирует Google File Search Store через run_async() для безопасного
    запуска async кода в Celery контексте.
    
    Args:
        sender: Celery worker instance (автоматически)
        **kwargs: Дополнительные параметры signal (автоматически)
        
    Note:
        - Запускается ОДИН раз при старте главного процесса воркера
        - Дочерние процессы создают свои Store в get_worker_instance_async()
        - При ошибке помечает worker как неинициализированный
    """
    logger.info("Сигнал 'worker_ready' получен. Запуск инициализации File Search Store...")
    if worker_instance:
        try:
            # Используем run_async() для безопасного запуска async кода в Celery контексте.
            run_async(worker_instance.initialize_store())
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
    """
    Синхронная обертка для Celery задачи сопоставления позиций.
    
    Запускает run_matching_task_async() через run_async() для безопасного
    выполнения async кода в Celery воркере.
    
    Returns:
        dict: Результат выполнения задачи:
            - status: "success" | "error"
            - matched_count: количество сопоставленных позиций
            - message: описание ошибки (если есть)
            
    Note:
        Зарегистрирована в Celery как периодическая задача (каждые 10 минут).
    """
    return run_async(run_matching_task_async())


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
    """
    Синхронная обертка для Celery задачи индексации позиций.
    
    Запускается по событию (через .delay()) когда появляются новые позиции
    после импорта тендера. Использует run_async() для выполнения async кода.
    
    Returns:
        dict: Результат выполнения задачи:
            - status: "success" | "error"
            - indexed_count: количество проиндексированных записей
            - message: описание ошибки (если есть)
            
    Note:
        Триггерится автоматически из import_tender_sync() при новых позициях.
    """
    return run_async(run_indexing_task_async())


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
    """
    Синхронная обертка для Celery задачи дедупликации каталога.
    
    Запускается по расписанию (раз в сутки в 3:00 ночи) для поиска
    семантических дубликатов в активном каталоге.
    
    Returns:
        dict: Результат выполнения задачи:
            - status: "success" | "error"
            - duplicates_found: количество найденных дубликатов
            - suggestions_created: количество созданных предложений слияния
            - message: описание ошибки (если есть)
            
    Note:
        Использует run_async() для выполнения долгой async операции.
    """
    return run_async(run_deduplication_task_async())


# Регистрируем задачи в Celery
celery_app = get_celery_app()
run_matching_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_matching_task")(run_matching_task)
run_indexing_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_indexing_task")(run_indexing_task)
run_deduplication_task = celery_app.task(name="app.workers.rag_catalog.tasks.run_deduplication_task")(
    run_deduplication_task
)
