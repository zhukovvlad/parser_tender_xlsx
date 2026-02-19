# -*- coding: utf-8 -*-
# app/workers/search_indexer/worker.py
"""
Асинхронная бизнес-логика для Search Indexer воркера.

Двухфазный пайплайн обработки catalog_positions:

Phase 1 — Claim (atomic, race-condition safe):
  UPDATE ... SET status='indexing' WHERE status='pending_indexing'
  с FOR UPDATE SKIP LOCKED.

Phase 2 — Embed (вне транзакции):
  768-d embedding через Gemini ``gemini-embedding-001``.
  Composite semantic string = description + единица измерения
  (LEFT JOIN units_of_measurement для различения «Стяжка м2» / «Стяжка м3»).

Phase 3 — Activate (со status guard):
  Дедупликация по cosine distance < 0.15 → suggested_merges.
  SET embedding, status='active' WHERE id = $2 AND status = 'indexing'.

Recovery:
  Зависшие 'indexing' записи (воркер упал) сбрасываются в 'pending_indexing'
  через reset_stale_claims() / периодическую Celery-задачу.

Технические заметки:
- Pure ``asyncpg`` — без ORM.
- ``standard_job_title`` уже лемматизирован upstream — не трогаем.
- Дедупликация использует HNSW индекс ``idx_cp_kind_pos_hnsw``
  (cosine distance оператор ``<=>``).
- Для 768-d embedding требуется L2-нормализация (см. документацию Gemini).
"""

from __future__ import annotations

import asyncio
import math
import os
from typing import Any, Dict, Sequence

import asyncpg
from dotenv import load_dotenv
from google import genai
from google.genai import types

from .logger import get_search_indexer_logger

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────

