# -*- coding: utf-8 -*-
# app/workers/search_indexer/worker.py
"""
Асинхронная бизнес-логика для Search Indexer воркера.

Пайплайн обработки catalog_positions:

Phase 1 — Fetch (SELECT pending_indexing rows):
  SELECT ... WHERE status='pending_indexing' ORDER BY id LIMIT N.

Phase 2 — Embed (вне транзакции):
  768-d embedding через Gemini ``gemini-embedding-001``.
  Composite semantic string = description + единица измерения
  (LEFT JOIN units_of_measurement для различения «Стяжка м2» / «Стяжка м3»).

Phase 3 — Activate (со status guard):
  Дедупликация по cosine distance < 0.15 → suggested_merges.
  SET embedding, status='active' WHERE id = $2 AND status = 'pending_indexing'.
  Если строку уже обработал другой воркер, UPDATE затронет 0 строк (идемпотентно).

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

# Timeout на один вызов Gemini Embedding API (секунды)
EMBED_TIMEOUT_S: int = _safe_int("SEARCH_INDEXER_EMBED_TIMEOUT", 60)

# Fail-fast: максимальное количество подряд неудачных embed-вызовов
# перед досрочным прекращением батча
MAX_CONSECUTIVE_EMBED_ERRORS: int = _safe_int(
    "SEARCH_INDEXER_MAX_CONSECUTIVE_ERRORS", 3
)


# ──────────────────────────────────────────────────────────────────────
# SQL-запросы
# ──────────────────────────────────────────────────────────────────────

# Phase 1: Fetch — SELECT pending_indexing rows.
# JOIN с units_of_measurement для получения единицы измерения.
SQL_FETCH_BATCH = """
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

# Phase 3: Activate — status guard ensures idempotency.
SQL_ACTIVATE = """
    UPDATE catalog_positions
    SET embedding   = $1::vector,
        status      = 'active',
        updated_at  = NOW()
    WHERE id = $2 AND status = 'pending_indexing';
"""

# Activate without embedding (for rows with empty descriptions).
SQL_ACTIVATE_NO_EMBEDDING = """
    UPDATE catalog_positions
    SET status      = 'active',
        updated_at  = NOW()
    WHERE id = $1 AND status = 'pending_indexing';
"""




# ──────────────────────────────────────────────────────────────────────
# Embedding-клиент (Gemini)
# ──────────────────────────────────────────────────────────────────────


