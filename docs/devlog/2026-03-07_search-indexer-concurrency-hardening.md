# 2026-03-07 — Hardening Search Indexer: SKIP LOCKED + Optimistic Concurrency Control

## Контекст

Search Indexer Worker (`worker.py`) запускается несколькими Celery-воркерами
одновременно. До этой правки существовали два неустранённых уязвимостей, приводящих
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

### 2. `SQL_ACTIVATE_GROUP` — Optimistic Concurrency Control через `description`

```sql
UPDATE catalog_positions
SET embedding          = $1::vector,
    standard_job_title = $2,
    status             = 'active',
    updated_at         = NOW()
WHERE id = $3
  AND status = 'pending_indexing'
  -- Concurrency Guard: не перезаписываем title, если description изменён
  AND description IS NOT DISTINCT FROM $4;
```

Параметр `$4` — это исходный `description`, зафиксированный в Phase 1.
`IS NOT DISTINCT FROM` использован вместо `= $4` для корректной обработки `NULL`:
в SQL `NULL = NULL` возвращает `NULL` (не `TRUE`), тогда как
`NULL IS NOT DISTINCT FROM NULL` возвращает `TRUE`.

Если за время API-вызова admin изменил `description` — `UPDATE` затронет **0 строк**,
строка останется `pending_indexing` и переиндексируется на следующем цикле с
актуальными данными.

### 3. `SQL_ACTIVATE_GROUP_NO_EMBEDDING` — тот же guard для no-embedding пути

```sql
UPDATE catalog_positions
SET standard_job_title = $1,
    status             = 'active',
    updated_at         = NOW()
WHERE id = $2
  AND status = 'pending_indexing'
  AND description IS NOT DISTINCT FROM $3;
```

### 4. Обновлённая структура данных в `run_indexing()`

`description_raw` (исходное значение `row["description"]`, включая `None`) сохраняется
в Phase 2 и прокидывается через кортежи как **concurrency token**:

- `embeddable_rows`: `(pos_id, title, kind, text_to_embed, description_raw)` — 5-tuple
- `embed_results`: `(pos_id, title, kind, emb_literal | None, skip_reason | None, description_raw)` — 6-tuple

Ключевое: `description_raw = row["description"]` (до `or ""`), чтобы `None`
передался в SQL как SQL `NULL`, а не как пустая строка.

### 5. Phase 3 — передача `description_raw` в SQL

```python
# GROUP_TITLE с embedding
activate_result = await conn.execute(
    SQL_ACTIVATE_GROUP,
    emb_literal, title, pos_id, description_raw,  # ← description_raw как $4
)

# GROUP_TITLE без embedding
result = await conn.execute(
    SQL_ACTIVATE_GROUP_NO_EMBEDDING,
    title, pos_id, description_raw,               # ← description_raw как $3
)
```

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `app/workers/search_indexer/worker.py` | SQL-константы, типы кортежей, Phase 2 и Phase 3 логика |

## Post-review правки (2026-03-07)

По итогам ревью Copilot и CodeRabbit внесены дополнительные исправления:

### R1 — `SQL_ACTIVATE` теперь тоже имеет concurrency guard

`SQL_ACTIVATE` (для `POSITION`-строк) получил тот же `AND description IS NOT DISTINCT FROM $3`,
что и `SQL_ACTIVATE_GROUP`. Ранее `POSITION` мог получить устаревший embedding при
изменении `description` администратором во время Gemini-вызова.

### R2 — Warning-лог no-op уточнён

`"Activate no-op pos_id=%s (status guard)"` изменён на
`"Activate no-op pos_id=%s (status guard или concurrency guard: description изменён admin-ом)"`.
В лог также добавлено поле `kind`, чтобы отличать POSITION от GROUP_TITLE при анализе.

### R3 — Комментарий SKIP LOCKED исправлен

Комментарий к `SQL_FETCH_BATCH` и текст девлога уточнены: явно указано, что
`SKIP LOCKED` в autocommit-режиме защищает только от **одновременного** (в пределах
миллисекунд) запуска двух воркеров, но **не** от последовательных запусков.
Реальная идемпотентность обеспечивается status guard в Phase 3.
Добавлен TODO с описанием полноценного claim-паттерна.

## Покрытие тестами (требуется)

Добавлены новые пункты в `TESTING_CHECKLIST.md` (секция 3.9):

- `SQL_FETCH_BATCH` содержит `FOR UPDATE OF cp SKIP LOCKED`
- `SQL_ACTIVATE` содержит guard `AND description IS NOT DISTINCT FROM $3`
- `SQL_ACTIVATE_GROUP` содержит guard `AND description IS NOT DISTINCT FROM $4`
- `SQL_ACTIVATE_GROUP_NO_EMBEDDING` содержит guard `AND description IS NOT DISTINCT FROM $3`
- Concurrency guard: admin update wins — `UPDATE 0` при изменённом `description`
- `description=None` корректно передаётся как SQL `NULL` через asyncpg
- No-op лог содержит поле `kind` для диагностики
