# -*- coding: utf-8 -*-
# app/workers/semantic_clusterer/tasks.py
"""
Celery-задача для семантической кластеризации catalog_positions.

Архитектура:
- Единый task_id для API и Celery (прокидывается через apply_async).
- Детальные статусы пишутся в Redis под ключом task_status:{task_id}.
- Асинхронная бизнес-логика (asyncpg, Gemini) запускается через run_async().
- ML-вычисления (UMAP, HDBSCAN) изолируются в потоке через asyncio.to_thread.
"""

import json
import os
import time

import redis
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from dotenv import load_dotenv

from app.utils.async_runner import run_async

from .logger import get_semantic_clusterer_logger
from .worker import SemanticClustererWorker

load_dotenv()

logger = get_semantic_clusterer_logger("semantic_clusterer.tasks")

STATUS_TTL_SECONDS = int(os.getenv("STATUS_TTL_SECONDS", "7200"))

# Ключ для Redis-lock (не допускает параллельных задач кластеризации)
_CLUSTERER_LOCK_KEY = "semantic_clusterer:run_lock"
# TTL для Redis-lock: soft_time_limit + запас 120с на graceful shutdown/cleanup
_CLUSTERER_LOCK_TTL = 3600 + 120


# ──────────────────────────────────────────────────────────────────────
# Redis helpers (из parser/tasks.py)
# ──────────────────────────────────────────────────────────────────────


def make_redis():
    """Создаёт клиент Redis с таймаутами и health-check."""
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


def _safe_set_status(task_id: str, payload: dict):
    """Пишет JSON-статус в Redis, не падая при ошибке соединения."""
    key = f"task_status:{task_id}"
    try:
        redis_client.set(key, json.dumps(payload), ex=STATUS_TTL_SECONDS)
    except Exception:
        logger.warning("Task %s: failed to write status to Redis", task_id, exc_info=True)


def _bump_ttl(task_id: str):
    """Продлевает TTL ключа статуса для длительных операций."""
    key = f"task_status:{task_id}"
    try:
        redis_client.expire(key, STATUS_TTL_SECONDS)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# Celery-задача
# ──────────────────────────────────────────────────────────────────────


@shared_task(
    bind=True,
    name="app.workers.semantic_clusterer.tasks.run_semantic_clustering",
    max_retries=3,
    soft_time_limit=3600,
    time_limit=3900,
)
def run_semantic_clustering(self, task_id: str):
    """Фоновая задача семантической кластеризации catalog_positions.

    Шаги:
    1. Fetch позиций из БД (asyncpg).
    2. UMAP + HDBSCAN (CPU-bound, через asyncio.to_thread).
    3. LLM naming кластеров (Gemini).
    4. Persist результатов в БД (одна транзакция asyncpg).
    """
    start = time.time()
    logger.info("Task %s: start semantic clustering", task_id)

    # Распределённая блокировка: не допускает параллельных задач кластеризации,
    # которые могут обработать одни и те же позиции и создать конфликтующие группы.
    lock = redis_client.lock(_CLUSTERER_LOCK_KEY, timeout=_CLUSTERER_LOCK_TTL, blocking=False)
    if not lock.acquire(blocking=False):
        logger.warning("Task %s: another clustering task is running, skipping.", task_id)
        _safe_set_status(task_id, {"status": "skipped", "error": "another clustering task is running"})
        return {"task_id": task_id, "status": "skipped"}

    _safe_set_status(task_id, {"status": "processing", "stage": "fetching_data"})

    try:
        # TODO(R5): run_async не поддерживает отмену корутины при SoftTimeLimitExceeded.
        # С --concurrency=1 корутина завершится при перезапуске процесса.
        clusters_found = run_async(_run_clustering_async(task_id))

        _safe_set_status(task_id, {"status": "completed", "clusters_found": clusters_found})
        logger.info("Task %s: completed, clusters_found=%d", task_id, clusters_found)
        return {"task_id": task_id, "status": "completed", "clusters_found": clusters_found}

    except SoftTimeLimitExceeded:
        _safe_set_status(
            task_id,
            {"status": "failed", "error": "soft time limit exceeded"},
        )
        logger.exception("Task %s: soft time limit exceeded", task_id)
        raise
    except Exception as e:
        will_retry = self.request.retries < self.max_retries
        _safe_set_status(
            task_id,
            {
                "status": "retrying" if will_retry else "failed",
                "error": str(e),
                "retry": self.request.retries,
                "max_retries": self.max_retries,
            },
        )
        logger.exception("Task %s: error (retry %s/%s)", task_id, self.request.retries, self.max_retries)
        if will_retry:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        else:
            raise
    finally:
        try:
            lock.release()
        except Exception:
            logger.debug("Task %s: lock release failed (may have expired)", task_id, exc_info=True)
        duration = time.time() - start
        logger.info("Task %s: finished in %.2fs", task_id, duration)


async def _run_clustering_async(task_id: str) -> int:
    """Оркестрирует асинхронный пайплайн кластеризации."""
    worker = SemanticClustererWorker()
    try:
        await worker.initialize()
        clusters_found = await worker.run_clustering(task_id, bump_ttl_fn=_bump_ttl)
        return clusters_found
    finally:
        await worker.shutdown()
