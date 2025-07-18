# Makefile для управления Python-сервисом парсера

# .PHONY гарантирует, что make выполнит команду, даже если в директории
# уже есть файл или папка с таким же именем (например, "run").
.PHONY: run help install test clean dev prod parse parse-offline sync-pending lint format check-types coverage

# Определяем переменные по умолчанию для удобства.
# Эти значения можно переопределить в Makefile.local
APP_MODULE = main:app
HOST = 0.0.0.0
PORT = 9000
RELOAD = --reload
PYTHON = python
PIP = pip

# Подключаем локальные настройки, если файл существует
-include Makefile.local

# Команда по умолчанию, которая будет выполняться, если просто написать "make"
default: help

# Основная команда для запуска сервера в режиме разработки
run:
	@echo "Запуск Uvicorn сервера на http://$(HOST):$(PORT)"
	@uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT) $(RELOAD)

# Запуск в продакшн режиме (без автоперезагрузки)
prod:
	@echo "Запуск Uvicorn сервера в продакшн режиме на http://$(HOST):$(PORT)"
	@uvicorn $(APP_MODULE) --host $(HOST) --port $(PORT)

# Установка зависимостей
install:
	@echo "Установка зависимостей..."
	@$(PIP) install -r requirements.txt

# Установка зависимостей для разработки
install-dev:
	@echo "Установка зависимостей для разработки..."
	@$(PIP) install -r requirements.txt
	@$(PIP) install black flake8 mypy isort

# Запуск тестов
test:
	@echo "Запуск тестов..."
	@$(PYTHON) -m pytest -v

# Запуск тестов с покрытием кода
coverage:
	@echo "Запуск тестов с покрытием кода..."
	@$(PYTHON) -m pytest --cov=app --cov=tools --cov-report=html --cov-report=term-missing -v

# Линтинг кода
lint:
	@echo "Проверка кода с помощью flake8..."
	@flake8 app/ tools/ tests/ --max-line-length=100 --ignore=E501,W503

# Форматирование кода
format:
	@echo "Форматирование кода с помощью black..."
	@black app/ tools/ tests/ --line-length=100
	@echo "Сортировка импортов с помощью isort..."
	@isort app/ tools/ tests/ --profile black

# Проверка типов
check-types:
	@echo "Проверка типов с помощью mypy..."
	@mypy app/ tools/ --ignore-missing-imports

# Комплексная проверка качества кода
check: lint check-types test
	@echo "Все проверки качества кода выполнены"

# Очистка временных файлов
clean:
	@echo "Очистка временных файлов..."
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -delete
	@rm -rf htmlcov/
	@rm -rf .coverage
	@rm -rf .pytest_cache/
	@rm -rf .mypy_cache/
	@rm -rf temp_uploads/
	@echo "Временные файлы очищены"

# Очистка выходных файлов
clean-output:
	@echo "Очистка выходных файлов..."
	@rm -rf tenders_xlsx/
	@rm -rf tenders_json/
	@rm -rf tenders_md/
	@rm -rf tenders_chunks/
	@rm -rf tenders_positions/
	@rm -rf pending_sync/
	@rm -rf logs/
	@echo "Выходные файлы очищены"

# Полная очистка
clean-all: clean clean-output
	@echo "Полная очистка выполнена"

# Парсинг одного файла (использование: make parse FILE=path/to/file.xlsx)
parse:
	@if [ -z "$(FILE)" ]; then \
		echo "Ошибка: Укажите файл для парсинга. Использование: make parse FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "Парсинг файла: $(FILE)"
	@$(PYTHON) -m app.parse "$(FILE)"

# Парсинг в offline режиме (работает без подключения к серверу)
parse-offline:
	@if [ -z "$(FILE)" ]; then \
		echo "Ошибка: Укажите файл для парсинга. Использование: make parse-offline FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "Парсинг файла в offline режиме: $(FILE)"
	@PARSER_FALLBACK_MODE=true $(PYTHON) -m app.parse "$(FILE)"

# Анализ лотов с помощью LLM
analyze-llm:
	@echo "Запуск анализа лотов с помощью LLM..."
	@$(PYTHON) tools/llm_analyzer.py

# Синхронизация файлов из pending_sync с сервером (будет реализовано отдельно)
sync-pending:
	@echo "Синхронизация ожидающих файлов с сервером..."
	@echo "TODO: Реализовать утилиту синхронизации"

# Создание виртуального окружения
venv:
	@echo "Создание виртуального окружения..."
	@$(PYTHON) -m venv venv
	@echo "Активируйте окружение: source venv/bin/activate (Linux/Mac) или venv\\Scripts\\activate (Windows)"

# Настройка окружения для разработки
setup-dev: venv
	@echo "Настройка окружения для разработки..."
	@. venv/bin/activate && $(PIP) install -r requirements.txt
	@. venv/bin/activate && $(PIP) install black flake8 mypy isort
	@echo "Окружение настроено. Активируйте его: source venv/bin/activate"

