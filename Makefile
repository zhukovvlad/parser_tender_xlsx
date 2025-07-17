# Makefile для управления Python-сервисом парсера

# .PHONY гарантирует, что make выполнит команду, даже если в директории
# уже есть файл или папка с таким же именем (например, "run").
.PHONY: run help install test clean dev prod parse

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

# Запуск тестов
test:
	@echo "Запуск тестов..."
	@python -m pytest -v

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

# Команда для вывода справки по доступным командам
help:
	@echo "Доступные команды:"
	@echo "  make run         - Запустить веб-сервер в режиме разработки с автоперезагрузкой"
	@echo "  make prod        - Запустить веб-сервер в продакшн режиме"
	@echo "  make install     - Установить зависимости из requirements.txt"
	@echo "  make test        - Запустить тесты"
	@echo "  make clean       - Очистить временные файлы"
	@echo "  make parse FILE=<path> - Парсить указанный XLSX файл"
	@echo "  make help        - Показать это справочное сообщение"
	@echo ""
	@echo "Персонализация:"
	@echo "  Создайте файл Makefile.local для переопределения настроек"
	@echo "  Пример содержимого Makefile.local:"
	@echo "    HOST = 127.0.0.1"
	@echo "    PORT = 8080"

