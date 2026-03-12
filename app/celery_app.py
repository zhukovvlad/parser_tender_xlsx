# app/celery_app.py

"""
Конфигурация Celery для асинхронной обработки задач.
Интегрируется с существующей Redis инфраструктурой.
"""

import logging as _logging
import os
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab  # <-- (ИЗМЕНЕНИЕ 1: Импорт для расписания)
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Создаем Celery приложение
celery_app = Celery(
    "tender_parser",
    broker=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0",
    backend=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0",
    include=[
        "app.workers.gemini.tasks",
        "app.workers.parser.tasks",
        "app.workers.search_indexer.tasks",
        "app.workers.semantic_clusterer.tasks",
        # "app.workers.rag_catalog.tasks",  # <-- (ОТКЛЮЧЕНО: RAG воркер)
    ],
)

# Конфигурация Celery
celery_app.conf.update(
    # Временные зоны
    timezone="UTC",
    enable_utc=True,
    # Настройки задач
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,  # Результаты хранятся 1 час
    # Настройки воркеров
    worker_prefetch_multiplier=1,  # Воркер берет по одной задаче
    task_acks_late=True,  # Подтверждение после выполнения
    worker_disable_rate_limits=False,
    # Retry настройки
    task_default_retry_delay=60,  # Задержка между попытками
    task_max_retries=3,  # Максимальное количество попыток
    # Маршрутизация задач по выделенным очередям
    # (устраняет head-of-line blocking между тяжёлым парсингом,
    #  rate-limited LLM вызовами и быстрым polling-индексером)
    task_routes={
        "app.workers.parser.tasks.*": {"queue": "parser"},
        "app.workers.search_indexer.tasks.*": {"queue": "indexer"},
        "app.workers.semantic_clusterer.tasks.*": {"queue": "clusterer"},
        "app.workers.gemini.tasks.cleanup_old_results": {"queue": "default"},
        "app.workers.gemini.tasks.*": {"queue": "llm"},
        # "app.workers.rag_catalog.tasks.*": {"queue": "default"},  # <-- (ОТКЛЮЧЕНО: Маршрут для RAG)
    },
    # Очередь по умолчанию
    task_default_queue="default",
    task_default_exchange="default",
    task_default_exchange_type="direct",
    task_default_routing_key="default",
    # Мониторинг
    worker_send_task_events=True,
    task_send_sent_event=True,
    # --- RedBeat Configuration (Redis-backed Scheduler) ---
    beat_scheduler="redbeat.RedBeatScheduler",
    beat_max_loop_interval=5,  # Проверять расписание каждые 5 секунд
    redbeat_redis_url=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0",
    redbeat_key_prefix="redbeat:",
)

# --- (ИЗМЕНЕНИЕ 4: Добавлено расписание Celery Beat) ---
# ⚠️ RAG задачи ОТКЛЮЧЕНЫ для экономии Google API
# Раскомментируйте блок ниже когда RAG воркеры понадобятся

# Включить расписание RAG задач (по умолчанию выключено)
ENABLE_RAG_SCHEDULE = os.getenv("ENABLE_RAG_SCHEDULE", "false").lower() == "true"


# Интервалы запуска RAG задач (в минутах для matcher, час для deduplicator).
# NOTE: _parse_int_env, _parse_hour_env, RAG_MATCHER_INTERVAL_MINUTES и RAG_DEDUP_HOUR
# намеренно определены вне блока ENABLE_RAG_SCHEDULE — они понадобятся при
# повторном включении RAG-расписания (см. beat_schedule_config ниже).
def _parse_int_env(key: str, default: int) -> int:
    """Безопасный парсинг целочисленных переменных окружения."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _parse_hour_env(key: str, default: int) -> int:
    """Безопасный парсинг часа (0-23) из переменных окружения."""
    value = _parse_int_env(key, default)
    if 0 <= value <= 23:
        return value
    return default


RAG_MATCHER_INTERVAL_MINUTES = _parse_int_env("RAG_MATCHER_INTERVAL_MINUTES", 360)  # По умолчанию 6 часов
RAG_DEDUP_HOUR = _parse_hour_env("RAG_DEDUP_HOUR", 3)  # По умолчанию 3:00 ночи

beat_schedule_config = {}

if ENABLE_RAG_SCHEDULE:
    # RAG воркеры отключены в include/autodiscover — конфигурация некорректна
    _logging.getLogger(__name__).error(
        "ENABLE_RAG_SCHEDULE=true, но RAG воркеры отключены в include/autodiscover. "
        "Раскомментируйте RAG в include/autodiscover или установите ENABLE_RAG_SCHEDULE=false."
    )
    raise RuntimeError(
        "ENABLE_RAG_SCHEDULE=true, но RAG воркеры отключены в include/autodiscover. "
        "Невозможно зарегистрировать RAG beat-задачи."
    )

# Задача 3: Очистка старых результатов (Gemini) - безопасная, не требует Google API
beat_schedule_config["cleanup-old-results"] = {
    "task": "app.workers.gemini.tasks.cleanup_old_results",
    # Запускать раз в сутки в 2:00 ночи
    "schedule": crontab(minute="0", hour="2"),
    # Явно указываем очередь default, чтобы не занимать AI-воркер
    "options": {"queue": "default"},
}

# Search Indexer: периодический опрос БД для обработки pending_indexing позиций
beat_schedule_config["search-indexer-poll-pending"] = {
    "task": "app.workers.search_indexer.tasks.run_search_indexing_task",
    "schedule": timedelta(seconds=30),
    "options": {"queue": "indexer", "expires": 29},
}

celery_app.conf.beat_schedule = beat_schedule_config
# --- Конец нового блока ---


# Автоматическое обнаружение задач
celery_app.autodiscover_tasks(
    [
        "app.workers.gemini",
        "app.workers.parser",
        "app.workers.search_indexer",
        "app.workers.semantic_clusterer",
        # "app.workers.rag_catalog",  # <-- (ОТКЛЮЧЕНО: RAG воркер)
    ]
)

if __name__ == "__main__":
    celery_app.start()

# Экспортируем app для обратной совместимости
app = celery_app
