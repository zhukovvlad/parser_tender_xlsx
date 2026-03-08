# 2026-03-07 — Hardening Search Indexer: SKIP LOCKED + Optimistic Concurrency Control

## Контекст

Search Indexer Worker (`worker.py`) запускается несколькими Celery-воркерами
одновременно. До этой правки существовали две неустранённые уязвимости, приводящие
к race condition в условиях реального production-трафика:

1. **Конкурентный захват строк** — несколько воркеров получали одинаковый батч из
   `pending_indexing`, т.к. `SQL_FETCH_BATCH` выполнял обычный `SELECT` без блокировки.
   Итог: лишние вызовы Gemini API и конфликты при фиксации.

2. **Перезапись правок администратора** — интервал между Phase 1 (Fetch) и Phase 3
   (Activate) может составлять от нескольких секунд до нескольких минут (время ответа
   Gemini API). Если администратор редактировал `description` в UI в это окно,
   `SQL_ACTIVATE_GROUP` перезаписывал лемматизированный `standard_job_title`,
   вычисленный от **старого** `description`.

## Что сделано

### 1. `SQL_FETCH_BATCH` — добавлен `FOR UPDATE OF cp SKIP LOCKED`

```sql
SELECT cp.id, cp.description, cp.standard_job_title, cp.kind,
       cp.updated_at,
       uom.normalized_name AS unit_name
FROM catalog_positions cp
LEFT JOIN units_of_measurement uom ON cp.unit_id = uom.id
WHERE cp.status = 'pending_indexing'
ORDER BY cp.id
LIMIT $1
FOR UPDATE OF cp SKIP LOCKED;
```

- `FOR UPDATE OF cp` блокирует строки `catalog_positions` при `SELECT`, не затрагивая
  пересечённые строки `units_of_measurement`.
- `SKIP LOCKED` пропускает уже заблокированные строки — если два воркера запускают
  `fetch()` **одновременно** (в рамках одного autocommit-statement), второй получит
  непересекающийся набор.

> **Ограничение:** `conn.fetch()` без явного `async with conn.transaction()` выполняется
> в **implicit autocommit-транзакции**, которая коммитится сразу после возврата данных.
> Row-locks снимаются немедленно — они живут только на время самого statement (миллисекунды).
> Поэтому `SKIP LOCKED` **не защищает** от повторной выборки тех же строк, если второй
> воркер запускает запрос уже после завершения первого. Это типичный сценарий при
> последовательных задачах Celery.
>
> **Реальная защита** от двойной записи обеспечивается в Phase 3 через status guard
> `AND status = 'pending_indexing'` — повторный UPDATE вернёт 0 строк (идемпотентность).
>
> **TODO:** для полного устранения лишних Gemini-запросов реализовать атомарный
> claim-паттерн с промежуточным статусом:
> ```sql
> UPDATE catalog_positions
>    SET status = 'indexing_in_progress'
>  WHERE id IN (
>    SELECT id FROM catalog_positions
>     WHERE status = 'pending_indexing'
>     ORDER BY id LIMIT $1
>     FOR UPDATE SKIP LOCKED
>  )
>  RETURNING id, description, standard_job_title, kind, ...;
> ```
> Требует добавления значения `'indexing_in_progress'` в CHECK constraint / enum
> столбца `status` и механизма сброса зависших строк (timeout heartbeat).

### 2. `SQL_ACTIVATE_GROUP` — Optimistic Concurrency Control через `updated_at`

> **Устарело:** Вначале guard использовал `description IS NOT DISTINCT FROM`. По результатам ревью (R7) переведён на `updated_at` — см. ниже.

```sql
UPDATE catalog_positions
SET embedding          = $1::vector,
    standard_job_title = $2,
    status             = 'active',
    updated_at         = NOW()
WHERE id = $3
  AND status = 'pending_indexing'
  -- Concurrency Guard: не перезаписываем title, если строка изменена (любое поле)
  AND updated_at IS NOT DISTINCT FROM $4;
```

Параметр `$4` — это `updated_at`, зафиксированный в Phase 1.
`IS NOT DISTINCT FROM` использован вместо `= $4` для корректной обработки `NULL`.

Если за время API-вызова admin изменил любое поле строки — `UPDATE` затронет **0 строк**,
строка останется `pending_indexing` и переиндексируется на следующем цикле с
актуальными данными.

### 3. `SQL_ACTIVATE_GROUP_NO_EMBEDDING` — тот же guard для no-embedding пути

> **Устарело:** Использовал `description IS NOT DISTINCT FROM`. Переведён на `updated_at` (см. R7).

```sql
UPDATE catalog_positions
SET standard_job_title = $1,
    status             = 'active',
    updated_at         = NOW()
WHERE id = $2
  AND status = 'pending_indexing'
  AND updated_at IS NOT DISTINCT FROM $3;
```

### 4. Обновлённая структура данных в `run_indexing()`

`description_raw` (исходное значение `row["description"]`, включая `None`) сохраняется для логики `no_description`.
`updated_at_raw` (значение `row["updated_at"]`) — version token для всех SQL-запросов оптимистической блокировки.
Оба прокидываются через кортежи:

- `embeddable_rows`: `(pos_id, title, kind, text_to_embed, description_raw, updated_at_raw)` — 6-tuple
- `embed_results`: `(pos_id, title, kind, emb_literal | None, skip_reason | None, description_raw, updated_at_raw)` — 7-tuple

