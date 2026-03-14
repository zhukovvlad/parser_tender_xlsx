# -*- coding: utf-8 -*-
# app/workers/semantic_clusterer/worker.py
"""
Семантическая кластеризация позиций каталога (UMAP + HDBSCAN + Gemini LLM).

Пайплайн (SemanticClustererWorker.run_clustering):
    1. Fetch   — читает активные POSITION-записи без parent_id через серверный
                 курсор asyncpg; embeddings декодируются бинарным кодеком pgvector
                 прямо в np.ndarray, без json.loads.
    2. ML      — UMAP снижает размерность эмбеддингов, HDBSCAN находит кластеры.
                 CPU-bound, выполняется в asyncio.to_thread, не блокирует event loop.
                 Параметры (n_components, n_neighbors) статичны — не урезаются под
                 размер батча; вместо этого min_required обеспечивает достаточный
                 запас данных для стабильной работы spectral layout.
    3. Naming  — для каждого кластера Gemini генерирует короткое название (2-5 слов)
                 через Structured Output (response_schema=ClusterNameResponse),
                 что исключает chain-of-thought и парсинг "напильником".
                 При коллизии с уже существующим названием — re-prompt с подсказкой
                 (до MAX_NAME_RETRIES попыток).
    4. Persist — INSERT GROUP_TITLE (ON CONFLICT DO NOTHING) + UPDATE parent_id
                 в одной транзакции asyncpg. Частичные сбои кластера логируются,
                 но не роняют всю транзакцию.

Архитектурные ограничения:
    - Pure asyncpg, без ORM.
    - google.genai и umap/hdbscan импортируются лениво (после fork Celery),
      чтобы не получить мёртвые сокеты в дочерних процессах.
    - Pydantic (ClusterNameResponse) fork-safe — определяется на уровне модуля.
    - Гиперпараметры задаются через payload POST /clusterize или env-переменные
      SEMANTIC_CLUSTERER_UMAP_COMPONENTS, SEMANTIC_CLUSTERER_UMAP_NEIGHBORS,
      SEMANTIC_CLUSTERER_HDBSCAN_MIN_SIZE, SEMANTIC_CLUSTERER_LLM_TOP_K.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable, Optional

import asyncpg
import numpy as np
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .logger import get_semantic_clusterer_logger

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────


# Pydantic fork-safe: определяем один раз на уровне модуля.
# google.genai — НЕ здесь, импортируется лениво после fork Celery.
class ClusterNameResponse(BaseModel):
    cluster_name: str = Field(description="Короткое название категории (2-5 слов) с заглавной буквы")


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
UMAP_N_NEIGHBORS: int = _safe_int("SEMANTIC_CLUSTERER_UMAP_NEIGHBORS", 15)
HDBSCAN_MIN_CLUSTER_SIZE: int = _safe_int("SEMANTIC_CLUSTERER_HDBSCAN_MIN_SIZE", 5)
LLM_TOP_K: int = _safe_int("SEMANTIC_CLUSTERER_LLM_TOP_K", 10)

# ──────────────────────────────────────────────────────────────────────
# SQL
# ──────────────────────────────────────────────────────────────────────

SQL_FETCH_POSITIONS = """
    SELECT id, standard_job_title, embedding
    FROM catalog_positions
    WHERE status = 'active'
      AND kind = 'POSITION'
      AND parent_id IS NULL
      AND embedding IS NOT NULL
    ORDER BY id
"""

SQL_INSERT_GROUP = """
    WITH inserted AS (
        INSERT INTO catalog_positions (standard_job_title, description, kind, status, updated_at)
        VALUES ($1, $1, 'GROUP_TITLE', 'pending_indexing', NOW())
        ON CONFLICT (standard_job_title, (COALESCE(unit_id, -1::bigint))) DO NOTHING
        RETURNING id
    )
    SELECT id FROM inserted
    UNION ALL
    SELECT id FROM catalog_positions
    WHERE standard_job_title = $1
      AND COALESCE(unit_id, -1) = -1
      AND kind = 'GROUP_TITLE'
    LIMIT 1;
"""

SQL_UPDATE_PARENT = """
    UPDATE catalog_positions
    SET parent_id = $1, updated_at = NOW()
    WHERE id = ANY($2::bigint[])
      AND parent_id IS NULL
    RETURNING id
"""

SQL_FETCH_EXISTING_TITLES = """
    SELECT DISTINCT standard_job_title
    FROM catalog_positions
    WHERE COALESCE(unit_id, -1) = -1
      AND status IN ('active', 'pending_indexing')