# Генерация отчета о покрытии кода
coverage-report:
	@echo "Генерация отчета о покрытии кода..."
	@$(PYTHON) -m pytest --cov=app --cov=tools --cov-report=html --cov-report=term-missing
	@echo "Отчет сгенерирован в htmlcov/index.html"

# Профилирование производительности
profile:
	@if [ -z "$(FILE)" ]; then \
		echo "Ошибка: Укажите файл для профилирования. Использование: make profile FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "Профилирование парсера для файла: $(FILE)"
	@$(PYTHON) -m cProfile -o profile_results.prof -m app.parse "$(FILE)"
	@echo "Результаты профилирования сохранены в profile_results.prof"

# Проверка безопасности зависимостей
security-check:
	@echo "Проверка безопасности зависимостей..."
	@$(PIP) install safety || true
	@safety check

# Обновление зависимостей
update-deps:
	@echo "Обновление зависимостей..."
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt --upgrade

# Экспорт зависимостей
freeze:
	@echo "Экспорт текущих зависимостей..."
	@$(PIP) freeze > requirements-freeze.txt
	@echo "Зависимости экспортированы в requirements-freeze.txt"

# Проверка стиля кода
style-check:
	@echo "Проверка стиля кода..."
	@black --check app/ tools/ tests/ --line-length=100
	@isort --check-only app/ tools/ tests/ --profile black
	@flake8 app/ tools/ tests/ --max-line-length=100 --ignore=E501,W503

# Автоматическое исправление стиля кода
style-fix:
	@echo "Автоматическое исправление стиля кода..."
	@black app/ tools/ tests/ --line-length=100
	@isort app/ tools/ tests/ --profile black

# Команда для вывода справки по доступным командам
help:
	@echo "Доступные команды:"
	@echo ""
	@echo "=== Запуск сервера ==="
	@echo "  make run         - Запустить веб-сервер в режиме разработки с автоперезагрузкой"
	@echo "  make prod        - Запустить веб-сервер в продакшн режиме"
	@echo ""
	@echo "=== Управление зависимостями ==="
	@echo "  make install     - Установить зависимости из requirements.txt"
	@echo "  make install-dev - Установить зависимости для разработки"
	@echo "  make update-deps - Обновить все зависимости"
	@echo "  make freeze      - Экспортировать текущие зависимости"
	@echo ""
	@echo "=== Парсинг и анализ ==="
	@echo "  make parse FILE=<path>        - Парсить указанный XLSX файл"
	@echo "  make parse-offline FILE=<path> - Парсить файл в offline режиме"
	@echo "  make analyze-llm              - Анализ лотов с помощью LLM"
	@echo "  make sync-pending             - Синхронизировать файлы из pending_sync"
	@echo ""
	@echo "=== Тестирование ==="
	@echo "  make test        - Запустить тесты"
	@echo "  make coverage    - Запустить тесты с покрытием кода"
	@echo "  make coverage-report - Сгенерировать отчет о покрытии"
	@echo ""
	@echo "=== Качество кода ==="
	@echo "  make lint        - Проверить код с помощью flake8"
	@echo "  make format      - Отформатировать код с помощью black и isort"
	@echo "  make check-types - Проверить типы с помощью mypy"
	@echo "  make check       - Выполнить все проверки качества"
	@echo "  make style-check - Проверить стиль кода"
	@echo "  make style-fix   - Автоматически исправить стиль кода"
	@echo ""
	@echo "=== Очистка ==="
	@echo "  make clean       - Очистить временные файлы"
	@echo "  make clean-output - Очистить выходные файлы"
	@echo "  make clean-all   - Полная очистка"
	@echo ""
	@echo "=== Разработка ==="
	@echo "  make venv        - Создать виртуальное окружение"
	@echo "  make setup-dev   - Настроить окружение для разработки"
	@echo "  make profile FILE=<path> - Профилировать производительность"
	@echo "  make security-check - Проверить безопасность зависимостей"
	@echo ""
	@echo "=== Персонализация ==="
	@echo "  Создайте файл Makefile.local для переопределения настроек"
	@echo "  Пример содержимого Makefile.local:"
	@echo "    HOST = 127.0.0.1"
	@echo "    PORT = 8080"
	@echo "    PYTHON = python3"
	@echo ""
	@echo "=== Переменные окружения ==="
	@echo "  PARSER_FALLBACK_MODE=true  - Включить резервный режим"
	@echo "  GO_SERVER_API_ENDPOINT     - URL API сервера"
	@echo "  GO_SERVER_API_KEY          - API ключ для сервера"
	@echo "  OLLAMA_URL                 - URL для LLM сервера"
	@echo "  OLLAMA_MODEL               - Модель LLM для использования"

