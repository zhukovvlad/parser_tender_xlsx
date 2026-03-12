# Чеклист тестирования: Parser Tender XLSX

> Статус: 🔲 — не начато | ✅ — выполнено | ⏳ — в работе

---

## I. Инфраструктура тестирования

### 1.1 Конфигурация pytest

- [x] `pyproject.toml` содержит секцию `[tool.pytest.ini_options]`
- [x] `testpaths` включает `tests/` и `app/tests/`
- [x] `addopts` включает `--strict-markers` (нельзя использовать незарегистрированные маркеры)
- [x] Зарегистрированы маркеры: `unit`, `integration`, `slow`, `gemini`, `offline`

### 1.2 Конфигурация coverage

- [x] `pyproject.toml` содержит секцию `[tool.coverage.run]`
- [x] `source = ["app"]` — измеряем только код проекта
- [x] `omit` исключает тестовые файлы
- [x] Определён `[tool.coverage.report]` с `show_missing = true`

### 1.3 Структура директорий

- [x] `tests/` существует в корне репозитория
- [x] `tests/unit/` — для юнит-тестов
- [x] `tests/integration/` — для интеграционных тестов
- [x] `tests/contract/` — для контрактных тестов
- [x] `tests/fixtures/` существует
- [x] `tests/fixtures/excel/` — для .xlsx-фикстур
- [x] `tests/fixtures/json/` — для golden JSON-файлов
- [x] `tests/fixtures/gemini/` — для мок-ответов Gemini API
- [x] `tests/fixtures/README.md` с инструкциями

### 1.4 Makefile

- [x] `make test` — запускает все тесты
- [x] `make test-fast` — быстрый прогон без интеграций и Gemini
- [x] `make test-coverage` — тесты с HTML-отчётом покрытия
- [x] `make test-integration` — только интеграционные тесты
- [x] `make test-excel-parser` — только тесты Excel-парсера
- [x] `make test-gemini` — только тесты Gemini-модуля
- [x] `make lint` — проверка flake8
- [x] `make check` — проверка форматирования (black + isort)
- [x] `make format` — форматирование кода

### 1.5 CI/CD

- [x] `.github/workflows/tests.yml` существует
- [x] CI запускается на push/PR в `main`, `master`, `develop`
- [x] CI шаги: checkout → Python setup → install → check → test-coverage
- [x] Coverage HTML-артефакт загружается в GitHub Actions
- [ ] CI badge добавлен в README.md (опционально)

### 1.6 Документация

- [x] `TESTING.md` в корне репозитория
- [x] `QA_TEST_SPEC.md` в корне репозитория
- [x] `TESTING_CHECKLIST.md` в корне репозитория (этот файл)
- [x] `tests/fixtures/README.md` с описанием фикстур

---

## II. Тестовые данные и фикстуры

### 2.1 Excel-фикстуры (`tests/fixtures/excel/`)

- [ ] `happy_path_single_lot.xlsx` — один лот, один подрядчик, все поля заполнены
- [ ] `happy_path_multi_lot.xlsx` — два лота, один подрядчик
- [ ] `happy_path_full.xlsx` — несколько лотов, несколько подрядчиков, все блоки
- [ ] `multi_contractor_3.xlsx` — три подрядчика в одном лоте
- [ ] `multi_contractor_4_diff_cols.xlsx` — четыре подрядчика с разными наборами колонок
- [ ] `dirty_extra_empty_cols.xlsx` — лишние пустые колонки между подрядчиками
- [ ] `dirty_merged_cells.xlsx` — объединённые ячейки в шапке и в позициях
- [ ] `dirty_mixed_types.xlsx` — числа вместо строк в ячейках-ключах
- [ ] `dirty_extra_whitespace.xlsx` — лишние пробелы в ключах и значениях
- [ ] `dirty_partial_rows.xlsx` — частично заполненные строки позиций
- [ ] `edge_no_additional_info.xlsx` — блок «Дополнительная информация» отсутствует
- [ ] `edge_no_executor.xlsx` — блок исполнителя отсутствует
- [ ] `edge_partial_executor.xlsx` — только имя исполнителя без тел/даты
- [ ] `edge_itogo_rows.xlsx` — строки «ИТОГО» и «В том числе НДС» присутствуют
- [ ] `edge_empty_optional_fields.xlsx` — поля «Предлагаемое количество» и «Общее кол-во» пусты
- [ ] `negative_empty.xlsx` — полностью пустой лист
- [ ] `negative_wrong_structure.xlsx` — файл не является тендером

