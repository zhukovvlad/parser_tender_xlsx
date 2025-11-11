# RAG Catalog Worker

Асинхронный воркер для автоматического сопоставления и дедупликации позиций тендеров с использованием Google File Search (RAG).

## Назначение

Модуль решает две ключевые задачи:

1. **Сопоставление (Matcher)** - автоматическое связывание новых позиций из тендеров с существующим каталогом
2. **Очистка (Cleaner)** - дедупликация и оптимизация каталога позиций

## Архитектура

```
rag_catalog/
├── __init__.py          # Инициализация модуля
├── logger.py            # Специализированный логгер (logs/rag_catalog.log)
├── tasks.py             # Celery задачи для периодического выполнения
├── worker.py            # Бизнес-логика RAG-воркера
└── README.md            # Документация
```

### Взаимодействие с другими модулями

```
┌─────────────────┐
│   Celery Beat   │ (расписание задач)
└────────┬────────┘
         │
         ├─── Каждые 5 минут ──→ run_matching_task
         └─── Раз в сутки (3:00) ──→ run_cleaning_task
                                            ↓
                                    ┌───────────────┐
                                    │   RagWorker   │
                                    └───┬───────┬───┘
                                        │       │
                        ┌───────────────┘       └──────────────┐
                        ↓                                       ↓
            ┌─────────────────────┐                 ┌──────────────────────┐
            │  GoApiClient (HTTP) │                 │  FileSearchClient    │
            │  ↕ PostgreSQL       │                 │  ↕ Google Gemini AI  │
            └─────────────────────┘                 └──────────────────────┘
```

## Процессы

### Процесс 1: Инициализация кэша (Startup)

**Когда:** При первом запуске `run_cleaning_task`

**Действия:**
1. Получает весь каталог из Go-бэкенда
2. Создает JSONL-файл для Google File Search
3. Индексирует данные в Google AI
4. Помечает записи как проиндексированные

**Результат:** Готовый RAG-индекс для быстрого поиска

### Процесс 2: Сопоставление (Matcher)

**Расписание:** Каждые 5 минут

**Задача:** `run_matching_task`

**Алгоритм:**
```python
1. Получить необработанные позиции (catalog_position_id IS NULL)
2. Для каждой позиции:
   a. Сформировать поисковый запрос из rich_context_string
   b. Выполнить AI-поиск в каталоге через FileSearchClient
   c. Если найдено совпадение → связать position_item с catalog_position
   d. Обновить запись в БД через GoApiClient
3. Вернуть статистику: {processed: N, matched: M}
```

**Условия работы:**
- Каталог должен быть инициализирован (`is_catalog_initialized = True`)
- Если кэш не готов → задача пропускается с предупреждением

### Процесс 3: Очистка (Cleaner)

**Расписание:** Раз в сутки в 3:00 ночи

**Задача:** `run_cleaning_task`

**Алгоритм:**

**Часть А: Переиндексация**
```python
if force_reindex OR first_run:
    # Полная переиндексация каталога
    initialize_catalog_cache()
```

**Часть Б: Дедупликация** (TODO)
```python
1. Для каждого элемента каталога:
   a. Искать похожие элементы через AI-поиск
   b. Если найден дубликат (score > SUGGEST_THRESHOLD):
      - Создать предложение на слияние
      - Отправить в Go-бэкенд для ручной проверки
2. Вернуть статистику слияний
```

## Конфигурация

### Переменные окружения

```bash
# Пороги схожести для сопоставления
RAG_MATCHING_THRESHOLD=0.95    # Минимальный порог для автосопоставления
RAG_SUGGEST_THRESHOLD=0.98     # Порог для предложения слияния

# Go API
GO_API_URL=http://localhost:8080
GO_API_KEY=your_api_key

# Google Gemini
GOOGLE_API_KEY=your_gemini_key

# Логирование
LOG_DIR=logs
```

### Расписание Celery Beat

Конфигурация в `app/celery_app.py`:

```python
celery_app.conf.beat_schedule = {
    'run-rag-matcher': {
        'task': 'app.workers.rag_catalog.tasks.run_matching_task',
        'schedule': crontab(minute='*/5'),  # Каждые 5 минут
    },
    'run-rag-cleaner': {
        'task': 'app.workers.rag_catalog.tasks.run_cleaning_task',
        'schedule': crontab(minute='0', hour='3'),  # 3:00 ночи
    },
}
```

## Использование

### Запуск воркера

```bash
# Запуск Celery воркера
celery -A app.celery_app worker --loglevel=info

# Запуск Celery Beat (планировщик)
celery -A app.celery_app beat --loglevel=info
```

### Ручной запуск задач

