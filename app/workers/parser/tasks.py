"""
Celery-задачи для парсинга тендерных файлов.

Содержит задачу `run_parsing_in_background`, которая выполняет парсинг
загруженного XLSX-файла в фоне, с опциональным AI-анализом. Прогресс
обновляется в Redis под тем же `task_id`, что и у API.

Особенности реализации:
- Единый `task_id` для API и Celery.
- Запись детальных статусов в Redis и продление TTL во время долгих задач.
- При исключениях входной файл не удаляется для возможности повторного запуска (retry).
"""

import json
import os
import time

import redis
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from dotenv import load_dotenv

from app.parse_with_gemini import parse_file_with_gemini

load_dotenv()

logger = get_task_logger(__name__)

STATUS_TTL_SECONDS = int(os.getenv("STATUS_TTL_SECONDS", "7200"))


def _cleanup_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info("Temp file removed: %s", path)
    except OSError as e:
        logger.warning("Temp file remove failed: %s", e)


def make_redis():
    """Создаёт клиент Redis с таймаутами и health-check.

    Предпочитает переменную окружения REDIS_URL; если её нет —
    использует host/port/password.
    """
    url = os.getenv("REDIS_URL")
    if url:
        return redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
            health_check_interval=30,
        )
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
        health_check_interval=30,
    )


redis_client = make_redis()


def _set_status(task_id: str, payload: dict):
    """Сохраняет JSON-статус задачи в Redis под ключом task_status:{task_id} c TTL."""
    key = f"task_status:{task_id}"
    redis_client.set(key, json.dumps(payload), ex=STATUS_TTL_SECONDS)


def _safe_set_status(task_id: str, payload: dict):
    """Пишет статус в Redis, не падая при ошибке соединения."""
    try:
        _set_status(task_id, payload)
    except Exception:
        logger.warning("Task %s: failed to write status to Redis", task_id, exc_info=True)


def _bump_ttl(task_id: str):
    """Продлевает TTL ключа статуса, чтобы он не истёк во время длинной операции."""
    key = f"task_status:{task_id}"
    try:
        redis_client.expire(key, STATUS_TTL_SECONDS)
    except Exception:
        pass


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 5, "countdown": 60},
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=1800,  # мягкий лимит, напр. 30 минут
    time_limit=2100,  # жёсткий лимит — чуть больше
)
def run_parsing_in_background(self, task_id: str, file_path: str, enable_ai: bool = False):
    """Фоновая обработка XLSX-файла с опциональным AI.

    Инварианты:
    - task_id единый для API и Celery (передан в apply_async(task_id=...)).
    - Детальные статусы пишутся в Redis; TTL периодически продлевается.
    - При исключении входной файл не удаляется (нужен для ретраев).
    """
    start = time.time()
    logger.info("Task %s: start file=%s ai=%s", task_id, file_path, enable_ai)

    # получили задачу
    _safe_set_status(task_id, {"status": "processing", "stage": "parsing", "enable_ai": enable_ai})

    try:
        _bump_ttl(task_id)

        # Основная работа: единый парсер/анализ
        ok = parse_file_with_gemini(file_path, enable_ai=enable_ai, async_processing=False)

        if ok:
            _safe_set_status(task_id, {"status": "completed", "stage": "completed", "enable_ai": enable_ai})
            logger.info("Task %s: completed successfully", task_id)
            result = {"task_id": task_id, "status": "completed", "with_ai": enable_ai}
        else:
            _safe_set_status(
                task_id,
                {"status": "completed_with_errors", "stage": "completed_with_errors", "enable_ai": enable_ai},
            )
            logger.warning("Task %s: completed with errors", task_id)
            result = {"task_id": task_id, "status": "completed_with_errors", "with_ai": enable_ai}

        # Удаляем файл только при терминальном завершении без исключения
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info("Task %s: temp file removed: %s", task_id, file_path)
        except OSError as rm_err:
            logger.warning("Task %s: temp file remove failed: %s", task_id, rm_err)

        return result

    except SoftTimeLimitExceeded:
        _safe_set_status(
            task_id,
            {
                "status": "failed",
                "stage": "timeout",
                "error": "soft time limit exceeded",
                "enable_ai": enable_ai,
            },
        )
        _cleanup_file(file_path)
        logger.exception("Task %s: soft time limit exceeded", task_id)
        raise
    except Exception as e:
        will_retry = self.request.retries < self.max_retries
        _safe_set_status(
            task_id,
            {
                "status": "retrying" if will_retry else "failed",
                "stage": "retrying" if will_retry else "failed",
                "error": str(e),
                "enable_ai": enable_ai,
                "retry": self.request.retries,
                "max_retries": self.max_retries,
            },
        )
        if not will_retry:
            _cleanup_file(file_path)
        logger.exception("Task %s: error (retry %s/%s)", task_id, self.request.retries, self.max_retries)
        raise
    finally:
        duration = time.time() - start
        logger.info("Task %s: finished in %.2fs", task_id, duration)
