# Руководство по тестированию

Этот документ описывает, как запускать тесты, добавлять фикстуры, работать с pytest-маркерами и golden-файлами в проекте **Parser Tender XLSX**.

---

## Быстрый старт

```bash
# Установить зависимости
make install

# Запустить все тесты
make test

# Быстрый прогон (без интеграций, останавливается на первой ошибке)
make test-fast

# Тесты с отчётом о покрытии
make test-coverage
```

---

## Структура тестов

```
app/tests/                        # Основные тесты (существующие)
├── conftest.py                   # Общие фикстуры pytest
├── excel_parser/                 # Тесты модуля Excel-парсера
│   ├── test_get_items_dict.py
│   ├── test_get_lot_positions.py
│   ├── test_get_proposals.py
│   ├── test_postprocess.py
│   ├── test_read_contractors.py
│   ├── test_read_executer_block.py
│   ├── test_read_headers.py
│   └── test_sanitize_text.py
└── gemini_module/                # Тесты Gemini-модуля
    ├── test_gemini_logging.py
    ├── test_logging.py
    └── test_processor_logging.py

tests/                            # Целевая структура для новых тестов
├── unit/                         # Юнит-тесты (быстрые, без внешних зависимостей)
├── integration/                  # Интеграционные тесты (требуют API-ключей/сервисов)
├── contract/                     # Контрактные тесты (JSON-схемы, форматы)
└── fixtures/                     # Тестовые данные
    ├── excel/                    # .xlsx-файлы для парсера
    ├── json/                     # Golden JSON-файлы (эталонный вывод)
    └── gemini/                   # Моки ответов Gemini API
```

> Подробное описание фикстур: [`tests/fixtures/README.md`](tests/fixtures/README.md)

---

## Команды Makefile

| Команда | Описание |
|---------|----------|
| `make test` | Запустить все тесты |
| `make test-fast` | Быстрый прогон без интеграций (`-m "not integration and not gemini and not slow"`) |
| `make test-coverage` | Тесты + HTML-отчёт покрытия в `htmlcov/` |
| `make test-integration` | Только интеграционные тесты (`-m "integration"`) |
| `make update-golden` | Пересоздать все golden JSON из `tests/fixtures/excel/*.xlsx` |
| `make test-excel-parser` | Только тесты Excel-парсера |
| `make test-excel-parser-coverage` | Excel-парсер + покрытие |
| `make test-gemini` | Только тесты Gemini-модуля |
| `make test-gemini-coverage` | Gemini-модуль + покрытие |
| `make check` | Проверить форматирование кода (без изменений) |
| `make lint` | Запустить flake8 |
| `make format` | Форматировать код (black + isort) |

---

## pytest-маркеры

Маркеры позволяют запускать подмножества тестов.

| Маркер | Назначение |
|--------|------------|
| `@pytest.mark.unit` | Юнит-тест: быстрый, без внешних зависимостей |
| `@pytest.mark.integration` | Интеграционный тест: требует реальных сервисов/ключей |
| `@pytest.mark.slow` | Медленный тест (> 5 сек) |
| `@pytest.mark.gemini` | Требует реального вызова Gemini API (`GOOGLE_API_KEY`) |
| `@pytest.mark.offline` | Должен работать без сети (для проверки изоляции) |

### Примеры фильтрации

```bash
# Только юнит-тесты
python -m pytest -m "unit"

# Всё, кроме интеграций и Gemini
python -m pytest -m "not integration and not gemini"

# Только медленные тесты
python -m pytest -m "slow"

# Только офлайн-тесты
python -m pytest -m "offline"
```

---

## Работа с фикстурами

### Добавление Excel-фикстуры

1. Поместите файл в `tests/fixtures/excel/` с именем по [правилам именования](tests/fixtures/README.md).
2. Создайте соответствующий golden JSON в `tests/fixtures/json/` (если нужен snapshot-тест).
3. Напишите тест, использующий фикстуру через `pytest.fixture` или параметризацию.

### Обновление golden JSON

Если вывод парсера изменился **намеренно** и изменение валидно:

```bash
# Пересоздать конкретный golden-файл
python -m app.parse tests/fixtures/excel/happy_path_single_lot.xlsx \
  > tests/fixtures/json/happy_path_single_lot.json
```

После обновления golden-файла обязательно укажите причину в commit message.

### Подключение фикстур через conftest.py

Файл `tests/conftest.py` уже создан и предоставляет фикстуры для подключения директорий:

```python
# Использование в тестах — фикстуры доступны автоматически
def test_parse_happy_path(excel_fixtures, json_fixtures):
    xlsx = excel_fixtures / "happy_path_single_lot.xlsx"
    expected = json.loads((json_fixtures / "happy_path_single_lot.json").read_text())
    # ...
```

Доступные фикстуры: `fixtures_dir`, `excel_fixtures`, `json_fixtures`, `gemini_fixtures`.

---

## Мокирование внешних зависимостей

### Gemini API

**Никогда не делайте реальные вызовы Gemini в тестах без маркера `@pytest.mark.gemini`.**

```python
# Пример мока через monkeypatch
import json
import pytest

@pytest.mark.unit
def test_processor_with_mock_gemini(monkeypatch, gemini_fixtures):
    mock_response = json.loads((gemini_fixtures / "response_simple_positions.json").read_text())

    def fake_generate(self, prompt):
        return mock_response

    monkeypatch.setattr("app.gemini_module.processor.GeminiProcessor.generate", fake_generate)
    # ... тест
```

### HTTP / Go API

```python
@pytest.mark.unit
def test_send_json(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **kw: FakeResponse(status_code=200))
    # ... тест
```

### Celery

Для тестирования задач Celery без брокера используйте `CELERY_TASK_ALWAYS_EAGER=True`:

```python
@pytest.fixture(autouse=True)
def celery_eager(monkeypatch):
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
```

### Даты и случайность

```python
import pytest
from unittest.mock import patch
from datetime import datetime

@pytest.fixture
def fixed_now(monkeypatch):
    fixed = datetime(2024, 1, 15, 12, 0, 0)
    with patch("app.excel_parser.read_executer_block.datetime") as mock_dt:
        mock_dt.now.return_value = fixed
        yield fixed
```

---

## CI/CD

GitHub Actions автоматически запускает тесты при push/PR в ветки `main`, `master`, `develop`.

Конфигурация: [`.github/workflows/tests.yml`](.github/workflows/tests.yml)

Шаги CI:
1. Установка Python 3.12 и зависимостей
2. `make check` — проверка форматирования
3. `make test-coverage` — прогон тестов с покрытием
4. Загрузка артефакта `htmlcov/` (хранится 14 дней)

---

## FAQ

**Q: Тест падает с `ImportError`.**
A: Убедитесь, что корень проекта в `PYTHONPATH`. `conftest.py` делает это автоматически при запуске через `pytest`.

**Q: Как пропустить медленные тесты локально?**
A: `make test-fast` или `python -m pytest -m "not slow"`.

**Q: Как запустить только один тест?**
A: `python -m pytest app/tests/excel_parser/test_read_headers.py::test_read_headers_happy_path -v`

**Q: Как посмотреть отчёт покрытия?**
A: После `make test-coverage` откройте `htmlcov/index.html` в браузере.
