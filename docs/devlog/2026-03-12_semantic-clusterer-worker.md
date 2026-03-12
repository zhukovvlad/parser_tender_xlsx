# 2026-03-12 — Новый воркер: Semantic Clusterer (UMAP + HDBSCAN + Gemini)

## Контекст

В MDM-системе каталога позиций накопилось большое количество активных позиций-листьев
(`kind = 'POSITION'`, `status = 'active'`, `parent_id IS NULL`) без привязки к
родительской группе. Ручная категоризация тысяч позиций нереалистична. Требуется
автоматическая семантическая кластеризация на основе embedding-векторов с последующим
именованием кластеров через LLM.

Создан новый воркер `app/workers/semantic_clusterer/`, архитектурно являющийся
гибридом двух существующих:
- **От `parser`:** `task_id` + Redis-статусы прогресса (`_safe_set_status`, `_bump_ttl`).
- **От `search_indexer`:** изолированный JSON-логгер, прямой `asyncpg` без ORM, транзакции.

## Что сделано

### 1. Зависимости (`requirements.txt`)

Добавлены ML-библиотеки:
- `umap-learn>=0.5.0` — снижение размерности embedding-пространства
- `hdbscan>=0.8.33` — density-based кластеризация
- `scikit-learn>=1.3.0` — зависимость UMAP/HDBSCAN

`numpy` уже присутствовал.

### 2. Регистрация в Celery (`celery_app.py`)

- `include` — `"app.workers.semantic_clusterer.tasks"`
- `task_routes` — `"app.workers.semantic_clusterer.tasks.*": {"queue": "clusterer"}`
- `autodiscover_tasks` — `"app.workers.semantic_clusterer"`

Выделенная очередь `clusterer` изолирует тяжёлые ML-вычисления от остальных воркеров.

### 3. Изолированный логгер (`logger.py`)

Полная копия паттерна из `search_indexer/logger.py`:
- `_JsonFormatter` — структурированный JSON на строку
- Файл: `logs/semantic_clusterer.log`
- Env: `SEMANTIC_CLUSTERER_LOG_LEVEL` → `LOG_LEVEL` → `INFO`
- Функция: `get_semantic_clusterer_logger(name)`
- Guard `_semantic_clusterer_configured` предотвращает повторную настройку

### 4. Celery-задача (`tasks.py`)

**Redis-хелперы** (скопированы из `parser/tasks.py`):
- `make_redis()` — поддерживает `REDIS_URL` и `REDIS_HOST`/`REDIS_PORT`
- `_safe_set_status(task_id, payload)` — JSON в `task_status:{task_id}` с TTL
- `_bump_ttl(task_id)` — продление TTL во время долгих фаз

**Задача `run_semantic_clustering`:**
- `@shared_task(bind=True)`, `max_retries=3`, `soft_time_limit=3600`, `time_limit=3900`
- Статусы: `processing` → `completed` (с `clusters_found`) / `failed` / `retrying`
- `SoftTimeLimitExceeded` не ретраится (терминальный)
- Прочие исключения ретраятся с прогрессивным countdown
- Async-логика запускается через `run_async()` — тот же паттерн, что в `search_indexer`
- `SemanticClustererWorker` создаётся и уничтожается в рамках одного вызова задачи

### 5. Бизнес-логика (`worker.py`)

Класс `SemanticClustererWorker` с ленивой инициализацией `asyncpg` pool.

**Phase 1 — Fetch:**
```sql
SELECT id, standard_job_title, embedding::text
FROM catalog_positions
WHERE status = 'active' AND kind = 'POSITION'
  AND parent_id IS NULL AND embedding IS NOT NULL
```
Embedding парсится через `json.loads` из текстового представления `pgvector`.

**Phase 2 — ML Pipeline (CPU-bound):**
Строго через `asyncio.to_thread`:
- UMAP: `metric='cosine'`, `n_components=15` (capped до `len(data)-1`), `random_state=42`
- HDBSCAN: `min_cluster_size=5`, `metric='euclidean'`, `cluster_selection_method='eom'`
- Выбросы (`label == -1`) отбрасываются
- Члены каждого кластера отсортированы по `probabilities_` (desc) для фазы LLM

**Phase 3 — LLM Naming:**
- ТОП-10 позиций (по `probabilities_`) отправляются в Gemini (`gemini-2.5-flash`)
- Промпт: «Проанализируй строительные работы → короткое название 2-5 слов»
- `generate_content` вызывается через `asyncio.to_thread` (синхронный SDK)
- Fallback: `"Авто-группа"` при отсутствии API-ключа, пустом ответе или ошибке

