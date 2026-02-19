# -*- coding: utf-8 -*-
# app/workers/search_indexer/worker.py
"""
Асинхронная бизнес-логика для Search Indexer воркера.

Пайплайн на каждую строку catalog_positions (status='pending_indexing'):
1. Генерация 768-d embedding через Gemini ``gemini-embedding-001``.
   Embedding строится на основе **composite semantic string** —
   description + единица измерения (LEFT JOIN units_of_measurement),
   что позволяет различать «Стяжка м2» и «Стяжка м3».
2. Поиск дубликатов среди active-записей (cosine distance < 0.15).
   Если найден → insert в ``suggested_merges``.
3. Атомарное обновление: SET embedding, status='active', updated_at=NOW().

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

# Database
DB_USER: str = os.getenv("DB_USER", "postgres")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: str = os.getenv("DB_PORT", "5432")
DB_NAME: str = os.getenv("DB_NAME", "tendersdb")

# Google AI — модель и размерность
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
EMBEDDING_MODEL: str = os.getenv(
    "SEARCH_INDEXER_EMBEDDING_MODEL", "gemini-embedding-001"
)
EMBEDDING_DIM: int = int(os.getenv("SEARCH_INDEXER_EMBEDDING_DIM", "768"))

# Размер батча и пороги
BATCH_SIZE: int = int(os.getenv("SEARCH_INDEXER_BATCH_SIZE", "50"))
DEDUP_DISTANCE_THRESHOLD: float = float(
    os.getenv("SEARCH_INDEXER_DEDUP_THRESHOLD", "0.15")
)

# Ограничение параллельных запросов к Gemini (rate-limit safe)
EMBED_CONCURRENCY: int = int(os.getenv("SEARCH_INDEXER_EMBED_CONCURRENCY", "5"))

# Database pool
POOL_MIN_SIZE: int = int(os.getenv("SEARCH_INDEXER_POOL_MIN", "2"))
POOL_MAX_SIZE: int = int(os.getenv("SEARCH_INDEXER_POOL_MAX", "10"))

# Интервал поллинга (секунды)
POLL_INTERVAL_S: int = int(os.getenv("SEARCH_INDEXER_POLL_INTERVAL", "10"))


# ──────────────────────────────────────────────────────────────────────
# SQL-запросы
# ──────────────────────────────────────────────────────────────────────

SQL_FETCH_PENDING = """
    SELECT cp.id,
           cp.description,
           cp.standard_job_title,
           uom.normalized_name AS unit_name
    FROM catalog_positions cp
    LEFT JOIN units_of_measurement uom ON cp.unit_id = uom.id
    WHERE cp.status = 'pending_indexing'
    ORDER BY cp.id
    LIMIT $1;
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

SQL_ACTIVATE = """
    UPDATE catalog_positions
    SET embedding   = $1::vector,
        status      = 'active',
        updated_at  = NOW()
    WHERE id = $2;
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
        self._sem = asyncio.Semaphore(EMBED_CONCURRENCY)
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
        async with self._sem:
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
            dsn = (
                f"postgresql://{DB_USER}:{DB_PASSWORD}"
                f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
            )
            self._pool = await asyncpg.create_pool(
                dsn,
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

    async def run_indexing(self) -> Dict[str, Any]:
        """
        Обрабатывает один батч pending_indexing записей.

        Пайплайн для каждой строки:
        1. Генерация embedding (Gemini).
        2. Поиск дубликатов (cosine distance < threshold).
        3. Атомарное обновление (embedding + status='active').

        Returns:
            dict: {"processed": int, "duplicates": int}
        """
        if not self.is_initialized:
            raise RuntimeError(
                "Search Indexer Worker не инициализирован. "
                "Задача индексации не может быть запущена."
            )

        assert self._pool is not None
        assert self._embedder is not None

        async with self._pool.acquire() as conn:
            rows: Sequence[asyncpg.Record] = await conn.fetch(
                SQL_FETCH_PENDING, BATCH_SIZE
            )

        if not rows:
            return {"processed": 0, "duplicates": 0}

        self.logger.info(
            "Получен батч pending_indexing записей",
            extra={"batch_size": len(rows)},
        )

        processed = 0
        duplicates = 0

        for row in rows:
            pos_id: int = row["id"]
            description: str = row["description"] or ""
            title: str = row["standard_job_title"] or ""
            unit_name: str = row["unit_name"] or ""

            try:
                # 1. Composite semantic string (unit-aware)
                if unit_name:
                    text_to_embed = f"{description}. Единица измерения: {unit_name}"
                else:
                    text_to_embed = description

                embedding = await self._embedder.embed(text_to_embed)
                emb_literal = _vector_literal(embedding)

                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        # 2. Deduplication check
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

                        # 3. Activate
                        await conn.execute(SQL_ACTIVATE, emb_literal, pos_id)

                processed += 1
                self.logger.info(
                    "Активирована позиция %s (%s)",
                    pos_id,
                    title[:80],
                    extra={"position_id": pos_id},
                )

            except Exception:
                self.logger.exception(
                    "Ошибка обработки позиции %s",
                    pos_id,
                    extra={"position_id": pos_id},
                )

        return {"processed": processed, "duplicates": duplicates}
