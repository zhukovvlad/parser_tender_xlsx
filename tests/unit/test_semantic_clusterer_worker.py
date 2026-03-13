# -*- coding: utf-8 -*-
"""
Unit-тесты для app/workers/semantic_clusterer/worker.py

Покрывает секцию 3.10 TESTING_CHECKLIST.md:
  3.10.1 Конфигурация
  3.10.2 _run_ml_pipeline()
  3.10.3 _get_cluster_name()
  3.10.4 _persist_clusters()
  3.10.5 _fetch_positions()
  3.10.6 Жизненный цикл
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Async helper — работает без pytest-asyncio
# ---------------------------------------------------------------------------


def run_sync(coro):
    """Запускает корутину в новом event loop (изоляция между тестами)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker(params=None):
    from app.workers.semantic_clusterer.worker import SemanticClustererWorker
    return SemanticClustererWorker(params=params)


def _make_initialized_worker(params=None):
    worker = _make_worker(params)
    worker._pool = MagicMock()
    worker.is_initialized = True
    return worker


def _random_embeddings(n, dim=32, seed=0):
    rng = np.random.default_rng(seed)
    return rng.standard_normal((n, dim)).astype(np.float32)


# ===========================================================================
# 3.10.1 Конфигурация
# ===========================================================================


class TestSafeInt:
    """Given: функция _safe_int в модуле worker."""

    def test_valid_integer_returns_value(self):
        """When: int-строка → Then: возвращается int."""
        from app.workers.semantic_clusterer.worker import _safe_int
        with patch.dict("os.environ", {"MY_VAR": "42"}):
            assert _safe_int("MY_VAR", 10) == 42

    def test_empty_string_returns_default(self):
        """When: пустая строка → Then: default."""
        from app.workers.semantic_clusterer.worker import _safe_int
        with patch.dict("os.environ", {"MY_VAR": ""}):
            assert _safe_int("MY_VAR", 7) == 7

    def test_invalid_string_returns_default(self):
        """When: не-число → Then: default."""
        from app.workers.semantic_clusterer.worker import _safe_int
        with patch.dict("os.environ", {"MY_VAR": "abc"}):
            assert _safe_int("MY_VAR", 5) == 5

    def test_missing_env_var_returns_default(self):
        """When: переменная отсутствует → Then: default."""
        import os
        from app.workers.semantic_clusterer.worker import _safe_int
        os.environ.pop("ABSENT_VAR_XYZ", None)
        assert _safe_int("ABSENT_VAR_XYZ", 99) == 99

    def test_float_string_returns_default(self):
        """When: float-строка → Then: default (int() не принимает '3.14')."""
        from app.workers.semantic_clusterer.worker import _safe_int
        with patch.dict("os.environ", {"MY_VAR": "3.14"}):
            assert _safe_int("MY_VAR", 0) == 0


class TestParamsOverride:
    """Given: SemanticClustererWorker создаётся с payload params."""

    def test_params_override_env_defaults(self):
        """When: params содержат все 4 ключа → Then: перекрывают defaults."""
        w = _make_worker({"min_cluster_size": 3, "umap_components": 8, "umap_neighbors": 10, "llm_top_k": 15})
        assert w.min_cluster_size == 3
        assert w.umap_components == 8
        assert w.umap_neighbors == 10
        assert w.llm_top_k == 15

    def test_none_params_uses_module_defaults(self):
        """When: params=None → Then: используются module-level constants."""
        from app.workers.semantic_clusterer.worker import (
            HDBSCAN_MIN_CLUSTER_SIZE, LLM_TOP_K,
            UMAP_N_COMPONENTS, UMAP_N_NEIGHBORS,
        )
        w = _make_worker(None)
        assert w.min_cluster_size == HDBSCAN_MIN_CLUSTER_SIZE
        assert w.umap_components == UMAP_N_COMPONENTS
        assert w.umap_neighbors == UMAP_N_NEIGHBORS
        assert w.llm_top_k == LLM_TOP_K

    def test_partial_params_keeps_defaults_for_missing(self):
        """When: только один ключ в params → Then: остальные из env-defaults."""
        from app.workers.semantic_clusterer.worker import UMAP_N_COMPONENTS
        w = _make_worker({"min_cluster_size": 2})
        assert w.min_cluster_size == 2
        assert w.umap_components == UMAP_N_COMPONENTS