Ключевое: `description_raw = row["description"]` (до `or ""`) — нужен для определения
ветки `no_description` в Phase 2. В Phase 3 не передаётся ни в один SQL-запрос
(позиция 6 в `embed_results` соответствует `description_raw` и игнорируется через `_` при деструктуризации).

### 5. Phase 3 — передача `updated_at_raw` в SQL

```python
# GROUP_TITLE с embedding
activate_result = await conn.execute(
    SQL_ACTIVATE_GROUP,
    emb_literal, title, pos_id, updated_at_raw,   # ← updated_at_raw как $4
)

# GROUP_TITLE без embedding
result = await conn.execute(
    SQL_ACTIVATE_GROUP_NO_EMBEDDING,
    title, pos_id, updated_at_raw,                # ← updated_at_raw как $3
)

# POSITION с embedding
activate_result = await conn.execute(
    SQL_ACTIVATE,
    emb_literal, pos_id, updated_at_raw,          # ← updated_at_raw как $3
)

# POSITION без embedding
result = await conn.execute(
    SQL_ACTIVATE_NO_EMBEDDING,
    pos_id, updated_at_raw,                       # ← updated_at_raw как $2
)
```

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `app/workers/search_indexer/worker.py` | SQL-константы, типы кортежей, Phase 2 и Phase 3 логика |

## Post-review правки (2026-03-07)

По итогам ревью Copilot и CodeRabbit внесены дополнительные исправления:

### R1 — `SQL_ACTIVATE` получил concurrency guard

`SQL_ACTIVATE` (для `POSITION`-строк) получил тот же guard, что и `SQL_ACTIVATE_GROUP` —
симметрия защиты для обоих типов строк.

### R2 — Warning-лог no-op уточнён

Лог уточнён: добавлено поле `kind`, чтобы при анализе было видно тип строки.
При срабатывании `early_guard_fired` второй warning больше не выводится (см. R7).

### R3 — Комментарий SKIP LOCKED исправлен

Комментарий к `SQL_FETCH_BATCH` уточнён: `SKIP LOCKED` в autocommit-режиме защищает
только от **одновременного** запуска двух воркеров, но **не** от последовательных.
Реальная идемпотентность обеспечивается status guard в Phase 3.
Добавлен TODO с описанием полноценного claim-паттерна через `indexing_in_progress`.

### R4 — Ранняя guard-проверка до dedup

**Проблема:** `SQL_INSERT_MERGE` выполнялся до финальной проверки guard.
Если строка изменилась, activation возвращала `UPDATE 0`, но запись в
`suggested_merges` уже была сделана на базе устаревшего embedding и повторялась
при каждом следующем прогоне.

**Решение:** в начале транзакции выполняется `SELECT 1 ... FOR UPDATE`,
который атомарно блокирует строку и проверяет version token. Если проверка
не прошла — весь блок dedup/merge/activate пропускается целиком.

### R5 — Грамматика

«два … уязвимостей» → «две … уязвимости»

### R6 — `SQL_ACTIVATE_NO_EMBEDDING` получил concurrency guard

Ветка `no_description` также не имела guard: воркер мог активировать строку без
embedding, если admin заполнил `description` после fetch. Добавлен guard аналогично
остальным SQL-константам.

### R7 — Замена `description` на `updated_at` как version token

**Проблема:** guard по `description` слишком узкий — embedding зависит ещё от
`unit_name` (через `unit_id`) и для `GROUP_TITLE` от `standard_job_title`. Изменение
любого из этих полей admin-ом приводило к публикации устаревшего embedding.

**Решение:** все пять SQL-констант (`SQL_ACTIVATE`, `SQL_ACTIVATE_GROUP`,
`SQL_ACTIVATE_GROUP_NO_EMBEDDING`, `SQL_ACTIVATE_NO_EMBEDDING`, ранняя guard-проверка)
переведены на `updated_at IS NOT DISTINCT FROM $N`.

`updated_at` — стандартный row-version token: любое изменение строки (через любое поле)
обязательно обновляет этот столбец. Один guard закрывает сразу все поля.

В Phase 1 в `SQL_FETCH_BATCH` добавлена колонка `cp.updated_at`.
В кортежах `embed_results` и `embeddable_rows` добавлен 7-й элемент `updated_at_raw`.
`description_raw` сохранён на 6-й позиции (нужен для логики `no_description`).

### R8 — Устранение двойного логирования

При `guard_ok is None` раньше печатались два warning подряд:
первый — «Concurrency guard fired early», второй — «Activate no-op» (т.к. `activate_result == "UPDATE 0"`).

**Решение:** добавлен флаг `early_guard_fired = True`, после выхода из блока
транзакции выполняется `continue` — второй warning полностью исключён.

## Покрытие тестами (требуется)

Обновлены пункты в `TESTING_CHECKLIST.md` (секция 3.9):

- `SQL_FETCH_BATCH` содержит `FOR UPDATE OF cp SKIP LOCKED` и колонку `cp.updated_at`
- Все SQL_ACTIVATE* содержат guard `AND updated_at IS NOT DISTINCT FROM $N`
- Version token: изменение `unit_name` или `standard_job_title` тоже срабатывает guard
- Early guard до dedup: `suggested_merges` не пишется при изменённой строке
- `early_guard_fired` — только один warning в лог, нет дублирования
- `updated_at_raw` передаётся через все кортежи Phase 2 → Phase 3
