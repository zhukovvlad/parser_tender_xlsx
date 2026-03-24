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
- ``standard_job_title`` лемматизируется этим воркером для ВСЕХ видов записей
  (POSITION и GROUP_TITLE) через spaCy ru_core_news_sm, независимо от upstream-источника.
- Дедупликация использует HNSW индекс ``idx_cp_kind_pos_hnsw``
  (cosine distance оператор ``<=>``).
- Для 768-d embedding требуется L2-нормализация (см. документацию Gemini).
"""

from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime
from typing import Any, Dict, Sequence

import asyncpg
from asyncpg.exceptions import UniqueViolationError
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
EMBEDDING_MODEL: str = os.getenv("SEARCH_INDEXER_EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_DIM: int = _safe_int("SEARCH_INDEXER_EMBEDDING_DIM", 768)

# Размер батча и пороги
BATCH_SIZE: int = _safe_int("SEARCH_INDEXER_BATCH_SIZE", 50)
_SAFE_DEFAULT_DEDUP: float = 0.15
_raw_dedup = _safe_float("SEARCH_INDEXER_DEDUP_THRESHOLD", _SAFE_DEFAULT_DEDUP)
DEDUP_DISTANCE_THRESHOLD: float = _raw_dedup if 0.0 < _raw_dedup < 2.0 else _SAFE_DEFAULT_DEDUP

# Database pool
POOL_MIN_SIZE: int = _safe_int("SEARCH_INDEXER_POOL_MIN", 2)
POOL_MAX_SIZE: int = _safe_int("SEARCH_INDEXER_POOL_MAX", 10)

# Интервал поллинга (секунды)
POLL_INTERVAL_S: int = _safe_int("SEARCH_INDEXER_POLL_INTERVAL", 10)

# Timeout на один вызов Gemini Embedding API (секунды)
EMBED_TIMEOUT_S: int = _safe_int("SEARCH_INDEXER_EMBED_TIMEOUT", 60)

# Fail-fast: максимальное количество подряд неудачных embed-вызовов
# перед досрочным прекращением батча
MAX_CONSECUTIVE_EMBED_ERRORS: int = _safe_int("SEARCH_INDEXER_MAX_CONSECUTIVE_ERRORS", 3)


# ──────────────────────────────────────────────────────────────────────
# SQL-запросы
# ──────────────────────────────────────────────────────────────────────

# Phase 1: Fetch — SELECT pending_indexing rows.
# JOIN с units_of_measurement для получения единицы измерения.
#
# FOR UPDATE OF cp SKIP LOCKED — best-effort оптимизация: если два воркера
# запускают fetch ОДНОВРЕМЕННО (в пределах одного autocommit-statement),
# SKIP LOCKED позволяет второму воркеру пропустить строки, уже захваченные
# первым. Однако блокировки снимаются сразу после завершения implicit-транзакции
# (autocommit), поэтому защита от повторной выборки одних строк ПОСЛЕДОВАТЕЛЬНЫМИ
# воркерами не гарантируется.
#
# Реальная защита от двойной обработки обеспечивается в Phase 3 через
# status guard «AND status = 'pending_indexing'» — повторный UPDATE вернёт 0
# строк и будет проигнорирован (идемпотентность).
#
# TODO: для полной гарантии «непересекающихся» батчей реализовать атомарный
#   claim-паттерн через промежуточный статус «indexing_in_progress»:
#   UPDATE catalog_positions SET status = 'indexing_in_progress'
#   WHERE id IN (SELECT id ... WHERE status = 'pending_indexing' ORDER BY id
#                LIMIT $1 FOR UPDATE SKIP LOCKED)
#   RETURNING id, description, standard_job_title, kind, ...;
SQL_FETCH_BATCH = """
    SELECT cp.id,
           cp.description,
           cp.standard_job_title,
           cp.kind,
           cp.updated_at,
           uom.normalized_name AS unit_name
    FROM catalog_positions cp
    LEFT JOIN units_of_measurement uom ON cp.unit_id = uom.id
    WHERE cp.status = 'pending_indexing'
    ORDER BY cp.id
    LIMIT $1
    FOR UPDATE OF cp SKIP LOCKED;
"""

# Cosine distance search по active-записям через HNSW индекс.
# $1 = embedding vector (text cast), $2 = current row id.
# Порог дедупликации читается из system_settings прямо в момент
# выполнения запроса, что устраняет race condition.
SQL_FIND_DUPLICATE = """
    SELECT id,
           (embedding <=> $1::vector) AS distance
    FROM catalog_positions
    WHERE status = 'active'
      AND id <> $2
      AND (embedding <=> $1::vector) < LEAST(GREATEST(
            COALESCE(
              (SELECT value_numeric
                 FROM system_settings
                WHERE key = 'dedup_distance_threshold'
                LIMIT 1),
              0.15
            ),
            0.01), 2.0)
    ORDER BY distance
    LIMIT 1;