class TestHyperparamLogging:
    """Given: __init__ воркера логирует гиперпараметры."""

    def test_init_logs_all_four_hyperparams(self):
        """When: создаём воркер с явными params → Then: logger.info вызван с 4 значениями."""
        from app.workers.semantic_clusterer import worker as wm

        mock_logger = MagicMock()
        with patch.object(wm, "get_semantic_clusterer_logger", return_value=mock_logger):
            _make_worker({"min_cluster_size": 7, "umap_components": 9, "umap_neighbors": 11, "llm_top_k": 6})

        # Собираем все аргументы из вызовов logger.info
        all_info_args = " ".join(
            str(a)
            for call in mock_logger.info.call_args_list
            for a in call[0]
        )
        for val in ("7", "9", "11", "6"):
            assert val in all_info_args, f"Значение {val} не найдено в logger.info вызовах"


# ===========================================================================
# 3.10.2 _run_ml_pipeline()
# ===========================================================================


class TestRunMlPipeline:
    """Given: _run_ml_pipeline вызывается без реального пула."""

    def _worker(self, **kw):
        defaults = {"min_cluster_size": 2, "umap_components": 5, "umap_neighbors": 5}
        defaults.update(kw)
        return _make_worker(defaults)

    def _mock_umap_hdbscan(self, n, labels, probs=None):
        """Возвращает контекстные патчи UMAP и HDBSCAN."""
        if probs is None:
            probs = np.ones(n)
        mock_c = MagicMock()
        mock_c.labels_ = np.array(labels)
        mock_c.probabilities_ = np.array(probs)
        return mock_c

    def test_happy_path_returns_cluster_dict_without_outlier_key(self):
        """When: 40 embeddings, 2 кластера → Then: dict без ключа -1."""
        w = self._worker()
        emb = _random_embeddings(40, dim=16)
        mock_c = self._mock_umap_hdbscan(40, [0]*20 + [1]*20)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            MockUMAP.return_value.fit_transform.return_value = np.zeros((40, 5))
            MockHDBSCAN.return_value = mock_c
            result = w._run_ml_pipeline("t1", emb)

        assert -1 not in result
        assert set(result.keys()) == {0, 1}

    def test_outliers_excluded_from_clusters(self):
        """When: первые 5 меток = -1 → Then: их индексы не входят в кластеры."""
        w = self._worker()
        emb = _random_embeddings(20, dim=8)
        mock_c = self._mock_umap_hdbscan(20, [-1]*5 + [0]*10 + [1]*5)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            MockUMAP.return_value.fit_transform.return_value = np.zeros((20, 5))
            MockHDBSCAN.return_value = mock_c
            result = w._run_ml_pipeline("t2", emb)

        all_indices = {i for idxs in result.values() for i in idxs}
        assert all_indices.isdisjoint({0, 1, 2, 3, 4})

    def test_all_outliers_returns_empty_dict(self):
        """When: все метки = -1 → Then: {}."""
        w = self._worker()
        emb = _random_embeddings(20, dim=8)
        mock_c = self._mock_umap_hdbscan(20, [-1]*20)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            MockUMAP.return_value.fit_transform.return_value = np.zeros((20, 5))
            MockHDBSCAN.return_value = mock_c
            result = w._run_ml_pipeline("t3", emb)

        assert result == {}

    def test_insufficient_data_returns_empty_dict_without_calling_umap(self):
        """When: len < min_required → Then: {} и UMAP не вызывается."""
        # min_required = max(5+5, 5+2) = 10; передаём 5
        w = self._worker(umap_components=5, umap_neighbors=5)
        emb = _random_embeddings(5, dim=8)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            result = w._run_ml_pipeline("t_few", emb)

        MockUMAP.assert_not_called()
        MockHDBSCAN.assert_not_called()
        assert result == {}

    def test_insufficient_data_logs_warning_with_task_id(self):
        """When: мало данных → Then: warning.logger вызывается с task_id."""
        from unittest.mock import patch as mpatch
        w = self._worker(umap_components=5, umap_neighbors=5)
        emb = _random_embeddings(3, dim=8)

        with mpatch.object(w.logger, "warning") as mock_warn:
            with patch("umap.UMAP"), patch("hdbscan.HDBSCAN"):
                w._run_ml_pipeline("task_warn_xyz", emb)

        # Проверяем что warning был вызван и один из аргументов содержит task_id
        assert mock_warn.called
        all_args = " ".join(str(a) for call in mock_warn.call_args_list for a in call[0])
        assert "task_warn_xyz" in all_args

    def test_min_required_formula_n_components_dominates(self):
        """When: umap_components=10, umap_neighbors=5 → min_required=max(15,7)=15; 14 точек → {}."""
        w = self._worker(umap_components=10, umap_neighbors=5)
        emb = _random_embeddings(14, dim=8)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN"):
            result = w._run_ml_pipeline("t_min1", emb)

        MockUMAP.assert_not_called()
        assert result == {}

    def test_min_required_formula_n_neighbors_dominates(self):
        """When: umap_neighbors=20, umap_components=5 → min_required=max(10,22)=22; 21 → {}."""
        w = self._worker(umap_components=5, umap_neighbors=20)
        emb = _random_embeddings(21, dim=8)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN"):
            result = w._run_ml_pipeline("t_min2", emb)

        MockUMAP.assert_not_called()
        assert result == {}

    def test_members_sorted_by_probability_desc(self):
        """When: probabilities разные → Then: внутри кластера desc-отсортированы."""
        w = self._worker()
        n = 20
        emb = _random_embeddings(n, dim=8)
        probs = np.array([i / (n - 1) for i in range(n)])  # 0.0…1.0
        mock_c = self._mock_umap_hdbscan(n, [0]*n, probs=probs)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            MockUMAP.return_value.fit_transform.return_value = np.zeros((n, 5))
            MockHDBSCAN.return_value = mock_c
            result = w._run_ml_pipeline("t_sort", emb)

        indices = result[0]
        for a, b in zip(indices, indices[1:]):
            assert probs[a] >= probs[b], "Порядок нарушен"

    def test_umap_called_with_random_state_42(self):
        """When: _run_ml_pipeline → Then: UMAP создаётся с random_state=42."""
        w = self._worker()
        emb = _random_embeddings(20, dim=8)
        mock_c = self._mock_umap_hdbscan(20, [0]*20)

        with patch("umap.UMAP") as MockUMAP, patch("hdbscan.HDBSCAN") as MockHDBSCAN:
            MockUMAP.return_value.fit_transform.return_value = np.zeros((20, 5))
            MockHDBSCAN.return_value = mock_c
            w._run_ml_pipeline("t_rs", emb)

        _, kwargs = MockUMAP.call_args
        assert kwargs.get("random_state") == 42