### 2.2 Golden JSON-файлы (`tests/fixtures/json/`)

- [ ] `happy_path_single_lot.json` — соответствует `happy_path_single_lot.xlsx`
- [ ] `happy_path_multi_lot.json` — соответствует `happy_path_multi_lot.xlsx`
- [ ] `multi_contractor_3.json` — соответствует `multi_contractor_3.xlsx`
- [ ] `edge_no_additional_info.json`
- [ ] `edge_itogo_rows.json`

### 2.3 Gemini-моки (`tests/fixtures/gemini/`)

- [ ] `response_simple_positions.json` — типичный успешный ответ
- [ ] `response_empty_input.json` — ответ на пустой промпт
- [ ] `response_malformed_json.json` — ответ с невалидным JSON в тексте
- [ ] `response_api_error.json` — симуляция ошибки API (HTTP 500)
- [ ] `response_timeout.json` — симуляция таймаута (через mock)

---

## III. Юнит-тесты по функциональным блокам

### 3.1 Парсинг шапки тендера (`read_headers`)

- [x] **Happy path:** все три поля (Предмет, Объект, Адрес) заполнены → корректные значения
- [x] **Пустой лист** → все поля `None`, без исключений
- [x] **Только ID без названия** (`№456789`) → `tender_id` = `"456789"`, `tender_title` = `"456789"`
- [x] **Данные вне диапазона** (строки 2 и 6) → игнорируются
- [x] **Лишние пробелы** в ключах и значениях → корректная нормализация
- [x] **Ключевое слово не в первой позиции строки** → игнорируется
- [x] **Только символ `№`** → `tender_id` = `None`
- [x] **Числовое значение** вместо строки → корректное преобразование в `str`
- [x] **Частичные данные** (только Объект) → остальные поля `None`
- [x] **Дублирующиеся ключи** → используется последнее значение
- [ ] **Ключ с двоеточием** (`"Объект:"`) → нормализуется и распознаётся
- [ ] **Ключ в смешанном регистре** (`"ОБЪЕКТ"`, `"объект"`) → нормализуется и распознаётся
- [ ] **Значение с внутренними переводами строк** → корректная обработка

### 3.2 Лоты (`read_lots_and_boundaries`)

- [ ] **Один лот** → корректные границы
- [ ] **Два лота** → оба лота с правильными границами
- [ ] **Три и более лотов** → все лоты с корректными границами
- [ ] **Строка «Лот №» в разных колонках** → обнаруживается
- [ ] **«Лот №» с пробелами** (`"Лот № 1"`, `"Лот №1"`) → оба варианта распознаются
- [ ] **Файл без лотов** → пустой список / `None`, без исключений
- [ ] **«Лот №» в последней строке** → корректная граница конца

### 3.3 Подрядчики (`read_contractors`, `parse_contractor_row`)

- [ ] **Один подрядчик** → список из одного элемента с корректными данными
- [ ] **Три подрядчика** → все три найдены, корректные диапазоны колонок
- [ ] **«Наименование контрагента» исключается** из списка подрядчиков
- [ ] **«Расчетная стоимость» исключается** из списка подрядчиков
- [ ] **Лишние пустые колонки между подрядчиками** → не ломают поиск
- [ ] **Метаданные КП (первые 4 строки):** Наименование, ИНН, Адрес, Статус аккредитации
- [ ] **Неполный блок КП** (меньше 4 строк) → доступные поля заполнены, остальные `None`
- [ ] **Разные наборы колонок у подрядчиков** → каждый подрядчик получает свои колонки
- [ ] **Подрядчик с пустым именем** → обрабатывается без исключений

