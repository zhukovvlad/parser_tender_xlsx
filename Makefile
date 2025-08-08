# Makefile для управления Python-сервисом парсера

# .PHONY гарантирует, что make выполнит команду, даже если в директории
# уже есть файл или папка с таким же именем (например, "run").
.PHONY: run help install test test-coverage test-gemini test-gemini-coverage test-excel-parser test-excel-parser-coverage test-fast test-new clean dev prod parse parse-offline parse-gemini parse-gemini-async worker-start worker-status sync-pending format lint check

# Определяем переменные по умолчанию для удобства.
# Эти значения можно переопределить в Makefile.local
APP_MODULE = main:app
HOST = 0.0.0.0
PORT = 9000
RELOAD = --reload

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
	@pip install -r requirements.txt

# Запуск всех тестов
test:
	@echo "Запуск всех тестов..."
	@python -m pytest -v

# Запуск тестов с покрытием кода
test-coverage:
	@echo "Запуск тестов с анализом покрытия кода..."
	@python -m pytest --cov=app --cov-report=html --cov-report=term -v

# Запуск только тестов gemini_module
test-gemini:
	@echo "Запуск тестов для gemini_module..."
	@python -m pytest app/tests/gemini_module/ -v

# Запуск тестов gemini_module с покрытием
test-gemini-coverage:
	@echo "Запуск тестов gemini_module с анализом покрытия..."
	@python -m pytest app/tests/gemini_module/ --cov=app.gemini_module --cov-report=html --cov-report=term -v

# Запуск только тестов excel_parser  
test-excel-parser:
	@echo "Запуск тестов для excel_parser..."
	@python -m pytest app/tests/excel_parser/ -v

# Запуск тестов excel_parser с покрытием
test-excel-parser-coverage:
	@echo "Запуск тестов excel_parser с анализом покрытия..."
	@python -m pytest app/tests/excel_parser/ --cov=app.excel_parser --cov-report=html --cov-report=term -v

# Быстрый запуск тестов (без покрытия)
test-fast:
	@echo "Быстрый запуск тестов..."
	@python -m pytest -x --tb=short

# Запуск только новых тестов (основные модули)
test-new:
	@echo "Запуск только новых тестов (gemini_module)..."
	@python -m pytest app/tests/gemini_module/ -x --tb=short

# Очистка временных файлов
clean:
	@echo "Очистка временных файлов..."
	@find . -type f -name "*.pyc" -delete
	@find . -type d -name "__pycache__" -delete
	@rm -rf htmlcov/
	@rm -f .coverage

# Парсинг одного файла (использование: make parse FILE=path/to/file.xlsx)
parse:
	@if [ -z "$(FILE)" ]; then \
		echo "Ошибка: Укажите файл для парсинга. Использование: make parse FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "Парсинг файла: $(FILE)"
	@python -m app.parse "$(FILE)"

# Парсинг в offline режиме (работает без подключения к серверу)
parse-offline:
	@if [ -z "$(FILE)" ]; then \
		echo "Ошибка: Укажите файл для парсинга. Использование: make parse-offline FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "Парсинг файла в offline режиме: $(FILE)"
	@PARSER_FALLBACK_MODE=true python -m app.parse "$(FILE)"

# Синхронизация файлов из pending_sync с сервером (будет реализовано отдельно)
sync-pending:
	@echo "Синхронизация ожидающих файлов с сервером..."
	@echo "TODO: Реализовать утилиту синхронизации"

# ======================================================================
# === НОВЫЕ КОМАНДЫ ДЛЯ РАБОТЫ С GEMINI AI ===
# ======================================================================

# Парсинг с Gemini AI (синхронный режим)
parse-gemini:
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Ошибка: Укажите файл. Использование: make parse-gemini FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "🧠 Парсинг с Gemini AI: $(FILE)"
	@.venv/bin/python -m app.parse_with_gemini process "$(FILE)" --verbose

# Парсинг с Gemini AI (асинхронный режим через Redis)
parse-gemini-async:
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Ошибка: Укажите файл. Использование: make parse-gemini-async FILE=path/to/file.xlsx"; \
		exit 1; \
	fi
	@echo "🧠 Асинхронный парсинг с Gemini AI: $(FILE)"
	@.venv/bin/python -m app.parse_with_gemini process "$(FILE)" --async --verbose

# Запуск воркера очереди Redis
worker-start:
	worker-start:
	@echo "🚀 Запускаю Gemini воркер очереди..."
	.venv/bin/python -m app.workers.gemini.cli worker

# === CELERY КОМАНДЫ ===

celery-worker:
	@echo "🚀 Запускаю Celery воркер для AI обработки..."
	.venv/bin/celery -A app.celery_app worker --loglevel=DEBUG

celery-beat:
	@echo "⏰ Запускаю Celery Beat планировщик..."
	.venv/bin/celery -A app.celery_app beat --loglevel=INFO

celery-flower:
	@echo "🌸 Запускаю Flower мониторинг на http://localhost:5555..."
	.venv/bin/celery -A app.celery_app flower --port=5555

celery-status:
	@echo "📊 Статус Celery воркеров:"
	.venv/bin/celery -A app.celery_app inspect ping

celery-tasks:
	@echo "📋 Активные задачи Celery:"
	.venv/bin/celery -A app.celery_app inspect active

celery-purge:
	@echo "🧹 Очищаю очередь задач Celery..."
	.venv/bin/celery -A app.celery_app purge -f

