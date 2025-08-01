# Тестирование в проекте Parser

## Обзор

Проект использует pytest для автоматизированного тестирования. Все тесты организованы в структурированную иерархию в директории `app/tests/`.

## Структура тестов

```
app/tests/
├── conftest.py                       # Конфигурация pytest
├── __init__.py                       # Инициализация пакета тестов
├── excel_parser/                     # Тесты для excel_parser модуля
│   ├── __init__.py
│   ├── test_postprocess.py           # Тесты постобработки данных
│   ├── test_read_executer_block.py   # Тесты чтения блока исполнителя
│   └── test_read_headers.py          # Тесты чтения заголовков Excel
└── gemini_module/                    # Тесты для gemini_module
    ├── __init__.py
    ├── run_tests.py                  # Скрипт запуска тестов модуля
    ├── test_gemini_logging.py        # Интеграционные тесты логгирования
    ├── test_logging.py               # Модульные тесты логгирования
    └── test_processor_logging.py     # Тесты логгирования процессора
```

## Команды тестирования (Makefile)

### Основные команды

```bash
# Запуск всех тестов
make test

# Запуск всех тестов с анализом покрытия кода
make test-coverage
```

### Специфичные команды для модулей

```bash
# Только тесты excel_parser
make test-excel-parser

# Тесты excel_parser с покрытием кода
make test-excel-parser-coverage

# Только тесты gemini_module
make test-gemini

# Тесты gemini_module с покрытием кода
make test-gemini-coverage

# Быстрые тесты только для gemini_module
make test-new
```

### Другие команды

```bash
# Быстрый запуск с остановкой на первой ошибке
make test-fast
```

## Прямые команды pytest

```bash
# Все тесты с детальным выводом
python -m pytest -v

# Только тесты excel_parser
python -m pytest app/tests/excel_parser/ -v

# Только тесты gemini_module
python -m pytest app/tests/gemini_module/ -v

# С покрытием кода для excel_parser
python -m pytest app/tests/excel_parser/ --cov=app.excel_parser --cov-report=html -v

# С покрытием кода для gemini_module
python -m pytest app/tests/gemini_module/ --cov=app.gemini_module --cov-report=html -v

# Быстрый запуск (остановка на первой ошибке)
python -m pytest -x --tb=short

# Запуск конкретного теста
python -m pytest app/tests/gemini_module/test_logging.py::test_setup_gemini_logger -v
```

## Покрытие кода

Проект использует pytest-cov для анализа покрытия кода. Отчеты генерируются в двух форматах:

- **Терминал**: сводная таблица покрытия
- **HTML**: подробный отчет в директории `htmlcov/`

### Текущее покрытие модулей:

**excel_parser модуль:**

- `postprocess.py`: 100% покрытие
- `read_headers.py`: 100% покрытие
- `read_executer_block.py`: 95% покрытие
- Другие модули: частичное покрытие (требуют доработки тестов)

**gemini_module:**

- `logger.py`: 94% покрытие
- `__init__.py`: 100% покрытие
- Тесты: 90%+ покрытие

## Конфигурация

### pytest.ini / pyproject.toml

Настройки pytest определены в `pyproject.toml`:

- Директории тестов: `tests`, `app/tests`
- Плагины: coverage, mock, html и др.

### conftest.py

Автоматически добавляет корень проекта в Python path для корректных импортов.

## Архитектура тестов

### excel_parser тесты

Модуль excel_parser имеет полноценные модульные тесты:

- **test_postprocess.py** (24 теста): тестирует постобработку данных Excel
- **test_read_executer_block.py** (11 тестов): тестирует чтение блока исполнителя
- **test_read_headers.py** (12 тестов): тестирует чтение заголовков Excel

### gemini_module тесты

Модуль gemini_module имеет комплексные тесты логгирования:

- **test_logging.py** (4 теста): базовые тесты настройки логгера
- **test_gemini_logging.py** (1 тест): интеграционный тест
- **test_processor_logging.py** (1 тест): тест логгирования процессора

## Статистика тестов

**Общее количество тестов: 53**

- excel_parser: 47 тестов
- gemini_module: 6 тестов

**Время выполнения:**

- Все тесты: ~9 секунд
- excel_parser: ~5 секунд
- gemini_module: ~4 секунды

## CI/CD интеграция

Команды Makefile готовы для интеграции в CI/CD пайплайны:

```yaml
# Пример для GitHub Actions
- name: Run all tests
  run: make test

- name: Run excel parser tests
  run: make test-excel-parser-coverage

- name: Run gemini tests
  run: make test-gemini-coverage

- name: Upload coverage
  uses: actions/upload-artifact@v2
  with:
    name: coverage-report
    path: htmlcov/
```

## Добавление новых тестов

1. Создайте файл `test_*.py` в соответствующей директории
2. Используйте стандартные assert-ы pytest
3. Добавьте docstring с описанием теста
4. Проверьте импорты через `conftest.py`
5. Запустите тесты командой `make test-new`

## Лучшие практики

- ✅ Используйте описательные имена тестов
- ✅ Каждый тест должен тестировать одну функциональность
- ✅ Очищайте временные файлы после тестов
- ✅ Используйте фикстуры для повторяющейся настройки
- ✅ Добавляйте docstring к тестовым функциям
- ✅ Покрытие кода должно быть > 80%