### 3.4 Позиции items (`get_lot_positions`, `get_items_dict`)

- [ ] **Парсинг останавливается на «Дополнительная информация»** (case-insensitive)
- [ ] **«Дополнительная информация» без регистра** (`"ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ"`) → тоже останавливает
- [ ] **Поле `suggested_quantity` включается, если значение есть** и НЕ включается если пусто
- [ ] **Поле `organizer_quantity_total_cost` включается, если есть** и НЕ включается если пусто
- [ ] **Поле «Стоимость всего за объемы заказчика» включается, если есть** и НЕ если пусто
- [ ] **Строка «ИТОГО …»** → добавляется как item
- [ ] **Строка «В том числе НДС …»** → добавляется как item
- [ ] **Анализ до первой полностью пустой строки** → корректное определение конца блока
- [ ] **Нулевые значения (0)** → остаются (не путать с отсутствием)
- [ ] **Позиция с главой** (раздел без числовых данных) → корректная структура
- [ ] **Пустой диапазон позиций** → пустой список, без исключений

### 3.5 Блок «Дополнительная информация» (`get_additional_info`)

- [ ] **Ключи в первом столбце** → корректное извлечение
- [ ] **Значения по колонкам подрядчиков** → каждый подрядчик получает своё значение
- [ ] **NaN-значение** → сохраняется как `null` в JSON
- [ ] **Прекращение на «Исполнитель:»** → строки исполнителя не попадают в блок
- [ ] **Прекращение на «тел:»** → аналогично
- [ ] **Прекращение на «Дата составления …»** → аналогично
- [ ] **Блок полностью отсутствует** → пустой dict / `None`, без исключений
- [ ] **Все значения NaN** → все поля `null`
- [ ] **Ключи с пробелами и двоеточиями** → нормализуются

### 3.6 Блок исполнителя (`read_executer_block`)

- [ ] **Все три поля** (имя, тел, дата) → корректное извлечение по префиксам
- [ ] **Только имя** (нет тел/даты) → имя заполнено, остальные `None`
- [ ] **Блок отсутствует** → все поля `None`, без исключений
- [ ] **Дата в разных форматах** → корректная обработка или `None`
- [ ] **Лишние пробелы в префиксах** → «  Исполнитель:  » → нормализуется

### 3.7 Санитайзер текста (`sanitize_text`)

- [ ] **Строка с пробелами** → trim
- [ ] **Строка с непечатаемыми символами** → очищаются
- [ ] **`None` на входе** → возвращает `None` или `""`
- [ ] **Числовое значение** → конвертируется в строку
- [ ] **Пустая строка** → возвращает `None` или `""`

### 3.8 Постобработка (`postprocess`)

- [ ] **Удаление None/NaN полей** → только если по спецификации
- [ ] **Нормализация числовых строк** → `"10.5"` → `10.5` (если применимо)
- [ ] **Сохранение структуры при пустом вводе** → без исключений
- [ ] **Корректность финального JSON** — соответствие схеме

### 3.9 Search Indexer Worker (`search_indexer/worker.py`)

#### 3.9.1 Конфигурация и хелперы

- [ ] **`_safe_int`** — корректные значения, пустая строка, невалидная строка → default
- [ ] **`_safe_float`** — корректные значения, пустая строка, невалидная строка → default
- [ ] **`DEDUP_DISTANCE_THRESHOLD`** — значение вне (0.0, 2.0) → fallback на `_SAFE_DEFAULT_DEDUP`
- [ ] **`_vector_literal`** — корректная сериализация вектора в строку `[0.1,0.2,...]`

#### 3.9.2 SQL-запросы (проверка через мок-БД или реальную тестовую БД)

