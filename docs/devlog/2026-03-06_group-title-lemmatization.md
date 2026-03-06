# 2026-03-06 — Поддержка GROUP_TITLE с лемматизацией в search_indexer worker

## Контекст

Search Indexer Worker (`worker.py`) ранее обрабатывал только строки с `kind = 'POSITION'`,
где `standard_job_title` уже был лемматизирован upstream. Теперь воркер получает
строки с `kind = 'GROUP_TITLE'`, в которых `standard_job_title` содержит сырой
пользовательский ввод. Для корректной индексации и дедупликации воркер должен
самостоятельно лемматизировать заголовок перед генерацией эмбеддинга.

## Что сделано

### 1. `SQL_FETCH_BATCH` — добавлена колонка `kind`

В `SELECT` добавлено поле `cp.kind`, чтобы воркер мог различать тип строки
и применять соответствующую логику обработки.

### 2. Новая SQL-константа `SQL_ACTIVATE_GROUP`

Для `GROUP_TITLE` строк нужно записать не только embedding и `status = 'active'`,
но и обновлённый (лемматизированный) `standard_job_title`:

```sql
UPDATE catalog_positions
SET embedding          = $1::vector,
    standard_job_title = $2,
    status             = 'active',
    updated_at         = NOW()
WHERE id = $3 AND status = 'pending_indexing';
```

Status guard (`AND status = 'pending_indexing'`) сохранён для идемпотентности.

### 3. Функция `_lemmatize_text()`

Делегирует лемматизацию в `normalize_job_title_with_lemmatization()`
из `app.excel_parser.sanitize_text` — тот же пайплайн, что используется
при парсинге Excel-таблиц:

1. lowercase
2. удаление Markdown-разметки (`**`, `_`, `---`)
3. замена пунктуации на пробелы (дефисы внутри слов сохраняются)
4. лемматизация через spaCy `ru_core_news_sm`

Импорт ленивый (внутри функции) — соответствует паттерну
воркера (инициализация после fork в Celery). Если
`normalize_job_title_with_lemmatization` вернёт `None` (пустой ввод),
функция фолбэчится на `text.strip()`, чтобы не потерять данные.

Вызывается для строк с `kind == 'GROUP_TITLE'` в Phase 2,
до построения composite string и отправки в Gemini Embedding API.

### 4. Обновлённая структура данных в `run_indexing()`

Кортежи `embed_results` и `embeddable_rows` расширены полем `kind`:

- `embed_results`: `(pos_id, title, kind, emb_literal | None, skip_reason | None)`
- `embeddable_rows`: `(pos_id, title, kind, text_to_embed)`

Это позволяет Phase 3 знать, какой SQL-запрос использовать.

### 5. Условная активация в Phase 3

В фазе записи в БД добавлена ветка:

- `kind == 'GROUP_TITLE'` → `SQL_ACTIVATE_GROUP(emb_literal, title, pos_id)` —
  записывает embedding **и** лемматизированный `standard_job_title`.
- Иначе → `SQL_ACTIVATE(emb_literal, pos_id)` — стандартная активация.

## Файлы затронуты

- `app/workers/search_indexer/worker.py` — `SQL_FETCH_BATCH`, новая
  `SQL_ACTIVATE_GROUP`, `_lemmatize_text()`, обновлённый `run_indexing()`
- `app/excel_parser/sanitize_text.py` — без изменений, используется как источник
  `normalize_job_title_with_lemmatization()`

## Не затронуто

- Batch embedding оптимизация (один HTTP-запрос) — сохранена.
- Phase 1/2/3 структура — сохранена.
- Дедупликация и `suggested_merges` — работают одинаково для обоих kind.
- Обработка `no_description` и `embed_error` — без изменений.