"""

SQL_INSERT_MERGE = """
    INSERT INTO suggested_merges
        (main_position_id, duplicate_position_id, similarity_score, status)
    VALUES ($1, $2, $3, 'PENDING')
    ON CONFLICT (main_position_id, duplicate_position_id) DO UPDATE
        SET similarity_score = EXCLUDED.similarity_score,
            status = CASE
                WHEN suggested_merges.status IN ('MERGED', 'REJECTED')
                THEN suggested_merges.status
                ELSE 'PENDING'
            END,
            updated_at = NOW();
"""

# Phase 3: Activate — status guard + concurrency guard ensure idempotency.
# Concurrency Guard ($3): updated_at используется как version token.
# Если любое поле строки (description, unit_id, standard_job_title и т.д.)
# было изменено администратором пока воркер ожидал Gemini,
# updated_at будет отличаться и UPDATE вернёт 0 строк. Строка останется
# pending_indexing и будет переиндексирована на следующем цикле.
# Применяется одинаково для POSITION и GROUP_TITLE.
SQL_ACTIVATE = """
    UPDATE catalog_positions
    SET embedding   = $1::vector,
        status      = 'active',
        updated_at  = NOW()
    WHERE id = $2
      AND status = 'pending_indexing'
      AND updated_at IS NOT DISTINCT FROM $3;
"""

# Activate group and update its lemmatized standard_job_title.
# Concurrency Guard ($4): updated_at как version token (см. SQL_ACTIVATE).
SQL_ACTIVATE_GROUP = """
    UPDATE catalog_positions
    SET embedding          = $1::vector,
        standard_job_title = $2,
        status             = 'active',
        updated_at         = NOW()
    WHERE id = $3
      AND status = 'pending_indexing'
      AND updated_at IS NOT DISTINCT FROM $4;
"""

# Activate group without embedding (empty description, but title was lemmatized).
# Concurrency Guard ($3): updated_at как version token (см. SQL_ACTIVATE).
SQL_ACTIVATE_GROUP_NO_EMBEDDING = """
    UPDATE catalog_positions
    SET standard_job_title = $1,
        status             = 'active',
        updated_at         = NOW()
    WHERE id = $2
      AND status = 'pending_indexing'
      AND updated_at IS NOT DISTINCT FROM $3;