- [ ] **`SQL_FETCH_BATCH`** — SELECT включает колонки `cp.kind` и `cp.updated_at`
- [ ] **`SQL_FETCH_BATCH`** — содержит `FOR UPDATE OF cp SKIP LOCKED`
- [ ] **`SQL_ACTIVATE`** — содержит version-token guard `AND updated_at IS NOT DISTINCT FROM $3`
- [ ] **`SQL_ACTIVATE_GROUP`** — содержит version-token guard `AND updated_at IS NOT DISTINCT FROM $4`
- [ ] **`SQL_ACTIVATE_GROUP_NO_EMBEDDING`** — содержит version-token guard `AND updated_at IS NOT DISTINCT FROM $3`
- [ ] **`SQL_ACTIVATE_NO_EMBEDDING`** — содержит version-token guard `AND updated_at IS NOT DISTINCT FROM $2`

- [ ] **`SQL_FIND_DUPLICATE`** — порог читается из `system_settings` подзапросом, а не параметром
- [ ] **`SQL_FIND_DUPLICATE`** — при отсутствии `dedup_distance_threshold` в `system_settings` используется fallback 0.15
- [ ] **`SQL_FIND_DUPLICATE`** — возвращает ближайшую active-позицию в пределах порога
- [ ] **`SQL_FIND_DUPLICATE`** — не возвращает саму себя (`id <> $2`)
- [ ] **`SQL_FIND_DUPLICATE`** — не возвращает позиции со статусом отличным от `active`
- [ ] **`SQL_INSERT_MERGE`** — новая запись создаётся со статусом `PENDING`
- [ ] **`SQL_INSERT_MERGE`** — при конфликте `(main_position_id, duplicate_position_id)` обновляется `similarity_score`
- [ ] **`SQL_INSERT_MERGE`** — при конфликте статус сбрасывается в `PENDING`, если текущий не терминальный
- [ ] **`SQL_INSERT_MERGE`** — терминальные статусы `MERGED`/`REJECTED` не перезаписываются
- [ ] **`SQL_INSERT_MERGE`** — `updated_at` обновляется при конфликте
- [ ] **`SQL_ACTIVATE`** — status guard: обновляет только `pending_indexing` → `active`
- [ ] **`SQL_ACTIVATE`** — version-token guard: UPDATE 0 строк если `updated_at` изменился (любое поле строки изменено)
- [ ] **`SQL_ACTIVATE_GROUP`** — записывает embedding, лемматизированный `standard_job_title` и `status='active'`
- [ ] **`SQL_ACTIVATE_GROUP`** — status guard: обновляет только `pending_indexing` → `active`
- [ ] **`SQL_ACTIVATE_GROUP`** — version-token guard: UPDATE 0 строк если `updated_at` изменился (description, unit_id, standard_job_title или любое другое поле)
- [ ] **`SQL_ACTIVATE_GROUP_NO_EMBEDDING`** — обновляет `standard_job_title` и `status='active'` без embedding
- [ ] **`SQL_ACTIVATE_GROUP_NO_EMBEDDING`** — status guard: обновляет только `pending_indexing` → `active`
- [ ] **`SQL_ACTIVATE_GROUP_NO_EMBEDDING`** — version-token guard: UPDATE 0 строк если `updated_at` изменился
- [ ] **`SQL_ACTIVATE_NO_EMBEDDING`** — status guard: обновляет только `pending_indexing` → `active`
- [ ] **`SQL_ACTIVATE_NO_EMBEDDING`** — version-token guard: UPDATE 0 строк если `updated_at` изменился после fetch

#### 3.9.3 `run_indexing()` — Phase 1: Fetch

- [ ] **Пустой батч** → возвращает `{"processed": 0, "duplicates": 0, "skipped": 0}`
- [ ] **Батч ограничен `BATCH_SIZE`** → не более N строк
- [ ] **Только `pending_indexing`** строки попадают в выборку
- [ ] **SKIP LOCKED** — два конкурентных воркера получают непересекающиеся наборы строк (интеграционный тест)

#### 3.9.4 `run_indexing()` — Phase 2: Embedding

