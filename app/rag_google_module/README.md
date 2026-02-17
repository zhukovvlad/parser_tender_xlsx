# RAG Google Module

Модуль для работы с Google File Search API (RAG - Retrieval-Augmented Generation) в контексте поиска по каталогу строительных работ.

## 📋 Содержание

- [Назначение](#naznachenie)
- [Архитектура](#arhitektura)
- [Установка](#ustanovka)
- [Конфигурация](#konfiguraciya)
- [Использование](#ispolzovanie)
- [API Reference](#api-reference)
- [Примеры](#primery)
- [Troubleshooting](#troubleshooting)

## <a id="naznachenie"></a>🎯 Назначение

Модуль предоставляет интерфейс для:

1. **Управления корпусом документов** - создание и управление File Search Store для хранения каталога строительных работ
2. **Индексации данных** - загрузка батчей записей в формате JSON с автоматической обработкой
3. **Семантического поиска** - RAG-поиск по корпусу с использованием моделей Gemini

## <a id="arhitektura"></a>🏗️ Архитектура

### Компоненты модуля

```text
rag_google_module/
├── __init__.py              # Публичный API модуля
├── file_search.py           # Основной клиент File Search API
├── config.py               # Конфигурация (RagConfig)
├── client_manager.py       # Управление клиентом GenAI
├── response_parser.py      # Парсинг ответов модели
├── retry.py               # Retry-логика для API
├── logger.py              # Логирование
└── README.md              # Документация
```

### Диаграмма взаимодействия

```text
┌─────────────────┐
│  User Code      │
└────────┬────────┘
         │
         v
┌─────────────────────────────┐
│  FileSearchClient           │
│  - initialize_store()       │
│  - add_batch_to_store()     │
│  - search()                 │
└─────┬───────────────────────┘
      │
      ├──> ClientManager ──> Google GenAI API
      ├──> ResponseParser
      ├──> RagConfig
      └──> Logger
```

## <a id="ustanovka"></a>📦 Установка

### Зависимости

```bash
pip install google-genai google-api-core
```

### Переменные окружения

Создайте `.env` файл в корне проекта:

```env
# Обязательные
GOOGLE_API_KEY=your_api_key_here

# Опциональные
GOOGLE_RAG_STORE_ID=rag-catalog-store
GOOGLE_RAG_MODEL=gemini-2.5-flash
```

## <a id="konfiguraciya"></a>⚙️ Конфигурация

### RagConfig

```python
from app.rag_google_module.config import RagConfig

# Из переменных окружения (по умолчанию)
config = RagConfig.from_env()

# Ручная конфигурация
config = RagConfig(
    api_key="your_api_key",
    store_id="custom-store-id",
    store_display_name="Custom Store Name",
    model_name="gemini-2.5-flash",
    max_tokens_per_chunk=512,
    max_overlap_tokens=0,
    operation_timeout=600,
    max_retries=3
)
```

### Параметры конфигурации

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `api_key` | str | - | Google API ключ (обязательный) |
| `store_id` | str | "rag-catalog-store" | ID хранилища |
| `store_display_name` | str | "Tenders Catalog Store" | Отображаемое имя |
| `model_name` | str | "gemini-2.5-flash" | Модель Gemini |
| `max_tokens_per_chunk` | int | 512 | Макс. токенов в чанке |
| `max_overlap_tokens` | int | 0 | Перекрытие чанков |
| `operation_timeout` | int | 600 | Таймаут операций (сек) |
| `max_retries` | int | 3 | Попыток при ошибке |

## <a id="ispolzovanie"></a>🚀 Использование

### Базовый пример

```python
import asyncio
from app.rag_google_module import FileSearchClient

async def main():
    # Инициализация клиента
    client = FileSearchClient()
    
    # Инициализация Store
    await client.initialize_store()
    
    # Загрузка данных
    catalog_data = [
        {
            "catalog_id": 1,
            "name": "Земляные работы",
            "description": "Разработка грунта экскаватором"
        },
        {
            "catalog_id": 2,
            "name": "Бетонные работы",
            "description": "Укладка бетона в фундамент"
        }
    ]
    
    await client.add_batch_to_store(catalog_data)
    
    # Поиск
    results = await client.search("разработка грунта")
    
    for result in results:
        print(f"ID: {result['catalog_id']}, Score: {result['score']}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Продвинутый пример с обработкой ошибок

```python
import asyncio
from app.rag_google_module import FileSearchClient
from app.rag_google_module.config import RagConfig
from google.api_core import exceptions as google_exceptions

async def advanced_search():
    # Кастомная конфигурация
    config = RagConfig.from_env()
    config.max_retries = 5
    
    client = FileSearchClient(config)
    
    try:
        await client.initialize_store()
        
        # Поиск с проверкой результатов
        query = "укладка бетона"
        results = await client.search(query)
        
        if not results:
            print(f"Ничего не найдено по запросу: {query}")
            return
        
        # Сортировка по релевантности
        sorted_results = sorted(
            results, 
            key=lambda x: x.get('score', 0), 
            reverse=True
        )
        
        print(f"Найдено {len(sorted_results)} результатов:")
        for i, result in enumerate(sorted_results, 1):
            print(f"{i}. ID: {result['catalog_id']}, "
                  f"Score: {result['score']:.2f}")
    
    except google_exceptions.PermissionDenied:
        print("Ошибка: Недостаточно прав для Google API")
    except TimeoutError:
        print("Ошибка: Превышен таймаут операции")
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")

asyncio.run(advanced_search())
```

### Батчевая загрузка больших объемов

```python
async def upload_large_catalog():
    client = FileSearchClient()
    await client.initialize_store()
    
    # Загружаем батчами по 100 записей
    BATCH_SIZE = 100
    
    for i in range(0, len(full_catalog), BATCH_SIZE):
        batch = full_catalog[i:i + BATCH_SIZE]
        
        print(f"Загрузка батча {i//BATCH_SIZE + 1}...")
        await client.add_batch_to_store(batch)
        
        # Небольшая пауза между батчами
        await asyncio.sleep(2)
    
    print("Загрузка завершена!")
```

## <a id="api-reference"></a>📚 API Reference

### FileSearchClient

#### `__init__(config: Optional[RagConfig] = None)`

Инициализирует клиент File Search.

**Параметры:**
- `config` (Optional[RagConfig]): Конфигурация. Если не указана, загружается из env.

**Пример:**
```python
client = FileSearchClient()
# или
client = FileSearchClient(config=custom_config)
```

---

#### `async initialize_store() -> None`

Инициализирует или находит существующий File Search Store.

**Raises:**
- `google_exceptions.PermissionDenied`: Недостаточно прав
- `RuntimeError`: Ошибка при создании Store

**Пример:**
```python
await client.initialize_store()
```

---

#### `async add_batch_to_store(records: List[Dict]) -> None`

Загружает батч записей в Store.

**Параметры:**
- `records` (List[Dict]): Список словарей для индексации

**Raises:**
- `RuntimeError`: Store не инициализирован
- `TimeoutError`: Превышен таймаут операции

**Пример:**
```python
data = [{"catalog_id": 1, "name": "Item 1"}]
await client.add_batch_to_store(data)
```

---

#### `async search(query: str) -> Optional[List[Dict[str, Any]]]`

Выполняет RAG-поиск по корпусу.

**Параметры:**
- `query` (str): Поисковый запрос

**Returns:**
- `Optional[List[Dict]]`: Список результатов с полями `catalog_id` и `score`

**Raises:**
- `RuntimeError`: Store не инициализирован
- `ServerError`: Ошибка сервера Google (с автоматическим retry)

**Пример:**
```python
results = await client.search("бетонные работы")
for result in results:
    print(result['catalog_id'], result['score'])
```

---

### SearchResponseParser

#### `SearchResponseParser.parse_search_results(response_text: str) -> List[Dict[str, Any]]`

Парсит JSON-ответ модели.

**Параметры:**
- `response_text` (str): Текстовый ответ от модели

**Returns:**
- `List[Dict]`: Список результатов с нормализованной структурой

**Пример:**
```python
parser = SearchResponseParser()
results = parser.parse_search_results(response_text)
```

---

### ClientManager

#### `async get_client() -> AsyncContextManager[genai.Client]`

Context manager для управления Google GenAI клиентом.

**Пример:**
```python
manager = ClientManager(api_key)
async with manager.get_client() as client:
    # Работа с клиентом
    pass
```

---

### Декоратор retry_on_server_error

```python
@retry_on_server_error(max_attempts=3)
async def my_api_call():
    # Код с возможными ServerError
    pass
```

Автоматически повторяет вызов при `ServerError` с экспоненциальной задержкой.

## <a id="primery"></a>💡 Примеры

### Интеграция с Celery

```python
from celery import shared_task
from app.rag_google_module import FileSearchClient

@shared_task
def search_in_catalog(query: str) -> list:
    """Celery task для поиска в каталоге."""
    import asyncio
    
    async def _search():
        client = FileSearchClient()
        await client.initialize_store()
        return await client.search(query)
    
    return asyncio.run(_search())
```

### Использование с FastAPI

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from app.rag_google_module import FileSearchClient

client = FileSearchClient()

@asynccontextmanager
async def lifespan(app):
    await client.initialize_store()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/search")
async def search_catalog(q: str):
    results = await client.search(q)
    if not results:
        raise HTTPException(status_code=404, detail="No results found")
    return {"results": results}
```

### Кастомный промпт для поиска

```python
class CustomFileSearchClient(FileSearchClient):
    def _build_search_prompt(self, query: str) -> str:
        """Переопределяем промпт для специфичных задач."""
        return f"""
Ты — эксперт по строительным работам.
Найди ПЯТЬ (5) наиболее подходящих позиций для: "{query}"

Учитывай синонимы и схожие термины.
Верни JSON:
[
    {{"catalog_id": 123, "score": 0.95, "reason": "точное совпадение"}},
    ...
]
"""

# Использование
custom_client = CustomFileSearchClient()
```

## <a id="troubleshooting"></a>🐛 Troubleshooting

### Ошибка: "GOOGLE_API_KEY не установлен"

**Решение:** Убедитесь, что файл `.env` существует и содержит валидный API ключ:
```bash
echo "GOOGLE_API_KEY=your_key_here" > .env
```

---

### Ошибка: PermissionDenied (403)

**Причины:**
1. Невалидный API ключ
2. API не активирован в Google Cloud Console
3. Превышена квота

**Решение:**
1. Проверьте ключ в [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Активируйте Generative Language API
3. Проверьте квоты и биллинг

---

### Ошибка: TimeoutError при загрузке

**Решение:** Увеличьте таймаут в конфигурации:
```python
config = RagConfig.from_env()
config.operation_timeout = 1200  # 20 минут
client = FileSearchClient(config)
```

---

### Поиск не возвращает результаты

**Проверьте:**
1. Store инициализирован: `await client.initialize_store()`
2. Данные загружены: `await client.add_batch_to_store(data)`
3. Подождите 1-2 минуты после загрузки (индексация)

---

### Низкая релевантность результатов

**Улучшение:**
1. Добавьте больше контекста в данные
2. Увеличьте `max_tokens_per_chunk` в конфигурации
3. Настройте кастомный промпт (см. примеры выше)

---

## 📝 Логирование

Модуль использует стандартный Python logging:

```python
import logging

# Включить debug логи
logging.getLogger("rag_google_module").setLevel(logging.DEBUG)

# Настроить формат
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logging.getLogger("rag_google_module").addHandler(handler)
```

## 🔒 Безопасность

1. **Никогда не коммитьте `.env` файл** с API ключами
2. Используйте переменные окружения для production
3. Ограничьте права API ключа только необходимыми API
4. Регулярно ротируйте ключи

## 🧪 Тестирование

```python
# tests/test_file_search.py
import pytest
from unittest.mock import AsyncMock, patch
from app.rag_google_module import FileSearchClient

@pytest.mark.asyncio
async def test_search():
    client = FileSearchClient()
    client._store_name = "test-store"  # bypass initialize_store

    fake_response = AsyncMock()
    fake_response.text = '[{"catalog_id": 1, "score": 0.95}]'

    with patch.object(
        client.client_manager, 'get_client'
    ) as mock_ctx:
        mock_client = AsyncMock()
        mock_client.models.generate_content.return_value = fake_response
        mock_ctx.return_value.__aenter__.return_value = mock_client

        results = await client.search("test query")
        assert len(results) == 1
        assert results[0]["catalog_id"] == 1
        assert results[0]["score"] == 0.95
```

## 📄 Лицензия

Внутренний модуль проекта parser_tender_xlsx.

## 🤝 Contributing

При внесении изменений:
1. Следуйте существующему стилю кода
2. Добавляйте docstrings для новых функций
3. Обновляйте эту документацию
4. Добавляйте тесты для новой функциональности

---

**Версия документации:** 1.0.0  
**Дата обновления:** 16.02.2026
