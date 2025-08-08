# app/celery_app.py

"""
Конфигурация Celery для асинхронной обработки задач.
Интегрируется с существующей Redis инфраструктурой.
"""

import os

from celery import Celery
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Создаем Celery приложение
celery_app = Celery(
    "tender_parser",
    broker=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0",
    backend=f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}/0",
    include=["app.workers.gemini.tasks"],  # Автоимпорт задач
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
    # Маршрутизация задач - все в основную очередь celery
    task_routes={
        "app.workers.gemini.tasks.*": {"queue": "celery"},
        "app.workers.parser.tasks.*": {"queue": "celery"},
    },
    # Мониторинг
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Автоматическое обнаружение задач
celery_app.autodiscover_tasks(["app.workers.gemini", "app.workers.parser"])

if __name__ == "__main__":
    celery_app.start()
