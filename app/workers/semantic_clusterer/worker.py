# -*- coding: utf-8 -*-
# app/workers/semantic_clusterer/worker.py
"""
Асинхронная бизнес-логика для Semantic Clusterer воркера.

Пайплайн:
1. Fetch — SELECT активных позиций-листьев с эмбеддингами из catalog_positions.
2. ML Pipeline — UMAP (снижение размерности) + HDBSCAN (кластеризация).
   CPU-bound операции изолируются через asyncio.to_thread.
3. LLM Naming — Gemini генерирует короткое название для каждого кластера.
4. Persist — INSERT GROUP_TITLE + UPDATE parent_id в одной транзакции asyncpg.

Технические заметки:
- Pure asyncpg — без ORM.
- google.genai импортируется лениво (после fork).
- ML-библиотеки (umap, hdbscan) работают строго в потоке.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Callable, Optional

import asyncpg
import numpy as np
from dotenv import load_dotenv

from .logger import get_semantic_clusterer_logger

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────


def _safe_int(env_var: str, default: int) -> int:
    raw = os.getenv(env_var, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


DB_USER: str = os.getenv("DB_USER", "postgres")
DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
DB_HOST: str = os.getenv("DB_HOST", "localhost")
DB_PORT: int = _safe_int("DB_PORT", 5432)
DB_NAME: str = os.getenv("DB_NAME", "tendersdb")

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL: str = os.getenv("SEMANTIC_CLUSTERER_LLM_MODEL", "gemini-2.5-flash")

POOL_MIN_SIZE: int = _safe_int("SEMANTIC_CLUSTERER_POOL_MIN", 2)
POOL_MAX_SIZE: int = _safe_int("SEMANTIC_CLUSTERER_POOL_MAX", 5)

UMAP_N_COMPONENTS: int = _safe_int("SEMANTIC_CLUSTERER_UMAP_COMPONENTS", 15)
HDBSCAN_MIN_CLUSTER_SIZE: int = _safe_int("SEMANTIC_CLUSTERER_HDBSCAN_MIN_SIZE", 5)
LLM_TOP_K: int = _safe_int("SEMANTIC_CLUSTERER_LLM_TOP_K", 10)

# ──────────────────────────────────────────────────────────────────────
# SQL
# ──────────────────────────────────────────────────────────────────────

SQL_FETCH_POSITIONS = """
    SELECT id, standard_job_title, embedding::text
    FROM catalog_positions
    WHERE status = 'active'
      AND kind = 'POSITION'
      AND parent_id IS NULL
      AND embedding IS NOT NULL
"""

SQL_INSERT_GROUP = """
    INSERT INTO catalog_positions (standard_job_title, kind, status, updated_at)
    VALUES ($1, 'GROUP_TITLE', 'pending_indexing', NOW())
    RETURNING id
"""

SQL_UPDATE_PARENT = """
    UPDATE catalog_positions
    SET parent_id = $1, updated_at = NOW()
    WHERE id = ANY($2::bigint[])
      AND parent_id IS NULL