# ===========================================================================
# 3.10.3 _get_cluster_name()
# ===========================================================================


class TestGetClusterName:
    """Given: _get_cluster_name — единственный источник имени кластера."""

    @pytest.fixture
    def worker(self):
        return _make_initialized_worker()

    def test_happy_path_returns_llm_name(self, worker):
        """When: Gemini возвращает {"cluster_name": "Монтажные работы"} → название."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"cluster_name": "Монтажные работы"})

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", new_callable=AsyncMock) as mt:
                    mt.return_value = mock_response
                    return await worker._get_cluster_name(["Укладка плитки", "Штукатурные работы"])

        name = run_sync(_run())
        assert name == "Монтажные работы"

    def test_empty_cluster_name_returns_fallback(self, worker):
        """When: {"cluster_name": ""} → fallback «Авто-группа»."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({"cluster_name": ""})

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", new_callable=AsyncMock) as mt:
                    mt.return_value = mock_response
                    return await worker._get_cluster_name(["Работа 1"])

        assert run_sync(_run()) == "Авто-группа"

    def test_api_error_returns_fallback(self, worker):
        """When: asyncio.to_thread бросает RuntimeError → fallback «Авто-группа»."""
        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", new_callable=AsyncMock) as mt:
                    mt.side_effect = RuntimeError("API 500")
                    return await worker._get_cluster_name(["Работа 1"])

        assert run_sync(_run()) == "Авто-группа"

    def test_no_api_key_returns_fallback_without_calling_gemini(self, worker):
        """When: GOOGLE_API_KEY пустой → fallback сразу, to_thread не вызывается."""
        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", ""):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread") as mt:
                    name = await worker._get_cluster_name(["Работа 1"])
                    mt.assert_not_called()
                    return name

        assert run_sync(_run()) == "Авто-группа"

    def test_oversized_name_returns_fallback(self, worker):
        """When: имя > 500 байт → fallback «Авто-группа»."""
        long_name = "А" * 600  # каждый символ = 2 байта в UTF-8 → 1200 байт
        mock_response = MagicMock()
        mock_response.text = json.dumps({"cluster_name": long_name})

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", new_callable=AsyncMock) as mt:
                    mt.return_value = mock_response
                    return await worker._get_cluster_name(["Работа 1"])

        assert run_sync(_run()) == "Авто-группа"

    def test_invalid_json_returns_fallback(self, worker):
        """When: response.text не JSON → fallback «Авто-группа»."""
        mock_response = MagicMock()
        mock_response.text = "не JSON вовсе!!!"

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", new_callable=AsyncMock) as mt:
                    mt.return_value = mock_response
                    return await worker._get_cluster_name(["Работа 1"])

        assert run_sync(_run()) == "Авто-группа"

    def test_generate_content_config_has_thinking_budget_zero_and_temperature(self, worker):
        """When: вызов Gemini → Then: thinking_budget=0, temperature=0.2."""
        captured = {}

        def fake_generate(model, contents, config):
            captured["config"] = config
            mock_r = MagicMock()
            mock_r.text = json.dumps({"cluster_name": "Строительство"})
            return mock_r

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = fake_generate
        worker._genai_client = mock_client

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", side_effect=fake_to_thread):
                    return await worker._get_cluster_name(["Работа 1"])

        run_sync(_run())

        cfg = captured.get("config")
        assert cfg is not None, "config не был передан в generate_content"
        assert cfg.thinking_config.thinking_budget == 0
        assert cfg.temperature == 0.2

    def test_response_schema_is_cluster_name_response(self, worker):
        """When: вызов Gemini → Then: response_schema = ClusterNameResponse."""
        from app.workers.semantic_clusterer.worker import ClusterNameResponse

        captured = {}

        def fake_generate(model, contents, config):
            captured["config"] = config
            mock_r = MagicMock()
            mock_r.text = json.dumps({"cluster_name": "Тест"})
            return mock_r

        async def fake_to_thread(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = fake_generate
        worker._genai_client = mock_client

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.GOOGLE_API_KEY", "fake-key"):
                with patch("app.workers.semantic_clusterer.worker.asyncio.to_thread", side_effect=fake_to_thread):
                    return await worker._get_cluster_name(["Работа 1"])

        run_sync(_run())
        assert captured["config"].response_schema is ClusterNameResponse


# ===========================================================================
# 3.10.4 _persist_clusters()
# ===========================================================================


class TestPersistClusters:
    """Given: _persist_clusters с замокированным asyncpg pool."""

    def _mock_conn(self, fetchval_side_effect, fetch_side_effect):
        """Создаёт мок conn с правильным async context manager для transaction()."""
        mock_conn = MagicMock()
        mock_conn.fetchval = AsyncMock(side_effect=fetchval_side_effect)
        mock_conn.fetch = AsyncMock(side_effect=fetch_side_effect)
        # transaction() используется как `async with conn.transaction():` — не awaited!
        # Поэтому transaction должен быть обычным MagicMock, возвращающим async CM.
        async_cm = MagicMock()
        async_cm.__aenter__ = AsyncMock(return_value=async_cm)
        async_cm.__aexit__ = AsyncMock(return_value=False)
        mock_conn.transaction = MagicMock(return_value=async_cm)
        return mock_conn

    def _attach_pool(self, worker, mock_conn):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        worker._pool.acquire.return_value = ctx

    def test_happy_path_calls_fetchval_and_fetch_for_each_cluster(self):
        """When: 2 кластера, group_id возвращается → fetchval и fetch по 2 раза."""
        worker = _make_initialized_worker()
        mock_conn = self._mock_conn(
            fetchval_side_effect=[101, 102],
            fetch_side_effect=[[MagicMock(), MagicMock()], [MagicMock()]],
        )
        self._attach_pool(worker, mock_conn)

        run_sync(worker._persist_clusters("t1", [
            {"name": "A", "member_ids": [1, 2]},
            {"name": "B", "member_ids": [3]},
        ]))

        assert mock_conn.fetchval.call_count == 2
        assert mock_conn.fetch.call_count == 2

    def test_group_id_none_skips_cluster_with_warning(self):
        """When: fetchval → None для первого → continue + warning, второй обрабатывается."""
        worker = _make_initialized_worker()
        mock_conn = self._mock_conn(
            fetchval_side_effect=[None, 200],
            fetch_side_effect=[[MagicMock()]],
        )
        self._attach_pool(worker, mock_conn)

        with patch.object(worker.logger, "warning") as mock_warn:
            run_sync(worker._persist_clusters("t_skip", [
                {"name": "КонфликтИмя", "member_ids": [10]},
                {"name": "Норм", "member_ids": [20]},
            ]))

        # fetch вызван только для второго кластера
        assert mock_conn.fetch.call_count == 1
        all_warn_args = " ".join(str(a) for call in mock_warn.call_args_list for a in call[0])
        assert "КонфликтИмя" in all_warn_args or "конфликт" in all_warn_args.lower() or "Пропуск" in all_warn_args

    def test_partial_update_logs_warning_no_exception(self):
        """When: len(updated) < len(member_ids) → warning, без исключения."""
        worker = _make_initialized_worker()
        # 3 member_ids, но fetch вернул только 1 запись
        mock_conn = self._mock_conn(
            fetchval_side_effect=[50],
            fetch_side_effect=[[MagicMock()]],
        )
        self._attach_pool(worker, mock_conn)

        with patch.object(worker.logger, "warning") as mock_warn:
            run_sync(worker._persist_clusters("t_partial", [{"name": "X", "member_ids": [1, 2, 3]}]))

        # Нет исключения; warning был вызван
        assert mock_warn.called, "Ожидалось предупреждение о частичном обновлении"

    def test_all_operations_in_single_transaction(self):
        """When: 3 кластера → Then: conn.transaction() вызван ровно один раз."""
        worker = _make_initialized_worker()
        mock_conn = self._mock_conn(
            fetchval_side_effect=[1, 2, 3],
            fetch_side_effect=[[MagicMock()], [MagicMock()], [MagicMock()]],
        )
        self._attach_pool(worker, mock_conn)

        run_sync(worker._persist_clusters("t_tx", [
            {"name": "K1", "member_ids": [1]},
            {"name": "K2", "member_ids": [2]},
            {"name": "K3", "member_ids": [3]},
        ]))

        mock_conn.transaction.assert_called_once()

    def test_update_parent_id_called_with_correct_group_id(self):
        """When: fetchval → 77 → Then: fetch вызывается с group_id=77."""
        worker = _make_initialized_worker()
        mock_conn = self._mock_conn(
            fetchval_side_effect=[77],
            fetch_side_effect=[[MagicMock(), MagicMock()]],
        )
        self._attach_pool(worker, mock_conn)

        run_sync(worker._persist_clusters("t_gid", [{"name": "G", "member_ids": [5, 6]}]))

        fetch_args = mock_conn.fetch.call_args[0]
        assert fetch_args[1] == 77  # первый позиционный аргумент = group_id


# ===========================================================================
# 3.10.5 _fetch_positions()
# ===========================================================================


class TestFetchPositions:
    """Given: _fetch_positions с замокированным asyncpg pool."""

    def _attach_cursor(self, worker, records):
        """Мокирует pool для возврата заданных записей через async cursor."""

        async def fake_cursor(query):
            for r in records:
                yield r

        class FakeTx:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass

        mock_conn = MagicMock()
        mock_conn.cursor = fake_cursor
        mock_conn.transaction.return_value = FakeTx()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        worker._pool.acquire.return_value = ctx

    def test_returns_correct_types(self):
        """When: 3 записи → Then: tuple[list[int], list[str], np.ndarray[shape=(3,2)]]."""
        worker = _make_initialized_worker()
        vecs = [np.array([0.1, 0.2], dtype=np.float32) for _ in range(3)]
        records = [{"id": i + 1, "standard_job_title": f"Работа {i+1}", "embedding": vecs[i]} for i in range(3)]
        self._attach_cursor(worker, records)

        ids, titles, emb = run_sync(worker._fetch_positions())

        assert isinstance(ids, list)
        assert all(isinstance(x, int) for x in ids)
        assert isinstance(titles, list)
        assert all(isinstance(t, str) for t in titles)
        assert isinstance(emb, np.ndarray)
        assert emb.shape == (3, 2)

    def test_empty_result_returns_empty_structures(self):
        """When: нет записей → Then: ([], [], np.array([])) с size=0."""
        worker = _make_initialized_worker()
        self._attach_cursor(worker, [])

        ids, titles, emb = run_sync(worker._fetch_positions())

        assert ids == []
        assert titles == []
        assert emb.size == 0

    def test_np_stack_builds_2d_matrix(self):
        """When: N записей с dim=4 → Then: emb.shape == (N, 4)."""
        n, dim = 5, 4
        worker = _make_initialized_worker()
        vecs = [np.random.rand(dim).astype(np.float32) for _ in range(n)]
        records = [{"id": i, "standard_job_title": f"T{i}", "embedding": vecs[i]} for i in range(n)]
        self._attach_cursor(worker, records)

        _, _, emb = run_sync(worker._fetch_positions())
        assert emb.shape == (n, dim)

    def test_cursor_used_inside_transaction(self):
        """When: _fetch_positions → Then: cursor вызывается между __aenter__ и __aexit__ транзакции."""
        worker = _make_initialized_worker()
        call_order = []

        async def fake_cursor(query):
            call_order.append("cursor")
            return
            yield  # make async generator

        class FakeTx:
            async def __aenter__(self):
                call_order.append("tx_enter")
                return self

            async def __aexit__(self, *_):
                call_order.append("tx_exit")

        mock_conn = MagicMock()
        mock_conn.cursor = fake_cursor
        mock_conn.transaction.return_value = FakeTx()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        worker._pool.acquire.return_value = ctx

        run_sync(worker._fetch_positions())

        assert call_order.index("tx_enter") < call_order.index("cursor") < call_order.index("tx_exit")


# ===========================================================================
# 3.10.6 Жизненный цикл
# ===========================================================================


class TestLifecycle:
    """Given: SemanticClustererWorker lifecycle методы."""

    def test_initialize_sets_is_initialized_and_pool(self):
        """When: initialize() → Then: is_initialized=True, _pool is not None."""
        worker = _make_worker()
        mock_pool = MagicMock()

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.asyncpg.create_pool", new_callable=AsyncMock) as mc:
                mc.return_value = mock_pool
                await worker.initialize()

        run_sync(_run())

        assert worker.is_initialized is True
        assert worker._pool is mock_pool

    def test_initialize_passes_init_callable_to_create_pool(self):
        """When: initialize() → Then: create_pool вызывается с callable init."""
        worker = _make_worker()

        async def _run():
            with patch("app.workers.semantic_clusterer.worker.asyncpg.create_pool", new_callable=AsyncMock) as mc:
                mc.return_value = MagicMock()
                await worker.initialize()
                _, kwargs = mc.call_args
                return kwargs

        kwargs = run_sync(_run())
        assert "init" in kwargs
        assert callable(kwargs["init"])

    def test_shutdown_closes_pool_resets_flags(self):
        """When: shutdown() → Then: pool.close() awaited, flags reset."""
        worker = _make_initialized_worker()
        mock_pool = AsyncMock()
        worker._pool = mock_pool

        run_sync(worker.shutdown())

        mock_pool.close.assert_awaited_once()
        assert worker.is_initialized is False
        assert worker._pool is None

    def test_shutdown_closes_genai_client(self):
        """When: shutdown() с genai client → Then: close() вызван, _genai_client=None."""
        worker = _make_initialized_worker()
        worker._pool = AsyncMock()
        mock_client = MagicMock()
        worker._genai_client = mock_client

        run_sync(worker.shutdown())

        mock_client.close.assert_called_once()
        assert worker._genai_client is None

    def test_shutdown_ignores_genai_close_exception(self):
        """When: genai.close() бросает → Then: завершается без raise."""
        worker = _make_initialized_worker()
        worker._pool = AsyncMock()
        mock_client = MagicMock()
        mock_client.close.side_effect = RuntimeError("already closed")
        worker._genai_client = mock_client

        run_sync(worker.shutdown())  # не должно бросить

        assert worker._genai_client is None

    def test_get_genai_client_caches_instance(self):
        """When: _get_genai_client() вызван дважды → Then: второй раз клиент не пересоздаётся."""
        worker = _make_initialized_worker()
        mock_client = MagicMock()
        # Предзаполним кэш — симулируем первый lazy вызов
        worker._genai_client = mock_client

        result = worker._get_genai_client()
        assert result is mock_client

    def test_google_genai_not_imported_at_module_level(self):
        """When: парсим AST worker.py → Then: google.genai не в top-level импортах."""
        import ast
        import pathlib

        path = pathlib.Path(__file__).parent.parent.parent / "app" / "workers" / "semantic_clusterer" / "worker.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        top_level_modules = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                top_level_modules.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top_level_modules.append(alias.name)

        assert "google.genai" not in top_level_modules, (
            "google.genai не должен быть в top-level импортах (fork-safety)"
        )

    def test_run_clustering_raises_runtime_error_if_not_initialized(self):
        """When: run_clustering без initialize() → Then: RuntimeError с 'not initialized'."""
        worker = _make_worker()

        async def _run():
            await worker.run_clustering("task_x")

        with pytest.raises(RuntimeError, match="not initialized"):
            run_sync(_run())