"""

# Activate without embedding (for rows with empty descriptions).
# Concurrency Guard ($2): updated_at как version token (см. SQL_ACTIVATE).
SQL_ACTIVATE_NO_EMBEDDING = """
    UPDATE catalog_positions
    SET status      = 'active',
        updated_at  = NOW()
    WHERE id = $1
      AND status = 'pending_indexing'
      AND updated_at IS NOT DISTINCT FROM $2;
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
                            120.0,  # default для read/write/pool
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
                self._logger.debug("Ignored error closing genai client", exc_info=True)
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
                f"Embedding dimension mismatch: expected {self._dim}, " f"got {len(raw)} from model '{self._model}'"
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
                            f"Embedding dimension mismatch at index {i}: " f"expected {self._dim}, got {len(raw)}"
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
                    delay = 2**attempt  # 1s, 2s
                    self._logger.warning(
                        "Batch embed attempt %d/%d failed: %s. " "Retrying in %ds with fresh client...",
                        attempt + 1,
                        max_retries,
                        type(exc).__name__,
                        delay,
                        extra={"attempt": attempt + 1, "error": str(exc)},
                    )
                    await asyncio.sleep(delay)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("embed_batch: no exception captured; check max_retries " f"(max_retries={max_retries})")

    async def close(self) -> None:
        """Освобождение ресурсов (закрытие httpx connection pool)."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                self._logger.debug("Ignored error closing genai client", exc_info=True)
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
        raise ValueError("Невозможно L2-нормализовать вектор с нулевой нормой " "(все компоненты равны 0)")
    return [x / norm for x in vec]


def _lemmatize_text(text: str | None) -> str | None:
    """Лемматизация текста для GROUP_TITLE строк.

    Использует normalize_job_title_with_lemmatization из excel_parser,
    которая выполняет: lowercase → очистка Markdown/пунктуации →
    лемматизация через spaCy (ru_core_news_sm).

    Возвращает None, если ввод пустой или лемматизация не дала результата,
    чтобы сохранить контракт upstream (None = нет нормализованного title).
    """
    if not text or not text.strip():
        return None

    from app.excel_parser.sanitize_text import normalize_job_title_with_lemmatization  # импорт после fork!

    return normalize_job_title_with_lemmatization(text)


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
            if _raw_dedup != DEDUP_DISTANCE_THRESHOLD:
                self.logger.error(
                    "Env SEARCH_INDEXER_DEDUP_THRESHOLD=%.4f is out of range "
                    "(0.0 < t < 2.0), using safe default %.4f",
                    _raw_dedup,
                    DEDUP_DISTANCE_THRESHOLD,
                    extra={
                        "invalid_threshold": _raw_dedup,
                        "fallback_threshold": DEDUP_DISTANCE_THRESHOLD,
                    },
                )
            self.logger.info(
                "Search Indexer Worker инициализирован " "(model=%s, dim=%d, threshold=%.2f)",
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
            raise RuntimeError("Search Indexer Worker не инициализирован. " "Задача индексации не может быть запущена.")

        assert self._pool is not None
        assert self._embedder is not None

        # Phase 1: Fetch pending_indexing rows
        async with self._pool.acquire() as conn:
            rows: Sequence[asyncpg.Record] = await conn.fetch(SQL_FETCH_BATCH, BATCH_SIZE)

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
        # embed_results: list of (pos_id, title, kind, emb_literal | None, skip_reason | None,
        #                          description_raw, updated_at_raw)
        # updated_at_raw — version token для concurrency guard всех SQL-запросов.
        # Покрывает все поля: description, unit_id, standard_job_title и др.
        embed_results: list[tuple[int, str | None, str, str | None, str | None, str | None, datetime | None]] = []

        # Step 1: Разделяем строки на embeddable и no-description
        # (pos_id, title, kind, text_to_embed, description_raw, updated_at_raw)
        embeddable_rows: list[tuple[int, str | None, str, str, str | None, datetime | None]] = []

        for row in rows:
            pos_id: int = row["id"]
            description_raw: str | None = row["description"]
            description: str = description_raw or ""
            updated_at_raw: datetime | None = row["updated_at"]  # version token for concurrency guard
            title: str | None = row["standard_job_title"] or ""
            kind: str = row["kind"] or ""
            unit_name: str = row["unit_name"] or ""

            title = _lemmatize_text(title)

            if not description.strip():
                self.logger.warning(
                    "Позиция %s (%s): пустое описание — " "активация без эмбеддинга",
                    pos_id,
                    (title or "")[:80],
                    extra={"position_id": pos_id},
                )
                embed_results.append((pos_id, title, kind, None, "no_description", description_raw, updated_at_raw))
                continue

            # Composite semantic string (unit-aware)
            if unit_name:
                text_to_embed = f"{description}. Единица измерения: {unit_name}"
            else:
                text_to_embed = description

            embeddable_rows.append((pos_id, title, kind, text_to_embed, description_raw, updated_at_raw))

        # Step 2: Batch embed — один HTTP-запрос для всех текстов
        if embeddable_rows:
            texts = [t[3] for t in embeddable_rows]
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
                    raise ValueError(f"Embedding count mismatch: " f"expected {len(texts)}, got {len(embeddings)}")
                for (e_pos_id, e_title, e_kind, _, e_description_raw, e_updated_at_raw), embedding in zip(
                    embeddable_rows, embeddings, strict=True
                ):
                    emb_literal = _vector_literal(embedding)
                    embed_results.append(
                        (e_pos_id, e_title, e_kind, emb_literal, None, e_description_raw, e_updated_at_raw)
                    )
                self.logger.info(
                    "Batch embedding succeeded for %d positions",
                    len(embeddable_rows),
                    extra={"batch_size": len(embeddable_rows)},
                )
            except Exception:
                self.logger.exception(
                    "Batch embedding failed for %d positions, " "rows remain pending_indexing for next run",
                    len(embeddable_rows),
                    extra={"embed_error_count": len(embeddable_rows)},
                )
                for e_pos_id, e_title, e_kind, _, e_description_raw, e_updated_at_raw in embeddable_rows:
                    embed_results.append(
                        (e_pos_id, e_title, e_kind, None, "embed_error", e_description_raw, e_updated_at_raw)
                    )

        # embed_error rows остаются в 'pending_indexing' — будут обработаны
        # при следующем запуске задачи.
        embed_error_ids = [pid for pid, _, _, _, reason, _, _ in embed_results if reason == "embed_error"]
        if embed_error_ids:
            self.logger.warning(
                "Embed errors for %d rows (will retry next run): %s",
                len(embed_error_ids),
                embed_error_ids[:20],
                extra={"embed_error_count": len(embed_error_ids)},
            )

        # ── Phase 3: DB operations (fast, single connection) ────────
        async with self._pool.acquire() as conn:
            for pos_id, title, kind, emb_literal, skip_reason, _, updated_at_raw in embed_results:
                if skip_reason == "no_description":
                    if title is not None:
                        result = await conn.execute(SQL_ACTIVATE_GROUP_NO_EMBEDDING, title, pos_id, updated_at_raw)
                    else:
                        result = await conn.execute(SQL_ACTIVATE_NO_EMBEDDING, pos_id, updated_at_raw)
                    if result == "UPDATE 1":
                        skipped += 1
                    else:
                        self.logger.warning(
                            "Activate-no-embed no-op pos_id=%s "
                            "(status/updated_at guard или concurrency guard: "
                            "строка изменилась (updated_at/status) — будет переиндексирована позже)",
                            pos_id,
                            extra={"position_id": pos_id, "kind": kind},
                        )
                    continue

                if skip_reason == "embed_error":
                    # Already logged during embed phase
                    continue

                # emb_literal is guaranteed not None here
                # (no_description and embed_error were handled above)
                if emb_literal is None:
                    raise ValueError(
                        f"emb_literal is None for pos_id={pos_id} " f"— unexpected: skip_reason should have been set"
                    )

                early_guard_fired = False
                activate_result: str | None = None
                try:
                    async with conn.transaction():
                        # Early concurrency guard: verify updated_at (version token)
                        # hasn't changed since Phase 1. Prevents stale suggested_merges
                        # entries when any field (description, unit_id, standard_job_title)
                        # was edited by an admin while Gemini was running.
                        guard_ok = await conn.fetchval(
                            """
                            SELECT 1 FROM catalog_positions
                             WHERE id = $1
                               AND status = 'pending_indexing'
                               AND updated_at IS NOT DISTINCT FROM $2
                             FOR UPDATE SKIP LOCKED
                            """,
                            pos_id,
                            updated_at_raw,
                        )
                        if guard_ok is None:
                            early_guard_fired = True
                            self.logger.warning(
                                "Concurrency guard fired early for pos_id=%s: "
                                "строка изменена, уже не pending_indexing, "
                                "или залочена другим воркером (SKIP LOCKED) — "
                                "пропускаем dedup/merge/activate",
                                pos_id,
                                extra={"position_id": pos_id, "kind": kind},
                            )
                        else:
                            # Deduplication check
                            if kind == "POSITION":
                                dup = await conn.fetchrow(
                                    SQL_FIND_DUPLICATE,
                                    emb_literal,
                                    pos_id,
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

                            # Activate with status guard + concurrency guard
                            if title is not None:
                                activate_result = await conn.execute(
                                    SQL_ACTIVATE_GROUP,
                                    emb_literal,
                                    title,
                                    pos_id,
                                    updated_at_raw,
                                )
                            else:
                                activate_result = await conn.execute(SQL_ACTIVATE, emb_literal, pos_id, updated_at_raw)

                    if early_guard_fired:
                        # Already logged; row stays pending_indexing for re-indexing.
                        continue

                    if activate_result == "UPDATE 1":
                        processed += 1
                        self.logger.info(
                            "Активирована позиция %s (%s)",
                            pos_id,
                            (title or "")[:80],
                            extra={"position_id": pos_id},
                        )
                    else:
                        self.logger.warning(
                            "Activate no-op pos_id=%s " "(status guard: строка обработана другим воркером)",
                            pos_id,
                            extra={"position_id": pos_id, "kind": kind},
                        )

                except UniqueViolationError:
                    # Лемматизированный title конфликтует с существующей записью.
                    # Повторяем активацию БЕЗ перезаписи standard_job_title —
                    # оставляем оригинальное LLM-название, оно уникально.
                    self.logger.warning(
                        "UniqueViolationError при активации позиции %s — "
                        "повторяем без перезаписи standard_job_title",
                        pos_id,
                        extra={"position_id": pos_id, "kind": kind},
                    )
                    try:
                        retry_result = await conn.execute(
                            SQL_ACTIVATE,
                            emb_literal,
                            pos_id,
                            updated_at_raw,
                        )
                        if retry_result == "UPDATE 1":
                            processed += 1
                            self.logger.info(
                                "Активирована позиция %s без перезаписи title",
                                pos_id,
                                extra={"position_id": pos_id},
                            )
                        else:
                            self.logger.warning(
                                "Retry activate no-op pos_id=%s",
                                pos_id,
                                extra={"position_id": pos_id},
                            )
                    except Exception:
                        self.logger.exception(
                            "Retry activate failed for pos_id=%s",
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