start-all:
	@echo "🚀 Запускаю все сервисы..."
	./scripts/start_services.sh

stop-all:
	@echo "🛑 Останавливаю все сервисы..."
	./scripts/stop_services.sh

# Проверка статуса обработки тендера
worker-status:
	@if [ -z "$(TENDER_ID)" ] || [ -z "$(LOT_IDS)" ]; then \
		echo "❌ Ошибка: Укажите TENDER_ID и LOT_IDS. Использование: make worker-status TENDER_ID=123 LOT_IDS='1 2 3'"; \
		exit 1; \
	fi
	@echo "📊 Проверяю статус тендера $(TENDER_ID), лоты: $(LOT_IDS)"
	@.venv/bin/python -m app.parse_with_gemini status $(TENDER_ID) $(LOT_IDS)

# Обработка одного файла позиций (для тестирования)
process-positions:
	@if [ -z "$(TENDER_ID)" ] || [ -z "$(LOT_ID)" ] || [ -z "$(FILE)" ]; then \
		echo "❌ Ошибка: Укажите все параметры. Использование: make process-positions TENDER_ID=123 LOT_ID=456 FILE=path/to/positions.md"; \
		exit 1; \
	fi
	@echo "🔍 Обрабатываю позиции: тендер $(TENDER_ID), лот $(LOT_ID)"
	@.venv/bin/python -m app.workers.gemini.cli --verbose process $(TENDER_ID) $(LOT_ID) "$(FILE)"

# Форматирование кода
format:
	@echo "Форматирование кода с помощью black и isort..."
	@.venv/bin/python -m black app/ *.py
	@.venv/bin/python -m isort app/ *.py

# Проверка стиля кода
lint:
	@echo "Проверка стиля кода..."
	@.venv/bin/python -m flake8 app/ *.py

# Проверка форматирования без изменений
check:
	@echo "Проверка форматирования кода..."
	@.venv/bin/python -m black --check --diff app/ *.py
	@.venv/bin/python -m isort --check-only --diff app/ *.py

# Команда для вывода справки по доступным командам
help:
	@echo "Доступные команды:"
	@echo "  make run         - Запустить веб-сервер в режиме разработки с автоперезагрузкой"
	@echo "  make prod        - Запустить веб-сервер в продакшн режиме"
	@echo "  make install     - Установить зависимости из requirements.txt"
	@echo "  make test        - Запустить все тесты"
	@echo "  make test-coverage - Запустить тесты с анализом покрытия кода"
	@echo "  make test-gemini - Запустить тесты для gemini_module"
	@echo "  make test-gemini-coverage - Запустить тесты gemini_module с покрытием"
	@echo "  make test-excel-parser - Запустить тесты для excel_parser"
	@echo "  make test-excel-parser-coverage - Запустить тесты excel_parser с покрытием"
	@echo "  make test-fast   - Быстрый запуск тестов (остановка на первой ошибке)"
	@echo "  make test-new    - Запустить только новые тесты (gemini_module)"
	@echo "  make clean       - Очистить временные файлы"
	@echo "  make parse FILE=<path>        - Парсить указанный XLSX файл"
	@echo "  make parse-offline FILE=<path> - Парсить файл в offline режиме"
	@echo ""
	@echo "🧠 Команды Gemini AI:"
	@echo "  make parse-gemini FILE=<path> - Парсить файл с Gemini AI (синхронно)"
	@echo "  make parse-gemini-async FILE=<path> - Парсить файл с Gemini AI (через Redis)"
	@echo "  make worker-start             - Запустить простой воркер Gemini AI"
	@echo "  make worker-status TENDER_ID=<id> LOT_IDS='<ids>' - Статус обработки"
	@echo "  make process-positions TENDER_ID=<id> LOT_ID=<id> FILE=<path> - Обработать позиции"
	@echo ""
	@echo "🐝 Команды Celery:"
	@echo "  make celery-worker            - Запустить Celery воркер"
	@echo "  make celery-beat              - Запустить планировщик задач"
	@echo "  make celery-flower            - Запустить мониторинг (localhost:5555)"
	@echo "  make celery-status            - Статус воркеров"
	@echo "  make celery-tasks             - Активные задачи"
	@echo "  make celery-purge             - Очистить очередь"
	@echo ""
	@echo "🚀 Управление сервисами:"
	@echo "  make start-all                - Запустить все сервисы"
	@echo "  make stop-all                 - Остановить все сервисы"
	@echo ""
	@echo "  make sync-pending - Синхронизировать файлы из pending_sync с сервером"
	@echo "  make format      - Форматировать код с помощью black и isort"
	@echo "  make lint        - Проверить стиль кода с помощью flake8"
	@echo "  make check       - Проверить форматирование без изменений"
	@echo "  make help        - Показать это справочное сообщение"
	@echo ""
	@echo "Персонализация:"
	@echo "  Создайте файл Makefile.local для переопределения настроек"
	@echo "  Пример содержимого Makefile.local:"
	@echo "    HOST = 127.0.0.1"
	@echo "    PORT = 8080"
	@echo ""
	@echo "Переменные окружения:"
	@echo "  PARSER_FALLBACK_MODE=true  - Включить резервный режим"
	@echo "  GO_SERVER_API_ENDPOINT     - URL API сервера"
	@echo "  GO_SERVER_API_KEY          - API ключ для сервера"
	@echo "  GOOGLE_API_KEY             - API ключ для Gemini AI"