```python
from app.workers.rag_catalog.tasks import run_matching_task, run_cleaning_task

# Запустить сопоставление вручную
result = run_matching_task.delay()
print(result.get())

# Запустить очистку с полной переиндексацией
result = run_cleaning_task.delay(force_reindex=True)
print(result.get())
```

### Использование RagWorker напрямую

```python
import asyncio
from app.workers.rag_catalog import RagWorker

async def main():
    worker = RagWorker()
    
    # Инициализация
    await worker.initialize_catalog_cache()
    
    # Сопоставление
    result = await worker.run_matcher()
    print(f"Matched: {result['matched']} из {result['processed']}")
    
    # Очистка
    result = await worker.run_cleaner(force_reindex=False)
    print(f"Suggested merges: {result['suggested_merges']}")

asyncio.run(main())
```

## Логирование

Логи записываются в `logs/rag_catalog.log` со следующей структурой:

```
2025-11-11 15:30:00 - rag_catalog.tasks - INFO - RAG Worker инициализирован
2025-11-11 15:35:00 - rag_catalog.worker - INFO - Процесс 2: Найдено 45 позиций для сопоставления
2025-11-11 15:35:15 - rag_catalog.worker - INFO - Найдено совпадение! Item 12345 -> Catalog 678
2025-11-11 15:35:30 - rag_catalog.tasks - INFO - Задача Matcher завершена: {'matched': 42, 'processed': 45}
```

### Уровни логирования

- **DEBUG** - детальная информация о поиске и сопоставлении
- **INFO** - основные события (старт/завершение задач, статистика)
- **WARNING** - пропущенные совпадения, отложенные задачи
- **ERROR** - ошибки обработки отдельных элементов
- **CRITICAL** - фатальные ошибки инициализации

## API Reference

### RagWorker

#### Методы

**`__init__()`**
- Инициализирует воркер, создает клиенты для Go API и Google File Search

**`async initialize_catalog_cache() -> None`**
- Загружает весь каталог и создает RAG-индекс
- Устанавливает `is_catalog_initialized = True` при успехе

**`async run_matcher() -> dict`**
- Сопоставляет необработанные позиции с каталогом
- Возвращает: `{"status": "success", "processed": int, "matched": int}`

**`async run_cleaner(force_reindex: bool = False) -> dict`**
- Переиндексирует каталог и ищет дубликаты
- Возвращает: `{"status": "success", "reindexed": bool, "suggested_merges": int}`

### Celery Tasks

**`run_matching_task()`**
- Синхронная обертка над `RagWorker.run_matcher()`
- Автоматически вызывается Celery Beat каждые 5 минут

**`run_cleaning_task(force_reindex: bool = False)`**
- Синхронная обертка над `RagWorker.run_cleaner()`
- Автоматически вызывается Celery Beat в 3:00

## Зависимости

- `GoApiClient` - HTTP-клиент для взаимодействия с Go-бэкендом
- `FileSearchClient` - клиент для Google Gemini File Search API
- `celery` - система очередей для фоновых задач
- `asyncio` - асинхронное выполнение

## Мониторинг

Для мониторинга выполнения задач используйте Flower:

```bash
celery -A app.celery_app flower --port=5555
```

Откройте http://localhost:5555 для просмотра:
- Статуса воркеров
- Истории выполнения задач
- Графиков производительности

## Troubleshooting

### Задача Matcher постоянно пропускается

**Причина:** Каталог не инициализирован

**Решение:**
```python
# Запустите очистку вручную для инициализации
from app.workers.rag_catalog.tasks import run_cleaning_task
run_cleaning_task.delay(force_reindex=True)
```

### Низкий процент совпадений

**Причина:** Недостаточное качество `rich_context_string`

**Решение:**
- Проверьте формирование контекстных строк в Go-бэкенде
- Убедитесь, что строки содержат достаточно деталей для поиска
- Настройте `RAG_MATCHING_THRESHOLD` (по умолчанию 0.95)

### Ошибки подключения к Google AI

**Причина:** Проблемы с API ключом или квотами

**Решение:**
- Проверьте `GOOGLE_API_KEY` в `.env`
- Убедитесь, что API включен в Google Cloud Console
- Проверьте квоты: https://console.cloud.google.com/apis/api/generativelanguage.googleapis.com/quotas

## Roadmap

- [ ] Реализовать логику дедупликации в `run_cleaner`
- [ ] Добавить метрики (Prometheus/StatsD)
- [ ] Добавить retry-механизм для Go API
- [ ] Реализовать инкрементальную индексацию
- [ ] Добавить unit-тесты
- [ ] Добавить webhook для уведомлений о предложенных слияниях

## Версии

- **v1.0.0** - Базовая функциональность matcher + cleaner с ленивой инициализацией
