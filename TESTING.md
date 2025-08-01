# Тестирование в проекте Parser

## Обзор

Проект использует pytest для автоматизированного тестирования. Все тесты организованы в структурированную иерархию в директории `app/tests/`.

## Структура тестов

```
app/tests/
├── conftest.py                    # Конфигурация pytest
├── __init__.py                    # Инициализация пакета тестов
├── gemini_module/                 # Тесты для gemini_module
│   ├── __init__.py
│   ├── run_tests.py               # Скрипт запуска тестов модуля
│   ├── test_gemini_logging.py     # Интеграционные тесты логгирования
│   ├── test_logging.py            # Модульные тесты логгирования
│   └── test_processor_logging.py  # Тесты логгирования процессора
└── helpers/                       # Тесты для вспомогательных функций
    ├── test_postprocess.py
    ├── test_read_executer_block.py
    └── test_read_headers.py
```

## Команды тестирования (Makefile)

### Основные команды

```bash
# Запуск всех тестов
make test

# Запуск всех тестов с анализом покрытия кода
make test-coverage
```

### Специфичные команды для gemini_module

```bash
# Только тесты gemini_module
make test-gemini

# Тесты gemini_module с покрытием кода
make test-gemini-coverage

# Быстрые тесты только для gemini_module
make test-new
```

### Другие команды

```bash
# Тесты helpers (могут иметь проблемы с импортами)
make test-helpers

# Быстрый запуск с остановкой на первой ошибке
make test-fast
```

## Прямые команды pytest

```bash
# Все тесты с детальным выводом
python -m pytest -v

# Только тесты gemini_module
python -m pytest app/tests/gemini_module/ -v

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

### Текущее покрытие gemini_module:

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

## Проблемы и решения

### Проблемы с импортами в helpers тестах

Существующие тесты в `app/tests/helpers/` имеют проблемы с относительными импортами.

**Решение**: Используйте `make test-new` или `make test-gemini` для тестирования только исправленных модулей.

### Временные файлы тестов

Тесты создают временные лог-файлы в `logs/`. Автоматически очищаются после тестов.

## CI/CD интеграция

Команды Makefile готовы для интеграции в CI/CD пайплайны:

```yaml
# Пример для GitHub Actions
- name: Run tests
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