- [ ] **Позиция с пустым описанием** → skip, `no_description`, активация без embedding
- [ ] **Composite string включает единицу измерения** (если `unit_name` не пуст)
- [ ] **`kind` извлекается из каждой строки** и передаётся в `embed_results`
- [ ] **`description_raw` сохраняется из `row["description"]`** (до `or ""`) — 5-й элемент `embeddable_rows`, 6-й в `embed_results`; в Phase 3 не передаётся в SQL (деструктурируется как `_`)
- [ ] **`updated_at_raw` сохраняется из `row["updated_at"]`** и прокидывается как version token — 6-й элемент `embeddable_rows`, 7-й в `embed_results`
- [ ] **`kind` = NULL или нераспознанное значение** → лемматизация не выполняется, используется стандартный `SQL_ACTIVATE` / `SQL_ACTIVATE_NO_EMBEDDING`
- [ ] **`GROUP_TITLE` — `standard_job_title` лемматизируется** в Phase 2 через `_lemmatize_text()` → spaCy `normalize_job_title_with_lemmatization`
- [ ] **`POSITION` — `standard_job_title` не модифицируется** (уже лемматизирован upstream)
- [ ] **Batch embed** — все тексты отправляются одним вызовом `embed_batch`
- [ ] **Ошибка `embed_batch`** → строки остаются `pending_indexing`, не падает
- [ ] **Несовпадение количества embeddings и текстов** → `ValueError`

#### 3.9.5 `run_indexing()` — Phase 3: Dedup + Activate

- [ ] **Race condition устранён** — порог не кешируется в Python, читается подзапросом в SQL
- [ ] **Дубликат найден** → создаётся запись в `suggested_merges`, `duplicates` +1
- [ ] **Дубликат не найден** → позиция активируется, `processed` +1
- [ ] **`GROUP_TITLE` — используется `SQL_ACTIVATE_GROUP`** с передачей `(emb_literal, title, pos_id, updated_at_raw)`
- [ ] **`GROUP_TITLE` — `standard_job_title` обновляется** лемматизированным значением в БД
- [ ] **`POSITION` — используется стандартный `SQL_ACTIVATE`** с передачей `(emb_literal, pos_id, updated_at_raw)`
- [ ] **Concurrent modification** (status guard) → activate no-op, warning в лог
- [ ] **Early guard до dedup** — `updated_at` изменился до начала транзакции → `suggested_merges` не записывается, строка остаётся `pending_indexing`
- [ ] **Двойной лог исключён** — при срабатывании early guard печатается ровно один warning, `continue` пропускает второй
- [ ] **Version token (Оптимистический guard)** — admin изменил любое поле (description, unit_id, standard_job_title) пока воркер ждёт Gemini → guard срабатывает, строка остаётся `pending_indexing`
- [ ] **Concurrency guard (no_description ветка)** — строка забрана с пустым description → admin заполнил description до Phase 3 → `SQL_ACTIVATE_NO_EMBEDDING` возвращает `UPDATE 0` → строка будет переиндексирована с embedding-ом
- [ ] **Ошибка в транзакции** → строка остаётся `pending_indexing`, не ломает батч
- [ ] **Idempotency** — повторный прогон того же батча не создаёт дубликатов

#### 3.9.6 Жизненный цикл воркера

- [ ] **`initialize()`** — создаёт пул и embedder, логирует параметры
- [ ] **`initialize()`** — невалидный порог из env → **error** лог, fallback, воркер работает
- [ ] **`shutdown()`** — корректно закрывает пул и embedder
- [ ] **`run_indexing()` до `initialize()`** → `RuntimeError`
- [ ] **`fetch_indexing_stats()`** — возвращает `(pending, active)` counts

#### 3.9.7 Обработка GROUP_TITLE