"""

MAX_NAME_RETRIES: int = 3

# Минимальные значения параметров (по документации UMAP 0.5 / HDBSCAN 0.8)
_PARAM_BOUNDS: dict[str, int] = {
    "min_cluster_size": 2,
    "umap_components": 1,
    "umap_neighbors": 2,
    "llm_top_k": 1,
}


def _validated(name: str, value: int) -> int:
    """Проверяет параметр кластеризации на минимально допустимое значение."""
    min_val = _PARAM_BOUNDS[name]
    if value < min_val:
        raise ValueError(f"{name} must be >= {min_val}, got {value}")
    return value


# ──────────────────────────────────────────────────────────────────────
# Worker
# ──────────────────────────────────────────────────────────────────────


class SemanticClustererWorker:
    """Семантическая кластеризация позиций каталога."""

    def __init__(self, params: dict | None = None) -> None:
        self.logger = get_semantic_clusterer_logger("semantic_clusterer.worker")
        self._pool: asyncpg.Pool | None = None
        self._genai_client: Any = None
        self.is_initialized: bool = False
        self.params = params or {}
        _p = self.params
        self.min_cluster_size: int = _validated("min_cluster_size", _p["min_cluster_size"] if _p.get("min_cluster_size") is not None else HDBSCAN_MIN_CLUSTER_SIZE)
        self.umap_components: int = _validated("umap_components", _p["umap_components"] if _p.get("umap_components") is not None else UMAP_N_COMPONENTS)
        self.umap_neighbors: int = _validated("umap_neighbors", _p["umap_neighbors"] if _p.get("umap_neighbors") is not None else UMAP_N_NEIGHBORS)
        self.llm_top_k: int = _validated("llm_top_k", _p["llm_top_k"] if _p.get("llm_top_k") is not None else LLM_TOP_K)
        self.logger.info(
            "Параметры кластеризации: min_cluster_size=%d, umap_components=%d, umap_neighbors=%d, llm_top_k=%d "
            "(raw payload: %s)",
            self.min_cluster_size,
            self.umap_components,
            self.umap_neighbors,
            self.llm_top_k,
            self.params if self.params else "пусто — используются env-var дефолты",
        )

    async def initialize(self) -> None:
        """Создаёт пул asyncpg."""
        self.logger.info("Инициализация Semantic Clusterer Worker...")

        # Функция, которая будет вызвана один раз для каждого нового соединения в пуле
        async def init_conn(conn):
            from pgvector.asyncpg import register_vector

            await register_vector(conn)

        self._pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            command_timeout=60,
            init=init_conn,
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

        ids, titles, embeddings = await self._fetch_positions()
        if not ids:
            self.logger.info("Task %s: No positions with embeddings found, skipping.", task_id)
            return 0

        self.logger.info("Task %s: Fetched %d positions", task_id, len(ids))
        if bump_ttl_fn:
            bump_ttl_fn(task_id)

        # Phase 2: ML pipeline (CPU-bound → to_thread)
        self.logger.info("Task %s: Phase 2 — UMAP + HDBSCAN", task_id)

        clusters = await asyncio.to_thread(self._run_ml_pipeline, task_id, embeddings)

        if not clusters:
            self.logger.info("Task %s: No clusters found by HDBSCAN.", task_id)
            return 0

        self.logger.info("Task %s: HDBSCAN found %d clusters", task_id, len(clusters))
        if bump_ttl_fn:
            bump_ttl_fn(task_id)

        # Phase 3: LLM naming (with duplicate-name detection & re-prompt)
        self.logger.info("Task %s: Phase 3 — LLM naming", task_id)
        existing_names = await self._fetch_existing_titles()
        used_names: set[str] = set()

        cluster_data: list[dict[str, Any]] = []
        for label, member_indices in clusters.items():
            member_ids = [ids[i] for i in member_indices]
            member_titles = [titles[i] for i in member_indices]

            top_titles = member_titles[: self.llm_top_k]
            name = await self._get_unique_cluster_name(top_titles, existing_names, used_names)
            used_names.add(name.lower())
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
        await self._persist_clusters(task_id, cluster_data)
        self.logger.info("Task %s: Clusters persisted successfully.", task_id)

        return len(cluster_data)

    # ── Phase 1: Fetch ────────────────────────────────────────────────

    async def _fetch_positions(self) -> tuple[list[int], list[str], np.ndarray]:
        """
        Читает позиции через серверный курсор и бинарный парсинг pgvector.
        Возвращает (ids, titles, embeddings).
        """
        ids: list[int] = []
        titles: list[str] = []
        embeddings_list: list[np.ndarray] = []

        async with self._pool.acquire() as conn:
            # Серверные курсоры в PostgreSQL существуют только внутри транзакций
            async with conn.transaction():
                # cursor() не вытягивает всю таблицу в память, а читает батчами (по умолчанию по 50 записей)
                async for record in conn.cursor(SQL_FETCH_POSITIONS):
                    ids.append(record["id"])
                    titles.append(record["standard_job_title"])
                    embeddings_list.append(record["embedding"])

        if not ids:
            return [], [], np.array([], dtype=np.float32)

        # Собираем список одномерных массивов в один 2D-массив (матрицу)
        # Это эффективнее, чем конкатенация в цикле
        embeddings_matrix = np.stack(embeddings_list)

        return ids, titles, embeddings_matrix

    # ── Phase 2: ML Pipeline (синхронный, запускается в потоке) ───────

    def _run_ml_pipeline(self, task_id: str, embeddings: np.ndarray) -> dict[int, list[int]]:
        """UMAP + HDBSCAN. Возвращает {label: [indices]}. Выбросы (-1) отброшены."""
        import hdbscan
        import umap

        # Запас +5 для n_components и +2 для n_neighbors гарантирует,
        # что UMAP spectral layout (eigsh(k=n_components+1)) не упадёт
        # без изменения целевой размерности на лету.
        min_required = max(self.umap_components + 5, self.umap_neighbors + 2)
        if len(embeddings) < min_required:
            self.logger.warning(
                "Task %s: Недостаточно данных для кластеризации (%d < %d). Пропускаем.",
                task_id,
                len(embeddings),
                min_required,
            )
            return {}

        reducer = umap.UMAP(
            n_components=self.umap_components,
            n_neighbors=self.umap_neighbors,
            metric="cosine",
            random_state=42,
        )
        reduced = reducer.fit_transform(embeddings)

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size,
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

    async def _fetch_existing_titles(self) -> set[str]:
        """Загружает все существующие standard_job_title из catalog_positions."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(SQL_FETCH_EXISTING_TITLES)
        return {r["standard_job_title"].lower() for r in rows if r["standard_job_title"]}

    async def _get_unique_cluster_name(
        self,
        titles: list[str],
        existing_names: set[str],
        used_names: set[str],
    ) -> str:
        """Получает уникальное название кластера, при конфликте re-prompt Gemini."""
        rejected: list[str] = []
        for attempt in range(MAX_NAME_RETRIES + 1):
            name = await self._get_cluster_name(titles, rejected_names=rejected or None)
            if name.lower() not in existing_names and name.lower() not in used_names:
                return name
            self.logger.warning(
                "LLM returned duplicate name '%s' (attempt %d/%d), re-prompting",
                name,
                attempt + 1,
                MAX_NAME_RETRIES + 1,
            )
            rejected.append(name)

        # Все попытки исчерпаны — суффикс для уникальности
        base = rejected[-1] if rejected else "Авто-группа"
        fallback = f"{base} (группа)"
        suffix = 2
        while fallback.lower() in existing_names or fallback.lower() in used_names:
            fallback = f"{base} (группа {suffix})"
            suffix += 1
        self.logger.warning("All LLM retries exhausted, using fallback: '%s'", fallback)
        return fallback

    async def _get_cluster_name(
        self,
        titles: list[str],
        rejected_names: list[str] | None = None,
    ) -> str:
        """Запрашивает у Gemini короткое название кластера (Structured Output)."""
        import json

        from google.genai import types  # noqa: E402  # импорт после fork!

        fallback = "Авто-группа"
        if not GOOGLE_API_KEY:
            self.logger.warning("GOOGLE_API_KEY not set, using fallback name.")
            return fallback

        titles_text = "\n".join(f"- {t}" for t in titles)

        exclusion_hint = ""
        if rejected_names:
            excluded = "\n".join(f"- {n}" for n in rejected_names)
            exclusion_hint = (
                f"\n\nВАЖНО: Следующие названия уже заняты, НЕ используй их " f"и придумай другое:\n{excluded}\n"
            )

        prompt = (
            "Проанализируй список позиций/работ из тендера. "
            "Придумай для них общее короткое название категории (2-5 слов) с заглавной буквы.\n\n"
            f"Работы:\n{titles_text}"
            f"{exclusion_hint}"
        )

        try:
            client = self._get_genai_client()

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=LLM_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    response_mime_type="application/json",
                    response_schema=ClusterNameResponse,
                    temperature=0.2,
                ),
            )
            result = json.loads(response.text)
            name = result.get("cluster_name", "").strip()
            if len(name.encode("utf-8")) > 500:
                self.logger.warning(
                    "LLM returned oversized name (%d bytes), using fallback.",
                    len(name.encode("utf-8")),
                )
                return fallback
            return name or fallback
        except Exception:
            self.logger.warning("LLM naming failed, using fallback.", exc_info=True)
            return fallback

    # ── Phase 4: Persist ──────────────────────────────────────────────

    async def _persist_clusters(self, task_id: str, cluster_data: list[dict[str, Any]]) -> None:
        """INSERT группы + UPDATE parent_id в одной транзакции."""
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for cluster in cluster_data:
                    group_id = await conn.fetchval(SQL_INSERT_GROUP, cluster["name"])
                    if group_id is None:
                        self.logger.warning(
                            "Task %s: Пропуск кластера '%s' — имя конфликтует с существующей позицией",
                            task_id,
                            cluster["name"],
                        )
                        continue
                    updated = await conn.fetch(SQL_UPDATE_PARENT, group_id, cluster["member_ids"])
                    if len(updated) != len(cluster["member_ids"]):
                        # Не падаем, а логируем дельту! Мы спасаем остальные данные.
                        self.logger.warning(
                            "Task %s: Кластер '%s' (ID %d) сохранен частично. Ожидалось %d позиций, обновлено %d "
                            "(возможно, позиции были изменены конкурентно).",
                            task_id,
                            cluster["name"],
                            group_id,
                            len(cluster["member_ids"]),
                            len(updated),
                        )
