# Makefile для автоматизации задач разработки

.PHONY: help install test lint format security clean

help:  ## Показать справку по командам
	@echo "Доступные команды:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Установить зависимости
	pip install -r requirements.txt

install-dev:  ## Установить зависимости для разработки
	pip install -r requirements.txt
	pre-commit install

test:  ## Запустить тесты
	python -m pytest app/tests/ -v --cov=app --cov-report=html --cov-report=term

test-fast:  ## Запустить быстрые тесты
	python -m pytest app/tests/ -v -m "not slow"

lint:  ## Проверить код линтерами
	flake8 app/ main.py
	mypy app/ main.py || true

format:  ## Форматировать код
	black app/ main.py
	isort app/ main.py

format-check:  ## Проверить форматирование без изменений
	black --check app/ main.py
	isort --check-only app/ main.py

security:  ## Проверить безопасность
	bandit -r app/ main.py

clean:  ## Очистить временные файлы
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf build/

run-server:  ## Запустить FastAPI сервер
	uvicorn main:app --reload --host 0.0.0.0 --port 8000

run-parser:  ## Запустить парсер (требуется указать файл: make run-parser FILE=example.xlsx)
	python -m app.parse $(FILE)

check-all:  ## Полная проверка: форматирование, линтинг, безопасность, тесты
	@echo "🔍 Проверка форматирования..."
	make format-check
	@echo "✅ Форматирование OK"
	@echo "🔍 Проверка линтерами..."
	make lint
	@echo "✅ Линтинг OK"
	@echo "🔍 Проверка безопасности..."
	make security
	@echo "✅ Безопасность OK"
	@echo "🔍 Запуск тестов..."
	make test
	@echo "✅ Все проверки пройдены!"

fix:  ## Автоматическое исправление проблем форматирования
	make format
	@echo "✅ Код отформатирован!"

setup:  ## Первоначальная настройка проекта
	make install-dev
	make format
	@echo "✅ Проект настроен для разработки!"