- [ ] **`_lemmatize_text`** — делегирует в `normalize_job_title_with_lemmatization()` из `sanitize_text`
- [ ] **`_lemmatize_text`** — лемматизация через spaCy `ru_core_news_sm` (напр. «монтажные работы» → «монтажный работа»)
- [ ] **`_lemmatize_text`** — пустая строка / `None` → возвращает `None` без исключений
- [ ] **`_lemmatize_text`** — `None` от `normalize_job_title_with_lemmatization` → возвращает `None`; Phase 3 пропускает обновление `standard_job_title` и использует `SQL_ACTIVATE` / `SQL_ACTIVATE_NO_EMBEDDING` вместо `SQL_ACTIVATE_GROUP`, независимо от `kind`
- [ ] **Смешанный батч** — POSITION и GROUP_TITLE в одном батче обрабатываются корректно
- [ ] **GROUP_TITLE с пустым описанием** → `SQL_ACTIVATE_GROUP_NO_EMBEDDING`, title лемматизирован в БД
- [ ] **GROUP_TITLE дубликат** — лемматизированный GROUP_TITLE срабатывает `SQL_FIND_DUPLICATE` → запись в `suggested_merges`, затем `SQL_ACTIVATE_GROUP` активирует с обновлённым title
- [ ] **GROUP_TITLE end-to-end** — лемматизация → embed → dedup → `SQL_ACTIVATE_GROUP` → `active` + обновлённый title в БД
- [ ] **`embed_results` кортежи** содержат `kind`, `description_raw` и `updated_at_raw` для всех строк

### 3.10 Semantic Clusterer Worker (`semantic_clusterer/worker.py`)

#### 3.10.1 Конфигурация

- [ ] **`_safe_int`** — корректные значения, пустая строка, невалидная строка → default
- [ ] **Env-переменные** — `SEMANTIC_CLUSTERER_UMAP_COMPONENTS`, `SEMANTIC_CLUSTERER_HDBSCAN_MIN_SIZE`, `SEMANTIC_CLUSTERER_LLM_TOP_K` корректно парсятся

#### 3.10.2 `_run_ml_pipeline()`

- [ ] **Happy path** — массив embeddings → dict `{label: [indices]}`, выбросы отброшены
- [ ] **Мало данных** — `len(embeddings) < min_cluster_size` → пустой dict
- [ ] **`n_components` capping** — `n_components = min(15, len(data)-1)` при малых данных
- [ ] **Сортировка по probabilities** — члены кластера отсортированы desc по `probabilities_`
- [ ] **Все выбросы** — все метки `-1` → пустой dict
- [ ] **Детерминизм** — `random_state=42` → воспроизводимые результаты при одинаковых данных

#### 3.10.3 `_get_cluster_name()`

- [ ] **Happy path** — LLM возвращает название → stripped строка без кавычек
- [ ] **Пустой ответ LLM** → fallback «Авто-группа»
- [ ] **Ошибка API** → fallback «Авто-группа», warning в лог
- [ ] **Нет `GOOGLE_API_KEY`** → fallback «Авто-группа», warning в лог
- [ ] **Ответ с кавычками** — `"Бетонные работы"` → `Бетонные работы`

#### 3.10.4 `_persist_clusters()`

- [ ] **INSERT GROUP_TITLE** — создаётся строка с `kind='GROUP_TITLE'`, `status='pending_indexing'`
- [ ] **UPDATE parent_id** — все `member_ids` получают `parent_id` = новый `id`
- [ ] **Одна транзакция** — INSERT + UPDATE в одном `conn.transaction()`
- [ ] **Rollback** — ошибка внутри транзакции → ни один INSERT/UPDATE не применяется

#### 3.10.5 `_fetch_positions()`

- [ ] **Фильтрация** — возвращает только `status='active'`, `kind='POSITION'`, `parent_id IS NULL`, `embedding IS NOT NULL`
- [ ] **Пустая выборка** — нет подходящих строк → пустой список

#### 3.10.6 Жизненный цикл

- [ ] **`initialize()`** — создаёт asyncpg pool, `is_initialized = True`
- [ ] **`shutdown()`** — закрывает pool и genai client, `is_initialized = False`
- [ ] **Ленивый genai client** — создаётся при первом вызове `_get_genai_client()`

### 3.11 Semantic Clusterer Tasks (`semantic_clusterer/tasks.py`)

