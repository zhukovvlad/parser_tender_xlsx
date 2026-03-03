# 2026-03-02 — Фикс race condition и upsert в search_indexer worker

## Контекст

В архитектуре Python-воркер → Go-бэкенд обнаружены три взаимосвязанные уязвимости
на стыке дедупликации и слияний позиций каталога:

1. **Race condition порога дедупликации** — воркер читал `dedup_distance_threshold`
   из `system_settings` *до* вызова Gemini API (генерация эмбеддингов). Если за время
   сетевого вызова администратор через Go API ужесточал порог, старые заявки удалялись,
   но воркер записывал новые дубликаты по устаревшему значению.
2. **`ON CONFLICT DO NOTHING` в Python** — Go-бэкенд использует
   `ON CONFLICT DO UPDATE` (обновляет `similarity_score`), а Python — `DO NOTHING`.
   При повторном прогоне оценки схожести не обновлялись.
3. **«Мёртвые души» после слияний** — после merge в Go позиция B становится
   `deprecated`, но PENDING-заявки с участием B зависают навсегда.
   *(Эта часть — зона ответственности Go-агента, здесь не затрагивается.)*

## Что сделано (Python-сторона)

### 1. `SQL_FIND_DUPLICATE` — порог внутри запроса

**Было:** порог передавался третьим параметром `$3`, считанным заранее.

**Стало:** подзапрос к `system_settings` прямо в `WHERE` с clamping через
`LEAST`/`GREATEST` для защиты от невалидных значений в БД:

```sql
AND (embedding <=> $1::vector) < LEAST(GREATEST(
      COALESCE(
        (SELECT value_numeric
           FROM system_settings
          WHERE key = 'dedup_distance_threshold'
          LIMIT 1),
        0.15
      ),
      0.01), 2.0)
```

Параметр `$3` удалён → запрос принимает только `$1` (вектор) и `$2` (id).
БД сама берёт актуальный порог в момент выполнения транзакции.
Фоллбэк 0.15 сохранён на случай отсутствия записи в `system_settings`.
Границы `[0.01, 2.0]` гарантируют, что невалидное значение в `system_settings`
не приведёт к некорректной дедупликации.

### 2. `SQL_INSERT_MERGE` — `ON CONFLICT DO UPDATE`

**Было:** `ON CONFLICT DO NOTHING` — повторный прогон не обновлял `similarity_score`.

**Стало:**

```sql
ON CONFLICT (main_position_id, duplicate_position_id) DO UPDATE
    SET similarity_score = EXCLUDED.similarity_score,
        status = CASE
            WHEN suggested_merges.status IN ('MERGED', 'REJECTED')
            THEN suggested_merges.status
            ELSE 'PENDING'
        END,
        updated_at = NOW();
```

- `similarity_score` обновляется всегда.
- Статус сбрасывается в `PENDING`, **если он не терминальный** (`MERGED`/`REJECTED`
  сохраняются).
- `updated_at` обновляется.

Логика совпадает с Go-стороной (`UpsertSuggestedMerge`).

### 3. Очистка `run_indexing()`

- Удалён блок «Fetch dynamic dedup threshold» (~40 строк) — предварительное
  чтение порога из `system_settings` больше не нужно.
- Удалена SQL-константа `SQL_GET_THRESHOLD`.
- Убран третий аргумент `dedup_threshold` из вызова
  `conn.fetchrow(SQL_FIND_DUPLICATE, ...)`.
- Переменная `dedup_threshold` полностью удалена из функции.

## Файлы затронуты

- `app/workers/search_indexer/worker.py` — `SQL_FIND_DUPLICATE`, `SQL_INSERT_MERGE`,
  `run_indexing()`, удалена `SQL_GET_THRESHOLD`

## Связанные задачи (Go-сторона, не затронуты)

- Зачистка «мёртвых душ» в `suggested_merges` после merge (каскадная отмена
  PENDING-заявок с участием deprecated-позиций) — зона ответственности Go-агента.