class EmbeddingClient:
    """
    Обёртка над Google Gemini Embedding API (sync SDK).

    Использует синхронный ``client.models.embed_content()`` из
    ``google-genai``, как в документации:
    https://ai.google.dev/gemini-api/docs/embeddings

    Ключевые оптимизации:

    - **Batch embedding**: все тексты батча отправляются одним HTTP-запросом
      через ``contents=[text1, text2, ...]``, что критически снижает
      количество SSL-handshake и сетевых round-trip (1 вместо N).
    - **Retry с пересозданием клиента**: при ConnectTimeout / SSL-ошибках
      httpx-клиент пересоздаётся со свежим SSL-контекстом.
    - **Увеличенный connect timeout**: 60 с на SSL handshake
      (в WSL2 / нестабильных сетях стандартный timeout недостаточен).

    Sync SDK работает через httpx и не страдает от проблем
    aiohttp + fork() в Celery. Блокирующий вызов выносится
    в поток через ``asyncio.to_thread()``.

    Клиент создаётся лениво — **после fork**, чтобы SSL-контекст
    был свежим.
    """

    def __init__(
        self,
        api_key: str,
        model: str = EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
    ) -> None:
        if not api_key:
            raise ValueError("GOOGLE_API_KEY обязателен для генерации эмбеддингов")
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._client: Any = None
        self._logger = get_search_indexer_logger("embedding_client")

    def _get_client(self):
        """Ленивое создание клиента (после fork).

        Импорт google.genai выполняется здесь, а не на уровне модуля,
        чтобы httpx/SSL инициализировались в дочернем процессе Celery,
        а не наследовались от MainProcess через fork().

        HTTP-конфигурация:
        - connect timeout = 60 с (SSL handshake в WSL2 может быть медленным)
        - read/write/pool timeout = 120 с (batch embedding обрабатывается долго)
        - SDK timeout = 120 000 мс (общий таймаут на запрос)
        """
        if self._client is None:
            import httpx as httpx_lib  # noqa: E402  # импорт после fork!
            from google import genai  # noqa: E402  # импорт после fork!
            from google.genai import types  # noqa: E402  # импорт после fork!

            self._client = genai.Client(
                api_key=self._api_key,
                http_options=types.HttpOptions(
                    timeout=120_000,  # 120s общий таймаут SDK (мс)
                    client_args={
                        "timeout": httpx_lib.Timeout(
                            120.0,        # default для read/write/pool
                            connect=60.0,  # 60s для SSL handshake (WSL2)
                        ),
                    },
                ),
            )
        return self._client

    def _reset_client(self) -> None:
        """Сбрасывает httpx-клиент для создания свежего SSL-соединения.

        Вызывается при ConnectTimeout / SSL-ошибках, чтобы следующий
        запрос не переиспользовал «мёртвый» connection pool.
        Закрывает старый клиент для освобождения connection pool.
        """
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass  # best-effort: клиент мог быть уже сломан
        self._client = None

    def _embed_sync(self, text: str) -> list[float]:
        """Синхронный вызов embed_content для одного текста (запускается в потоке)."""
        from google.genai import types  # noqa: импорт после fork!

        client = self._get_client()
        result = client.models.embed_content(
            model=self._model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY",
                output_dimensionality=self._dim,
            ),
        )
        return list(result.embeddings[0].values)

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """Batch embed_content — один HTTP-запрос для N текстов.

        Согласно документации Google Gemini Embedding API,
        ``contents`` принимает список строк и возвращает
        соответствующий список эмбеддингов:
        https://ai.google.dev/gemini-api/docs/embeddings#generating-embeddings
        """
        from google.genai import types  # noqa: импорт после fork!

        client = self._get_client()
        result = client.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type="SEMANTIC_SIMILARITY",
                output_dimensionality=self._dim,
            ),
        )
        return [list(emb.values) for emb in result.embeddings]

    async def embed(self, text: str) -> list[float]:
        """
        Возвращает нормализованный embedding-вектор заданной размерности.

        Для обработки батчей предпочтительнее ``embed_batch()``.
        """
        raw = await asyncio.wait_for(
            asyncio.to_thread(self._embed_sync, text),
            timeout=EMBED_TIMEOUT_S,
        )
        if len(raw) != self._dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._dim}, "
                f"got {len(raw)} from model '{self._model}'"
            )
        return _l2_normalize(raw)

    async def embed_batch(
        self,
        texts: list[str],
        max_retries: int = 3,
    ) -> list[list[float]]:
        """Batch embedding с retry и пересозданием клиента при сетевых ошибках.

        Отправляет все тексты одним HTTP-запросом, что критически снижает
        количество SSL-handshake (1 вместо N). При ConnectTimeout / SSL-
        ошибках пересоздаёт httpx-клиент и повторяет с exponential backoff.

        Args:
            texts: Список текстов для эмбеддинга.
            max_retries: Максимальное количество попыток при сетевых ошибках.

        Returns:
            Список L2-нормализованных эмбеддинг-векторов (порядок = порядку texts).

        Raises:
            Последнее исключение, если все попытки исчерпаны.
        """
        import httpx as httpx_lib  # noqa: E402  # импорт после fork!

        last_exc: BaseException | None = None
        # Увеличенный таймаут для батча
        batch_timeout = EMBED_TIMEOUT_S + len(texts) * 2

        for attempt in range(max_retries):
            try:
                raw_list = await asyncio.wait_for(
                    asyncio.to_thread(self._embed_batch_sync, texts),
                    timeout=batch_timeout,
                )
                # Валидация размерности и L2-нормализация
                results: list[list[float]] = []
                for i, raw in enumerate(raw_list):
                    if len(raw) != self._dim:
                        raise ValueError(
                            f"Embedding dimension mismatch at index {i}: "
                            f"expected {self._dim}, got {len(raw)}"
                        )
                    results.append(_l2_normalize(raw))
                return results
            except (
                httpx_lib.ConnectTimeout,
                httpx_lib.ConnectError,
                httpx_lib.ReadTimeout,
                TimeoutError,
                asyncio.TimeoutError,
                ConnectionError,
                OSError,
            ) as exc:
                last_exc = exc
                self._reset_client()  # свежий SSL-контекст
                if attempt < max_retries - 1:
                    delay = 2 ** attempt  # 1s, 2s
                    self._logger.warning(
                        "Batch embed attempt %d/%d failed: %s. "
                        "Retrying in %ds with fresh client...",
                        attempt + 1,
                        max_retries,
                        type(exc).__name__,
                        delay,
                        extra={"attempt": attempt + 1, "error": str(exc)},
                    )
                    await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            "embed_batch: no exception captured; check max_retries "
            f"(max_retries={max_retries})"
        )

    async def close(self) -> None:
        """Освобождение ресурсов (закрытие httpx connection pool)."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass  # best-effort
        self._client = None


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2-нормализация вектора до единичной длины.

    Raises:
        ValueError: Если все компоненты вектора нулевые (нулевая L2-норма).
            Такой вектор недопустим для cosine similarity вычислений.
    """
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        raise ValueError(
            "Невозможно L2-нормализовать вектор с нулевой нормой "
            "(все компоненты равны 0)"
        )
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

    async def fetch_indexing_stats(self) -> tuple[int, int]:
        """
        Возвращает (pending_count, active_count)
        из catalog_positions.

        Удобно для smoke-тестов и мониторинга.
        Использует единый агрегатный запрос вместо двух round-trip.
        """
        pool = self.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT "
                "  COUNT(*) FILTER (WHERE status = 'pending_indexing') AS pending, "
                "  COUNT(*) FILTER (WHERE status = 'active') AS active "
                "FROM catalog_positions"
            )
        return row["pending"], row["active"]

    async def run_indexing(self) -> Dict[str, Any]:
        """
        Обрабатывает один батч позиций (fetch → embed → activate).

        Phase 1: Fetch pending_indexing rows (SELECT only, no status change).
        Phase 2: Embedding generation (outside transaction).
        Phase 3: Deduplication + activate (status guard 'pending_indexing' → 'active').

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

        # Phase 1: Fetch pending_indexing rows
        async with self._pool.acquire() as conn:
            rows: Sequence[asyncpg.Record] = await conn.fetch(
                SQL_FETCH_BATCH, BATCH_SIZE
            )

        if not rows:
            return {"processed": 0, "duplicates": 0, "skipped": 0}

        self.logger.info(
            "Fetched batch for indexing",
            extra={"batch_size": len(rows)},
        )

        processed = 0
        duplicates = 0
        skipped = 0

        # ── Phase 2: Embedding (outside DB connection) ──────────────
        # Собираем эмбеддинги заранее, чтобы не держать DB-соединение
        # открытым на время сетевых вызовов к Gemini.
        #
        # Используем BATCH embedding: все тексты отправляются одним
        # HTTP-запросом к Gemini API (contents=[...]), что сокращает
        # количество SSL-handshake с N до 1.
        # embed_results: list of (pos_id, title, emb_literal | None, skip_reason | None)
        embed_results: list[tuple[int, str, str | None, str | None]] = []

        # Step 1: Разделяем строки на embeddable и no-description
        embeddable_rows: list[tuple[int, str, str]] = []  # (pos_id, title, text_to_embed)

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

            # Composite semantic string (unit-aware)
            if unit_name:
                text_to_embed = (
                    f"{description}. Единица измерения: {unit_name}"
                )
            else:
                text_to_embed = description

            embeddable_rows.append((pos_id, title, text_to_embed))

        # Step 2: Batch embed — один HTTP-запрос для всех текстов
        if embeddable_rows:
            texts = [t[2] for t in embeddable_rows]
            try:
                embeddings = await self._embedder.embed_batch(texts)
                if len(embeddings) != len(texts):
                    self.logger.error(
                        "Embedding count mismatch: expected %d, got %d",
                        len(texts),
                        len(embeddings),
                        extra={
                            "expected": len(texts),
                            "actual": len(embeddings),
                        },
                    )
                    raise ValueError(
                        f"Embedding count mismatch: "
                        f"expected {len(texts)}, got {len(embeddings)}"
                    )
                for (e_pos_id, e_title, _), embedding in zip(
                    embeddable_rows, embeddings, strict=True
                ):
                    emb_literal = _vector_literal(embedding)
                    embed_results.append(
                        (e_pos_id, e_title, emb_literal, None)
                    )
                self.logger.info(
                    "Batch embedding succeeded for %d positions",
                    len(embeddable_rows),
                    extra={"batch_size": len(embeddable_rows)},
                )
            except Exception:
                self.logger.exception(
                    "Batch embedding failed for %d positions, "
                    "rows remain pending_indexing for next run",
                    len(embeddable_rows),
                    extra={"embed_error_count": len(embeddable_rows)},
                )
                for e_pos_id, e_title, _ in embeddable_rows:
                    embed_results.append(
                        (e_pos_id, e_title, None, "embed_error")
                    )

        # embed_error rows остаются в 'pending_indexing' — будут обработаны
        # при следующем запуске задачи.
        embed_error_ids = [
            pid for pid, _, _, reason in embed_results
            if reason == "embed_error"
        ]
        if embed_error_ids:
            self.logger.warning(
                "Embed errors for %d rows (will retry next run): %s",
                len(embed_error_ids),
                embed_error_ids[:20],
                extra={"embed_error_count": len(embed_error_ids)},
            )

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
                # (no_description and embed_error were handled above)
                if emb_literal is None:
                    raise ValueError(
                        f"emb_literal is None for pos_id={pos_id} "
                        f"— unexpected: skip_reason should have been set"
                    )

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
                    # Строка остаётся в 'pending_indexing' —
                    # будет обработана при следующем запуске.

        return {"processed": processed, "duplicates": duplicates, "skipped": skipped}
