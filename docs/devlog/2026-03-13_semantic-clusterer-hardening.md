# 2026-03-13 — Hardening: Semantic Clusterer (Phase 2)

## Контекст

Продолжение работы над `app/workers/semantic_clusterer/worker.py`.
После первого запуска (2026-03-12) выявлены производственные дефекты:
`ProgramLimitExceededError` из-за цепочек рассуждений Gemini,
зависание индексера от конкурентной коллизии `GROUP_TITLE`,
падение UMAP на малых датасетах. Параллельно — рефактор фетчинга
и параметризация гиперпараметров.

---

## 1. Gemini chain-of-thought → Structured Output

**Проблема:** Gemini 2.5 Flash включал цепочки рассуждений (`THOUGHT:`, `ТИХО:`)
прямо в `response.text`. Названия кластеров вырастали до тысяч символов и роняли
INSERT с `ProgramLimitExceededError` (btree-индекс: max 2704 байт).

**Фикс 1 (временный):** `thinking_budget=0` + парсинг последней строки (`lines[-1]`).

**Фикс 2 (финальный):** Structured Output через `response_schema=ClusterNameResponse`.
SDK передаёт Pydantic-модель как JSON Schema; модель возвращает строго
`{"cluster_name": "..."}` без лишнего текста. `splitlines()` хак удалён.
Добавлен `temperature=0.2` для более предметных имён.

```python
# Было:
name = response.text.strip().strip('"').strip("'")

# Стало:
result = json.loads(response.text)
name = result.get("cluster_name", "").strip()
```

**`ClusterNameResponse`** определён на уровне модуля (Pydantic fork-safe),
не пересоздаётся в цикле.

---

## 2. Рефактор `_fetch_positions`

**Было:** `conn.fetch(SQL_FETCH_POSITIONS)` → список asyncpg Record,
`json.loads(r["embedding"])` на каждой строке.

**Стало:**
- `init=init_conn` в `asyncpg.create_pool` — бинарный кодек pgvector
  регистрируется один раз для каждого соединения в пуле, не перед каждым запросом.
- Серверный курсор `conn.cursor()` внутри транзакции — не загружает всю таблицу в RAM.
- `np.stack(embeddings_list)` вместо `np.array([json.loads(...)])`.
- Сигнатура: `tuple[list[int], list[str], np.ndarray]` вместо `list[Record]`.
- `import json` удалён из топ-уровня (больше не используется).

`run_clustering` обновлён под новую сигнатуру:
```python
ids, titles, embeddings = await self._fetch_positions()
```

---

## 3. Параметризация гиперпараметров

Добавлена env-переменная `SEMANTIC_CLUSTERER_UMAP_NEIGHBORS` (default: 15).
В `__init__` добавлен `self.umap_neighbors`.

`ClusterizeParams` в `main.py` переведён на `int | None = None` дефолты.
Перед передачей в Celery фильтруются `None`-значения:
```python
explicit_params = {k: v for k, v in params.model_dump().items() if v is not None}
```
Это позволяет env-var дефолтам воркера работать при вызове без явных параметров.

---

## 4. UMAP — статичные параметры + правильный `min_required`

**Проблема:** динамический кэп `n_components = min(umap_components, len-2)`
нарушает консистентность пространства: при разных размерах датасета HDBSCAN
работает в разных размерностях, находя несопоставимые кластеры.

**Решение:** убрать динамику, увеличить запас `min_required`:
```python
min_required = max(self.umap_components + 5, self.umap_neighbors + 2)
```
`+5` покрывает требование `eigsh(k=n_components+1)` UMAP spectral layout
с достаточным запасом. При нехватке данных — warning и `return {}`,
без деградации размерности.

---

## 5. SQL_INSERT_GROUP — атомарный upsert

**Было:** двухшаговый CTE (`existing` → `WHERE NOT EXISTS (SELECT 1 FROM existing)`).
Уязвимость: если `GROUP_TITLE` со статусом `pending_indexing` уже существует,
CTE его «не видел» (фильтр `status = 'active'`) и пытался вставить повторно.

**Стало:** `ON CONFLICT (standard_job_title, (COALESCE(unit_id, -1::bigint))) DO NOTHING`
с `UNION ALL` fallback SELECT. Атомарен, race-condition защищён.
Убран фильтр `status = 'active'` из fallback — теперь возвращает любой `GROUP_TITLE`
с этим именем независимо от статуса.

```sql
WITH inserted AS (
    INSERT INTO catalog_positions (...)
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
```

---

## 6. `_persist_clusters` — мягкий сбой вместо `RuntimeError`

**Было:** `group_id is None` → `raise RuntimeError(...)` — ронял всю транзакцию.

**Стало:** `continue` + `warning` лог — пропускаем один кластер, сохраняем остальные.
Частичное сохранение (`len(updated) != len(member_ids)`) логируется на уровне `warning`.

---

## 7. Импорты — fork safety

`from google.genai import types` убран из топ-уровня.
Теперь импортируется только внутри `_get_cluster_name` (после fork Celery).
`_get_genai_client` — убран дублирующийся `from google.genai import types`
вне `if self._genai_client is None`.

---

## 8. Логирование гиперпараметров

В `__init__` добавлен `logger.info` с полными параметрами при старте воркера:
```
Параметры кластеризации: min_cluster_size=5, umap_components=15,
umap_neighbors=15, llm_top_k=10 (raw payload: {...})
```

---

## 9. `_run_ml_pipeline` — `task_id` в лог

Сигнатура изменена: `_run_ml_pipeline(self, task_id: str, embeddings)`.
Warning при нехватке данных теперь включает `task_id`.

---

## Изменённые файлы

| Файл | Изменение |
|------|-----------|
| `app/workers/semantic_clusterer/worker.py` | Все пункты выше |
| `main.py` | `ClusterizeParams` с `None`-дефолтами, фильтрация `explicit_params` |

## Технический долг

- Кластеризация на малых батчах (`< min_required`) молча возвращает `{}` —
  нет метрики для мониторинга частоты этого события.
- `umap_neighbors` не передаётся из Go-хендлера `ProxyClusterizeHandler`
  (тот знает только `min_cluster_size`, `umap_components`, `llm_top_k`).