- [ ] **`make_redis()`** — поддерживает `REDIS_URL` и `REDIS_HOST`/`REDIS_PORT`/`REDIS_PASSWORD`
- [ ] **`_safe_set_status`** — ошибка Redis → warning в лог, не raise
- [ ] **`_bump_ttl`** — ошибка Redis → silent pass
- [ ] **`STATUS_TTL_SECONDS`** — читается из env, default 7200

### 3.12 Semantic Clusterer Logger (`semantic_clusterer/logger.py`)

- [ ] **`_JsonFormatter`** — формирует валидный JSON с `ts`, `level`, `logger`, `msg`
- [ ] **`_JsonFormatter`** — `exc_info` → поле `exc` в JSON
- [ ] **`_JsonFormatter`** — кастомные `extra={}` → дополнительные поля в JSON
- [ ] **`get_semantic_clusterer_logger`** — повторный вызов → тот же логгер без повторной настройки
- [ ] **Guard `_semantic_clusterer_configured`** — предотвращает дублирование хендлеров

---

## IV. Интеграционные тесты

### 4.1 Excel → JSON pipeline

- [ ] **`happy_path_single_lot.xlsx` → golden JSON** (snapshot-тест)
- [ ] **`happy_path_multi_lot.xlsx` → golden JSON** (snapshot-тест)
- [ ] **`multi_contractor_3.xlsx` → golden JSON** (snapshot-тест)
- [ ] **`dirty_extra_empty_cols.xlsx`** — парсер не падает, возвращает корректную структуру
- [ ] **`negative_empty.xlsx`** — парсер возвращает пустой/null результат без исключений

### 4.2 FastAPI endpoint

- [ ] **`POST /parse`** с корректным файлом → `200 OK`, JSON-тело
- [ ] **`POST /parse`** с некорректным файлом → `422` или корректное сообщение об ошибке
- [ ] **`POST /parse`** без файла → `422 Unprocessable Entity`

### 4.3 Celery задачи (с eager mode)

- [ ] **Задача парсинга** запускается и завершается в eager mode
- [ ] **Задача Gemini-постобработки** запускается с мок-Gemini в eager mode
- [ ] **Retry-логика** при ошибке Gemini API → задача повторяется нужное число раз

### 4.4 Search Indexer (с тестовой БД + мок Gemini)

- [ ] **Full pipeline** — `pending_indexing` → embed → dedup → `active` (happy path)
- [ ] **Дедупликация** — два похожих описания → запись в `suggested_merges`
- [ ] **Upsert merge** — повторный прогон обновляет `similarity_score`, а не `DO NOTHING`
- [ ] **Терминальные статусы** — `MERGED`/`REJECTED` не перезаписываются upsert-ом
- [ ] **Динамический порог** — изменение `dedup_distance_threshold` в `system_settings` между прогонами влияет на результат
- [ ] **Пустое описание** — позиция активируется без embedding
- [ ] **Ошибка Gemini** — строки остаются `pending_indexing`, следующий прогон подхватывает
- [ ] **GROUP_TITLE pipeline** — `pending_indexing` → лемматизация → embed → dedup → `active` + обновлённый `standard_job_title`
- [ ] **Смешанный батч POSITION + GROUP_TITLE** — оба типа обрабатываются корректно в одном прогоне
- [ ] **SKIP LOCKED — конкурентные воркеры** — два параллельных `run_indexing()` не обрабатывают одни и те же строки (интеграционный тест с реальной БД)
- [ ] **Optimistic guard — admin wins** — строка остаётся `pending_indexing` если запись изменилась (любое поле, обновился `updated_at`) между Phase 1 и Phase 3 (интеграционный тест с реальной БД)

### 4.5 Semantic Clusterer (с тестовой БД + мок Gemini)