"""


# ──────────────────────────────────────────────────────────────────────
# Worker
# ──────────────────────────────────────────────────────────────────────


class SemanticClustererWorker:
    """Семантическая кластеризация позиций каталога."""

    def __init__(self) -> None:
        self.logger = get_semantic_clusterer_logger("semantic_clusterer.worker")
        self._pool: asyncpg.Pool | None = None
        self._genai_client: Any = None
        self.is_initialized: bool = False

    async def initialize(self) -> None:
        """Создаёт пул asyncpg."""
        self.logger.info("Инициализация Semantic Clusterer Worker...")
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
        self.is_initialized = True
        self.logger.info("Semantic Clusterer Worker инициализирован.")

    async def shutdown(self) -> None:
        """Закрывает пул подключений и genai-клиент."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        if self._genai_client is not None:
            try:
                self._genai_client.close()
            except Exception:
                self.logger.debug("Ignored error closing genai client", exc_info=True)
            self._genai_client = None
        self.is_initialized = False

    # ── Gemini client (ленивая инициализация после fork) ──────────────

    def _get_genai_client(self):
        if self._genai_client is None:
            import httpx as httpx_lib  # noqa: E402  # импорт после fork!
            from google import genai  # noqa: E402
            from google.genai import types  # noqa: E402

            self._genai_client = genai.Client(
                api_key=GOOGLE_API_KEY,
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
        return self._genai_client

    # ── Основной пайплайн ─────────────────────────────────────────────

    async def run_clustering(
        self,
        task_id: str,
        bump_ttl_fn: Optional[Callable[[str], None]] = None,
    ) -> int:
        """
        Выполняет полный пайплайн кластеризации.

        Returns:
            Количество найденных кластеров.

        Raises:
            RuntimeError: Если воркер не инициализирован (initialize() не вызван).
        """
        if not self.is_initialized or self._pool is None:
            raise RuntimeError("SemanticClustererWorker not initialized — call initialize() first")

        # Phase 1: Fetch
        self.logger.info("Task %s: Phase 1 — Fetch positions", task_id)
        rows = await self._fetch_positions()
        if not rows:
            self.logger.info("Task %s: No positions with embeddings found, skipping.", task_id)
            return 0

        self.logger.info("Task %s: Fetched %d positions", task_id, len(rows))
        if bump_ttl_fn:
            bump_ttl_fn(task_id)

        # Phase 2: ML pipeline (CPU-bound → to_thread)
        self.logger.info("Task %s: Phase 2 — UMAP + HDBSCAN", task_id)
        ids = [r["id"] for r in rows]
        titles = [r["standard_job_title"] for r in rows]
        embeddings = np.array([json.loads(r["embedding"]) for r in rows], dtype=np.float32)

        clusters = await asyncio.to_thread(self._run_ml_pipeline, embeddings)

        if not clusters:
            self.logger.info("Task %s: No clusters found by HDBSCAN.", task_id)
            return 0

        self.logger.info("Task %s: HDBSCAN found %d clusters", task_id, len(clusters))
        if bump_ttl_fn:
            bump_ttl_fn(task_id)

        # Phase 3: LLM naming
        self.logger.info("Task %s: Phase 3 — LLM naming", task_id)
        cluster_data: list[dict[str, Any]] = []
        for label, member_indices in clusters.items():
            member_ids = [ids[i] for i in member_indices]
            member_titles = [titles[i] for i in member_indices]

            top_titles = member_titles[:LLM_TOP_K]
            name = await self._get_cluster_name(top_titles)
            cluster_data.append({"name": name, "member_ids": member_ids})
            self.logger.info(
                "Task %s: Cluster %d → '%s' (%d members)",
                task_id,
                label,
                name,
                len(member_ids),
            )

        if bump_ttl_fn:
            bump_ttl_fn(task_id)

        # Phase 4: Persist
        self.logger.info("Task %s: Phase 4 — Persist to DB", task_id)
        await self._persist_clusters(cluster_data)
        self.logger.info("Task %s: Clusters persisted successfully.", task_id)

        return len(cluster_data)

    # ── Phase 1: Fetch ────────────────────────────────────────────────

    async def _fetch_positions(self) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(SQL_FETCH_POSITIONS)

    # ── Phase 2: ML Pipeline (синхронный, запускается в потоке) ───────

    def _run_ml_pipeline(self, embeddings: np.ndarray) -> dict[int, list[int]]:
        """UMAP + HDBSCAN. Возвращает {label: [indices]}. Выбросы (-1) отброшены."""
        import hdbscan
        import umap

        if len(embeddings) < HDBSCAN_MIN_CLUSTER_SIZE:
            self.logger.warning(
                "Too few positions (%d) for clustering (min_cluster_size=%d)",
                len(embeddings),
                HDBSCAN_MIN_CLUSTER_SIZE,
            )
            return {}

        n_components = max(1, min(UMAP_N_COMPONENTS, len(embeddings) - 1))

        reducer = umap.UMAP(
            n_components=n_components,
            metric="cosine",
            random_state=42,
        )
        reduced = reducer.fit_transform(embeddings)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
            metric="euclidean",
            cluster_selection_method="eom",
        )
        clusterer.fit(reduced)

        labels = clusterer.labels_
        probabilities = clusterer.probabilities_

        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(labels):
            if label == -1:
                continue
            clusters.setdefault(label, []).append(idx)

        # Сортируем членов каждого кластера по probabilities_ (desc)
        for label in clusters:
            clusters[label].sort(key=lambda i: probabilities[i], reverse=True)

        return clusters

    # ── Phase 3: LLM Naming ───────────────────────────────────────────

    async def _get_cluster_name(self, titles: list[str]) -> str:
        """Запрашивает у Gemini короткое название кластера."""
        fallback = "Авто-группа"
        if not GOOGLE_API_KEY:
            self.logger.warning("GOOGLE_API_KEY not set, using fallback name.")
            return fallback

        titles_text = "\n".join(f"- {t}" for t in titles)
        prompt = (
            "Проанализируй эти строительные работы. "
            "Придумай общее короткое название (2-5 слов) для категории в каталоге. "
            "Верни только название с заглавной буквы без кавычек.\n\n"
            f"{titles_text}"
        )

        try:
            client = self._get_genai_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=LLM_MODEL,
                contents=prompt,
            )
            name = response.text.strip().strip('"').strip("'")
            if name:
                return name
            self.logger.warning("Empty LLM response, using fallback.")
            return fallback
        except Exception:
            self.logger.warning("LLM naming failed, using fallback.", exc_info=True)
            return fallback

    # ── Phase 4: Persist ──────────────────────────────────────────────

    async def _persist_clusters(self, cluster_data: list[dict[str, Any]]) -> None:
        """INSERT группы + UPDATE parent_id в одной транзакции."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for cluster in cluster_data:
                    group_id = await conn.fetchval(SQL_INSERT_GROUP, cluster["name"])
                    await conn.execute(SQL_UPDATE_PARENT, group_id, cluster["member_ids"])