**Phase 4 — Persist:**
Строго в одной `asyncpg` транзакции:
```sql
INSERT INTO catalog_positions (standard_job_title, kind, status, updated_at)
VALUES ($1, 'GROUP_TITLE', 'pending_indexing', NOW()) RETURNING id;

UPDATE catalog_positions SET parent_id = $1, updated_at = NOW()
WHERE id = ANY($2::bigint[])
  AND parent_id IS NULL;
```

### 6. Скрипты запуска

**`Makefile`:**
- Новая цель `celery-worker-clusterer` с `--concurrency=1 --queues=clusterer`
- Добавлена в `.PHONY` и `help`

**`scripts/start_services.sh`:**
- Пункт 5: `celery-clusterer` между `celery-default` и `celery-beat`
- Строка лога в блоке вывода

**`scripts/stop_services.sh`** — изменений не требуется: `pkill -f "celery -A app.celery_app"`
убивает все Celery-процессы включая новый воркер.

## Конфигурация через переменные окружения

| Переменная | Default | Описание |
|---|---|---|
| `SEMANTIC_CLUSTERER_LOG_LEVEL` | `INFO` | Уровень логов |
| `SEMANTIC_CLUSTERER_LLM_MODEL` | `gemini-2.5-flash` | Модель для naming |
| `SEMANTIC_CLUSTERER_POOL_MIN` | `2` | Минимум соединений asyncpg |
| `SEMANTIC_CLUSTERER_POOL_MAX` | `5` | Максимум соединений asyncpg |
| `SEMANTIC_CLUSTERER_UMAP_COMPONENTS` | `15` | n_components UMAP |
| `SEMANTIC_CLUSTERER_HDBSCAN_MIN_SIZE` | `5` | min_cluster_size HDBSCAN |
| `SEMANTIC_CLUSTERER_LLM_TOP_K` | `10` | Кол-во позиций для промпта |

## Структура файлов

```
app/workers/semantic_clusterer/
├── __init__.py    — docstring модуля
├── logger.py      — JSON-логгер → logs/semantic_clusterer.log
├── tasks.py       — Celery-задача + Redis helpers
└── worker.py      — SemanticClustererWorker (asyncpg + UMAP + HDBSCAN + Gemini)
```

## Ключевые архитектурные решения

1. **`--concurrency=1`** — UMAP и HDBSCAN используют все доступные ядра CPU;
   параллельный запуск нескольких задач приведёт к конкуренции за CPU и деградации.

2. **`asyncio.to_thread` для ML** — numpy/UMAP/HDBSCAN вычисления блокируют event loop;
   изоляция в потоке сохраняет отзывчивость asyncpg и Redis.

3. **`asyncio.to_thread` для Gemini** — `google-genai` SDK синхронный; вызов
   `generate_content` в потоке не блокирует event loop.

4. **Одна транзакция на Phase 4** — INSERT группы + UPDATE parent_id атомарны;
   при ошибке в середине откатываются все изменения.

5. **Worker per-task** — `SemanticClustererWorker` создаётся и уничтожается в рамках
   каждого вызова задачи (в отличие от `search_indexer`, который использует синглтон).
   Обосновано: кластеризация запускается редко (ad-hoc), а не каждые 30 секунд.

## Исправления по результатам code review (PR #45)

### R1, R3. Logger namespace collision (Copilot)

`get_semantic_clusterer_logger("tasks")` и `("worker")` создавали глобальные
логгеры `logging.getLogger("tasks")` / `("worker")`, которые коллидировали с
одноимёнными логгерами других воркеров. Исправлено на
`"semantic_clusterer.tasks"` и `"semantic_clusterer.worker"`.

### R2. `self.retry()` при исчерпанных ретраях (Copilot)

`self.retry()` при `will_retry=False` выбрасывал `MaxRetriesExceededError`,
затирая оригинальный traceback. Теперь: `raise self.retry(...)` только
при `will_retry=True`, иначе `raise` оригинального исключения.

### R4. GenAI client без httpx timeouts (Copilot)

Добавлены явные `httpx.Timeout(120.0, connect=60.0)` в `client_args`,
выровнено с паттерном `search_indexer/worker.py`. Предотвращает
зависания при медленном SSL handshake (WSL2).

### R5. SoftTimeLimitExceeded не отменяет корутину (CodeRabbit) — ОТЛОЖЕНО

