# -*- coding: utf-8 -*-
# app/workers/rag_catalog/tasks.py

import asyncio
import logging
import os

from ...celery_app import app as celery_app
from .logger import get_rag_logger
from .worker import RagWorker

logger = get_rag_logger("tasks")


# Безопасное чтение timeout значений из переменных окружения
def _parse_timeout_env(var_name: str, default: int) -> int:
    """
    Безопасно парсит timeout из environment variable.

    Args:
        var_name: Имя переменной окружения
        default: Значение по умолчанию

    Returns:
        int: Валидное значение timeout
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


# Timeout для задач (в секундах)
MATCHER_TIMEOUT = _parse_timeout_env("RAG_MATCHER_TIMEOUT", 300)  # 5 минут
CLEANER_TIMEOUT = _parse_timeout_env("RAG_CLEANER_TIMEOUT", 600)  # 10 минут

# --- Инициализация воркера ---
try:
    worker_instance = RagWorker()
    logger.info("RAG Worker (Matcher/Cleaner) инициализирован (кэш будет прогрет 'лениво').")

    # asyncio.run(worker_instance.initialize_catalog_cache()) # <-- (ИЗМЕНЕНИЕ: УБРАЛИ БЛОКИРОВКУ)

except Exception as e:
    logger.critical(f"Критическая ошибка: Не удалось инициализировать RAG Worker: {e}", exc_info=True)
    worker_instance = None


# --- ЗАДАЧА 1: Сопоставление (Частая) ---
# NOTE: Использует asyncio.run() для совместимости с существующими sync задачами.
# TODO: Рассмотреть миграцию на native async tasks при переходе всего проекта на async pool.
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
        logger.warning(
            "RAG Matcher пропущен: Кэш каталога еще не инициализирован (ожидаем первый запуск run_cleaning_task)."
        )
        return {"status": "skipped", "message": "Catalog not initialized"}
    # --- Конец проверки ---

    logger.info("--- (RAG) Запуск задачи Matcher (Процесс 2) ---")
    try:
        result = asyncio.run(asyncio.wait_for(worker_instance.run_matcher(), timeout=MATCHER_TIMEOUT))
        logger.info(f"--- (RAG) Задача Matcher завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.exception(f"RAG Matcher превысил timeout ({MATCHER_TIMEOUT}s)")
        return {"status": "error", "message": f"Timeout after {MATCHER_TIMEOUT}s"}
    except Exception:
        logger.exception("Критическая ошибка в RAG Matcher")
        return {"status": "error", "message": "Internal error"}


# --- ЗАДАЧА 2: Очистка (Редкая) ---
# NOTE: Использует asyncio.run() для совместимости с существующими sync задачами.
# TODO: Рассмотреть миграцию на native async tasks при переходе всего проекта на async pool.
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
        result = asyncio.run(
            asyncio.wait_for(worker_instance.run_cleaner(force_reindex=force_reindex), timeout=CLEANER_TIMEOUT)
        )
        logger.info(f"--- (RAG) Задача Cleaner завершена: {result} ---")
        return result
    except asyncio.TimeoutError:
        logger.exception(f"RAG Cleaner превысил timeout ({CLEANER_TIMEOUT}s)")
        return {"status": "error", "message": f"Timeout after {CLEANER_TIMEOUT}s"}
    except Exception:
        logger.exception("Критическая ошибка в RAG Cleaner")
        return {"status": "error", "message": "Internal error"}