def _safe_int(env_var: str, default: int) -> int:
    """Безопасный парсинг int из переменной окружения."""
    raw = os.getenv(env_var, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _safe_float(env_var: str, default: float) -> float:
    """Безопасный парсинг float из переменной окружения."""
    raw = os.getenv(env_var, "")
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


# Database
DB_USER: str = os.getenv("DB_USER", "postgres")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = _safe_int("DB_PORT", 5432)
DB_NAME: str = os.getenv("DB_NAME", "tendersdb")

# Google AI — модель и размерность
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
EMBEDDING_MODEL: str = os.getenv(
    "SEARCH_INDEXER_EMBEDDING_MODEL", "gemini-embedding-001"
)
EMBEDDING_DIM: int = _safe_int("SEARCH_INDEXER_EMBEDDING_DIM", 768)

# Размер батча и пороги
BATCH_SIZE: int = _safe_int("SEARCH_INDEXER_BATCH_SIZE", 50)
DEDUP_DISTANCE_THRESHOLD: float = _safe_float(
    "SEARCH_INDEXER_DEDUP_THRESHOLD", 0.15
)

# Database pool
POOL_MIN_SIZE: int = _safe_int("SEARCH_INDEXER_POOL_MIN", 2)
POOL_MAX_SIZE: int = _safe_int("SEARCH_INDEXER_POOL_MAX", 10)

# Интервал поллинга (секунды)
POLL_INTERVAL_S: int = _safe_int("SEARCH_INDEXER_POLL_INTERVAL", 10)

# Timeout для сброса зависших 'indexing' claims (секунды, по умолчанию 1 час)
STALE_CLAIM_TIMEOUT_S: int = _safe_int("SEARCH_INDEXER_STALE_TIMEOUT", 3600)


# ──────────────────────────────────────────────────────────────────────
# SQL-запросы
# ──────────────────────────────────────────────────────────────────────

# Phase 1: Claim — atomic UPDATE...RETURNING с FOR UPDATE SKIP LOCKED.
# Переводит status 'pending_indexing' → 'indexing'. JOIN с units_of_measurement
# выполняется над результатом CTE.
SQL_CLAIM_BATCH = """
    WITH claimed AS (
        UPDATE catalog_positions
        SET status     = 'indexing',
            updated_at = NOW()
        WHERE id IN (
            SELECT id
            FROM catalog_positions
            WHERE status = 'pending_indexing'
            ORDER BY id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, description, standard_job_title, unit_id
    )
    SELECT c.id,
           c.description,
           c.standard_job_title,
           uom.normalized_name AS unit_name
    FROM claimed c
    LEFT JOIN units_of_measurement uom ON c.unit_id = uom.id
    ORDER BY c.id;
"""

# Cosine distance search по active-записям через HNSW индекс.
# $1 = embedding vector (text cast), $2 = current row id, $3 = threshold.
SQL_FIND_DUPLICATE = """
    SELECT id,
           (embedding <=> $1::vector) AS distance
    FROM catalog_positions
    WHERE status = 'active'
      AND id <> $2
      AND (embedding <=> $1::vector) < $3
    ORDER BY distance
    LIMIT 1;
"""

SQL_INSERT_MERGE = """
    INSERT INTO suggested_merges
        (main_position_id, duplicate_position_id, similarity_score, status)
    VALUES ($1, $2, $3, 'PENDING')
    ON CONFLICT DO NOTHING;
"""

# Phase 3: Activate — status guard ensures only claimed rows are updated.
SQL_ACTIVATE = """
    UPDATE catalog_positions
    SET embedding   = $1::vector,
        status      = 'active',
        updated_at  = NOW()
    WHERE id = $2 AND status = 'indexing';
"""

# Activate without embedding (for rows with empty descriptions).
SQL_ACTIVATE_NO_EMBEDDING = """
    UPDATE catalog_positions
    SET status      = 'active',
        updated_at  = NOW()
    WHERE id = $1 AND status = 'indexing';
"""

# Recovery: reset stale 'indexing' claims back to 'pending_indexing'.
# $1 = max age in seconds.
SQL_RESET_STALE = """
    UPDATE catalog_positions
    SET status     = 'pending_indexing',
        updated_at = NOW()
    WHERE status = 'indexing'
      AND updated_at < NOW() - make_interval(secs => $1::double precision)
    RETURNING id;
"""


# ──────────────────────────────────────────────────────────────────────
# Embedding-клиент (Gemini)
# ──────────────────────────────────────────────────────────────────────


class EmbeddingClient:
    """
    Обёртка над Google GenAI Embedding API.

    Использует модель ``gemini-embedding-001`` с task_type=SEMANTIC_SIMILARITY
    и output_dimensionality=768. Результат нормализуется до единичного вектора
    (требование документации для размерностей < 3072).
    """

    def __init__(
        self,
        api_key: str,
        model: str = EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
    ) -> None:
        if not api_key:
            raise ValueError("GOOGLE_API_KEY обязателен для генерации эмбеддингов")
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._dim = dim
        self._config = types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=dim,
        )

    async def embed(self, text: str) -> list[float]:
        """
        Возвращает нормализованный embedding-вектор заданной размерности.

        Args:
            text: Текст для эмбеддинга (description из catalog_positions).

        Returns:
            Нормализованный список float длиной ``self._dim``.
        """
        response = await asyncio.to_thread(
            self._client.models.embed_content,
            model=self._model,
            contents=text,
            config=self._config,
        )
        raw = list(response.embeddings[0].values)
        return _l2_normalize(raw)

    async def close(self) -> None:
        """Освобождение ресурсов (для совместимости интерфейса)."""
        pass


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2-нормализация вектора до единичной длины."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _vector_literal(vec: list[float]) -> str:
    """Конвертация Python-списка в pgvector текстовый литерал ``'[0.1,0.2,…]'``."""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


# ──────────────────────────────────────────────────────────────────────
# Основной воркер
# ──────────────────────────────────────────────────────────────────────