`run_async()` — shared utility, изменение сигнатуры затронет все воркеры.
С `--concurrency=1` корутина завершится при перезапуске процесса. Добавлен TODO.

### R6. `SQL_INSERT_GROUP` со статусом `'active'` обходит search_indexer (CodeRabbit)

Отличный catch. Группы, вставленные как `active`, не попадут в search_indexer
и не получат embeddings. Исправлено на `pending_indexing`.

### R7. Нет блокировки на весь fetch→persist window (CodeRabbit)

Добавлена двухуровневая защита:
1. **Redis distributed lock** (`semantic_clusterer:run_lock`) с TTL 3720с —
   блокирует параллельный запуск. Дублирующая задача получает
   `status: "skipped"`.
2. **`WHERE parent_id IS NULL`** в `SQL_UPDATE_PARENT` — defense-in-depth,
   предотвращает перезапись уже привязанных позиций.

### Фикс модели

Исправлено `gemini-2.0-flash` → `gemini-2.5-flash` в default значении
`SEMANTIC_CLUSTERER_LLM_MODEL`.

### R8. `n_components` может стать 0 (Copilot)

`min(UMAP_N_COMPONENTS, len(embeddings) - 1)` даёт 0 при одном embedding.
Добавлен `max(1, ...)` — UMAP получает валидный `n_components ≥ 1`.

### R9. `logging.getLevelName` не работает для name→int (Copilot) — НЕ ПРИМЕНЕНО

Замечание ошибочно: `logging.getLevelName("INFO")` возвращает `20` (int),
а не строку. Текущий код с `isinstance(numeric_level, int)` guard корректен.

### R13. Lock TTL < hard time_limit (Copilot)

`_CLUSTERER_LOCK_TTL = 3720` (soft_time_limit + 120) был меньше
`time_limit = 3900`. Лок мог истечь до SIGKILL. Исправлено: `3900 + 120 = 4020`.

### R10/R11. TESTING_CHECKLIST: `status='active'` → `'pending_indexing'` (Copilot+CodeRabbit)

Две строки в чеклисте (§3.10.4, §4.5) ещё указывали `status='active'` для
GROUP_TITLE. Выровнено с фактическим SQL в `worker.py`.

### R12. Нет автоматических тестов (Copilot) — ОТЛОЖЕНО

Тест-спецификация уже в `TESTING_CHECKLIST.md` (§3.10–3.12, §4.5–4.6).
Реализация тестов — отдельная задача.

### R16. `Redis.lock(blocking=False)` — TypeError (Copilot)

`redis-py` `Redis.lock()` не принимает `blocking=` — это параметр `lock.acquire()`.
Удалён невалидный kwarg из конструктора лока; `acquire(blocking=False)` уже корректен.

### R17. `self._pool` без проверки инициализации (Copilot)

`run_clustering()` использовал `self._pool` без guard-а. При вызове без 
`initialize()` — непонятный `AttributeError: 'NoneType'`. Добавлен
`if not self.is_initialized or self._pool is None: raise RuntimeError(...)`.

### R18. Lock release при SoftTimeLimitExceeded (Copilot)

`finally: lock.release()` отпускал лок, пока корутина в `run_async` ещё работала.
Новая задача могла захватить лок и обработать те же позиции. Теперь: при
`SoftTimeLimitExceeded` лок НЕ отпускается (`lock = None`), истекает по TTL.

### R19. `SQL_FETCH_POSITIONS` без `ORDER BY` (Copilot)

Без детерминированного порядка вход UMAP/HDBSCAN мог меняться между запусками,
делая `random_state=42` бесполезным. Добавлен `ORDER BY id`.

### R20. Exception chaining `from e` (CodeRabbit)

`raise self.retry(exc=e, ...) from e` — сохраняет исходный traceback при ретрае
(Ruff B904).

### R21. UMAP `n_neighbors` >= `n_samples` → ValueError (Copilot)

При малом числе позиций (< 15) дефолт UMAP `n_neighbors=15` превышает `n_samples`
и вызывает ValueError. Добавлен явный `n_neighbors = min(15, len(embeddings) - 1)`.

### Nitpick: Пиннинг ML-зависимостей (CodeRabbit) — ОТЛОЖЕНО

Рекомендация пиннить `umap-learn`, `hdbscan`, `scikit-learn` до точных версий.
Отложено до стабилизации пайплайна — пока идёт активная разработка ML-части.