- [ ] **Full pipeline** — позиции с embeddings → UMAP → HDBSCAN → LLM naming → INSERT GROUP_TITLE + UPDATE parent_id
- [ ] **Пустая выборка** — нет позиций с embeddings → `clusters_found=0`, без побочных эффектов
- [ ] **Мало позиций** — меньше `min_cluster_size` → HDBSCAN не находит кластеров, `clusters_found=0`
- [ ] **Все выбросы** — HDBSCAN все метки `-1` → `clusters_found=0`
- [ ] **Транзакционность Phase 4** — ошибка в середине persist → все INSERT/UPDATE откатываются
- [ ] **LLM fallback** — Gemini недоступен → кластеры именуются «Авто-группа»
- [ ] **LLM пустой ответ** — Gemini вернул пустую строку → fallback «Авто-группа»
- [ ] **parent_id обновляется** — после persist позиции-члены имеют `parent_id` = id новой группы
- [ ] **GROUP_TITLE создаётся** — новые строки в `catalog_positions` с `kind='GROUP_TITLE'`, `status='pending_indexing'`
- [ ] **Idempotency** — повторный запуск не создаёт дубликатов (позиции уже имеют `parent_id IS NOT NULL`)

### 4.6 Semantic Clusterer Celery-задача (eager mode + мок Redis)

- [ ] **Статус `processing`** — устанавливается при старте задачи
- [ ] **Статус `completed`** — устанавливается при успехе, содержит `clusters_found`
- [ ] **Статус `failed`** — устанавливается при финальной ошибке, содержит `error`
- [ ] **Статус `retrying`** — устанавливается при ретраируемой ошибке, содержит `retry` и `max_retries`
- [ ] **SoftTimeLimitExceeded** — статус `failed`, не ретраится
- [ ] **`_bump_ttl`** — TTL продлевается между фазами
- [ ] **`_safe_set_status`** — ошибка Redis не ломает задачу

---

## V. Контрактные тесты

### 5.1 JSON-схема выходного формата

- [ ] Обязательные ключи присутствуют: `tender_id`, `tender_title`, `lots`
- [ ] `lots` — массив объектов
- [ ] Каждый лот содержит: `lot_number`, `proposals`
- [ ] `proposals` — массив объектов
- [ ] Каждый proposal содержит: `contractor_name`, `items`
- [ ] `items` — массив позиций
- [ ] Числовые поля имеют тип `number` (не `string`)
- [ ] `null` поля явно присутствуют (не опускаются)

---

## VI. Нефункциональные требования

### 6.1 Производительность

- [ ] `make test-fast` завершается за < 30 секунд
- [ ] Парсинг одного типичного файла (≤ 500 строк) < 5 секунд
- [ ] Парсинг большого файла (1000+ строк) < 30 секунд (пометить `@pytest.mark.slow`)

### 6.2 Изоляция

- [ ] Ни один unit-тест не делает реальных HTTP-запросов
- [ ] Ни один unit-тест не читает файлы вне `tests/fixtures/`
- [ ] Ни один unit-тест не использует реальный Gemini API
- [ ] Порядок запуска тестов не влияет на результат

### 6.3 Детерминизм

- [ ] Повторный запуск тестов даёт тот же результат
- [ ] Тесты с датами/временем используют фиксированные значения
- [ ] Тесты с UUID/random используют фиксированный seed

---

## VII. Definition of Done (DoD) для тестового покрытия

### Минимальные пороги

- [ ] `app/excel_parser/` покрытие ≥ 80%
- [ ] `app/gemini_module/` покрытие ≥ 60%
- [ ] `app/go_module/` покрытие ≥ 50%
- [ ] `app/workers/search_indexer/` покрытие ≥ 70%
- [ ] Общее по `app/` покрытие ≥ 65%

### Обязательные условия принятия

- [ ] Все тесты проходят в CI (`make test-coverage` в GitHub Actions)
- [ ] `make check` (форматирование) проходит в CI
- [ ] Ни один тест не помечен как `xfail` без обоснования
- [ ] Все маркеры из `pyproject.toml` используются корректно
- [ ] Тестовые файлы следуют соглашениям об именовании
- [ ] Каждый новый тест имеет явный pytest-маркер