class SearchIndexerWorker:
    """
    Асинхронная бизнес-логика: Fetch → Embed → Deduplicate → Activate.

    Аналогичен по структуре RagWorker:
    - __init__ создаёт инстанс без подключений
    - initialize() устанавливает пул БД и embedding-клиент
    - run_indexing() — основной цикл обработки одного батча
    """

    def __init__(self) -> None:
        self.logger = get_search_indexer_logger("worker")
        self._pool: asyncpg.Pool | None = None
        self._embedder: EmbeddingClient | None = None
        self.is_initialized: bool = False

    async def initialize(self) -> None:
        """
        Инициализирует пул подключений и embedding-клиент.
        Вызывается при старте воркера (аналог initialize_store в RagWorker).
        """
        self.logger.info("Инициализация Search Indexer Worker...")
        try:
            self._pool = await asyncpg.create_pool(
                user=DB_USER,
                password=DB_PASSWORD,
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                command_timeout=60,
            )
            self._embedder = EmbeddingClient(api_key=GOOGLE_API_KEY)
            self.is_initialized = True
            self.logger.info(
                "Search Indexer Worker инициализирован "
                "(model=%s, dim=%d, threshold=%.2f)",
                EMBEDDING_MODEL,
                EMBEDDING_DIM,
                DEDUP_DISTANCE_THRESHOLD,
            )
        except Exception as e:
            self.is_initialized = False
            self.logger.critical(
                f"Не удалось инициализировать Search Indexer Worker: {e}",
                exc_info=True,
            )
            raise

    async def shutdown(self) -> None:
        """Корректное завершение: закрываем пул и клиент."""
        if self._pool:
            await self._pool.close()
        if self._embedder:
            await self._embedder.close()
        self.logger.info("Search Indexer Worker остановлен")

    def get_pool(self) -> asyncpg.Pool:
        """Публичный доступ к пулу подключений (для тестов/диагностики)."""
        if self._pool is None:
            raise RuntimeError("Worker не инициализирован — пул недоступен")
        return self._pool

    async def fetch_indexing_stats(self) -> tuple[int, int, int]:
        """
        Возвращает (pending_count, active_count, indexing_count)
        из catalog_positions.

        Удобно для smoke-тестов и мониторинга.
        """
        pool = self.get_pool()
        async with pool.acquire() as conn:
            pending = await conn.fetchval(
                "SELECT count(*) FROM catalog_positions "
                "WHERE status = 'pending_indexing'"
            )
            active = await conn.fetchval(
                "SELECT count(*) FROM catalog_positions WHERE status = 'active'"
            )
            indexing = await conn.fetchval(
                "SELECT count(*) FROM catalog_positions "
                "WHERE status = 'indexing'"
            )
        return pending, active, indexing

    async def reset_stale_claims(
        self, max_age_seconds: int = STALE_CLAIM_TIMEOUT_S
    ) -> int:
        """
        Сбрасывает зависшие 'indexing' записи обратно в 'pending_indexing'.

        Записи, которые находятся в статусе 'indexing' дольше
        max_age_seconds, считаются зависшими (воркер упал или
        превысил timeout).

        Args:
            max_age_seconds: Максимальный возраст claim в секундах.

        Returns:
            Количество сброшенных записей.
        """
        pool = self.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                SQL_RESET_STALE, float(max_age_seconds)
            )
        count = len(rows)
        if count > 0:
            reset_ids = [r["id"] for r in rows]
            self.logger.warning(
                "Reset %d stale 'indexing' claims → 'pending_indexing': %s",
                count,
                reset_ids[:20],
                extra={"reset_count": count},
            )
        return count

    async def run_indexing(self) -> Dict[str, Any]:
        """
        Обрабатывает один батч позиций (two-phase claim → embed → activate).

        Phase 1: Atomic claim (status 'pending_indexing' → 'indexing').
        Phase 2: Embedding generation (outside transaction).
        Phase 3: Deduplication + activate (status guard 'indexing' → 'active').

        Returns:
            dict: {"processed": int, "duplicates": int, "skipped": int}
        """
        if not self.is_initialized:
            raise RuntimeError(
                "Search Indexer Worker не инициализирован. "
                "Задача индексации не может быть запущена."
            )

        assert self._pool is not None
        assert self._embedder is not None

        # Phase 1: Claim batch atomically (FOR UPDATE SKIP LOCKED)
        async with self._pool.acquire() as conn:
            rows: Sequence[asyncpg.Record] = await conn.fetch(
                SQL_CLAIM_BATCH, BATCH_SIZE
            )

        if not rows:
            return {"processed": 0, "duplicates": 0, "skipped": 0}

        self.logger.info(
            "Claimed batch for indexing (status → 'indexing')",
            extra={"batch_size": len(rows)},
        )

        processed = 0
        duplicates = 0
        skipped = 0

        # ── Phase 2: Embedding (outside DB connection) ──────────────
        # Собираем эмбеддинги заранее, чтобы не держать DB-соединение
        # открытым на время сетевых вызовов к Gemini.
        # embed_results: list of (pos_id, title, emb_literal | None, skip_reason | None)
        embed_results: list[tuple[int, str, str | None, str | None]] = []

        for row in rows:
            pos_id: int = row["id"]
            description: str = row["description"] or ""
            title: str = row["standard_job_title"] or ""
            unit_name: str = row["unit_name"] or ""

            if not description.strip():
                self.logger.warning(
                    "Позиция %s (%s): пустое описание — "
                    "активация без эмбеддинга",
                    pos_id,
                    title[:80],
                    extra={"position_id": pos_id},
                )
                embed_results.append((pos_id, title, None, "no_description"))
                continue

            try:
                # Composite semantic string (unit-aware)
                if unit_name:
                    text_to_embed = (
                        f"{description}. Единица измерения: {unit_name}"
                    )
                else:
                    text_to_embed = description

                embedding = await self._embedder.embed(text_to_embed)
                emb_literal = _vector_literal(embedding)
                embed_results.append((pos_id, title, emb_literal, None))
            except Exception:
                self.logger.exception(
                    "Ошибка генерации эмбеддинга для позиции %s",
                    pos_id,
                    extra={"position_id": pos_id},
                )
                embed_results.append((pos_id, title, None, "embed_error"))

        # ── Phase 3: DB operations (fast, single connection) ────────
        async with self._pool.acquire() as conn:
            for pos_id, title, emb_literal, skip_reason in embed_results:
                if skip_reason == "no_description":
                    result = await conn.execute(
                        SQL_ACTIVATE_NO_EMBEDDING, pos_id
                    )
                    if result == "UPDATE 1":
                        skipped += 1
                    else:
                        self.logger.warning(
                            "Activate-no-embed no-op pos_id=%s "
                            "(concurrent modification?)",
                            pos_id,
                            extra={"position_id": pos_id},
                        )
                    continue

                if skip_reason == "embed_error":
                    # Already logged during embed phase
                    continue

                # emb_literal is guaranteed not None here
                assert emb_literal is not None

                try:
                    async with conn.transaction():
                        # Deduplication check
                        dup = await conn.fetchrow(
                            SQL_FIND_DUPLICATE,
                            emb_literal,
                            pos_id,
                            DEDUP_DISTANCE_THRESHOLD,
                        )

                        if dup is not None:
                            distance: float = dup["distance"]
                            similarity = 1.0 - distance
                            main_id: int = dup["id"]

                            await conn.execute(
                                SQL_INSERT_MERGE,
                                main_id,
                                pos_id,
                                round(similarity, 6),
                            )
                            duplicates += 1
                            self.logger.warning(
                                "Duplicate candidate found: %s resembles %s",
                                pos_id,
                                main_id,
                                extra={
                                    "position_id": pos_id,
                                    "duplicate_id": main_id,
                                    "similarity": round(similarity, 6),
                                },
                            )

                        # Activate with status guard
                        activate_result = await conn.execute(
                            SQL_ACTIVATE, emb_literal, pos_id
                        )

                    if activate_result == "UPDATE 1":
                        processed += 1
                        self.logger.info(
                            "Активирована позиция %s (%s)",
                            pos_id,
                            title[:80],
                            extra={"position_id": pos_id},
                        )
                    else:
                        self.logger.warning(
                            "Activate no-op pos_id=%s (status guard)",
                            pos_id,
                            extra={"position_id": pos_id},
                        )

                except Exception:
                    self.logger.exception(
                        "Ошибка обработки позиции %s",
                        pos_id,
                        extra={"position_id": pos_id},
                    )

        return {"processed": processed, "duplicates": duplicates, "skipped": skipped}
