# app/celery_app.py

"""
Конфигурация Celery для асинхронной обработки задач.
Интегрируется с существующей Redis инфраструктурой.
"""

import os

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
        "app.workers.rag_catalog.tasks",  # <-- (ИЗМЕНЕНИЕ 2: Добавлен RAG воркер)
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
    # Маршрутизация задач
    task_routes={
        "app.workers.gemini.tasks.*": {"queue": "default"},
        "app.workers.parser.tasks.*": {"queue": "default"},
        "app.workers.rag_catalog.tasks.*": {"queue": "default"},  # <-- (ИЗМЕНЕНИЕ 3: Маршрут для RAG)
    },
    # Очередь по умолчанию
    task_default_queue="default",
    task_default_exchange="default",
    task_default_exchange_type="direct",
    task_default_routing_key="default",
    # Мониторинг
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# --- (ИЗМЕНЕНИЕ 4: Добавлено расписание Celery Beat) ---
celery_app.conf.beat_schedule = {
    # Задача 1: Сопоставление (часто)
    "run-rag-matcher": {
        "task": "app.workers.rag_catalog.tasks.run_matching_task",
        # Запускать каждые 5 минут
        "schedule": crontab(minute="*/5"),
    },
    # Задача 2: Дедупликация (редко, ночная задача)
    "run-rag-deduplicator": {
        "task": "app.workers.rag_catalog.tasks.run_deduplication_task",
        # Запускать раз в сутки в 3:00 ночи
        "schedule": crontab(minute="0", hour="3"),
    },
    # Задача 3: Индексация НЕ в расписании - вызывается event-driven
}
# --- Конец нового блока ---


# Автоматическое обнаружение задач
celery_app.autodiscover_tasks(
    [
        "app.workers.gemini",
        "app.workers.parser",
        "app.workers.rag_catalog",  # <-- (ИЗМЕНЕНИЕ 5: Добавлен RAG воркер)
    ]
)

if __name__ == "__main__":
    celery_app.start()

# Экспортируем app для обратной совместимости
app = celery_app
