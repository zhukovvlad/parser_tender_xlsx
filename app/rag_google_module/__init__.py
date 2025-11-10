# app/rag_google_module/__init__.py
"""
RAG Google Module

Этот модуль предоставляет интеграцию с Google File Search API (RAG-as-a-Service).
Использует новый клиент-ориентированный SDK (google-genai) для прямой загрузки файлов
через model-based API и выполнения семантического поиска по загруженным документам.

Основные компоненты:
- FileSearchClient: Асинхронный клиент для работы с RAG API
  - Загрузка и индексация JSONL-файлов через model-based API
  - Прямой семантический поиск по загруженным файлам
  - Мониторинг статуса загрузки и индексации

Рабочий процесс:
1. Загрузка JSONL-файлов напрямую в модель (минуя corpus API)
2. Автоматическая индексация загруженных файлов
3. Выполнение семантического поиска по индексированным данным
4. Получение релевантных результатов с метаданными

Требования:
- GOOGLE_API_KEY должен быть установлен в переменных окружения
- Установленный пакет google-genai
"""

from .file_search import FileSearchClient
from .logger import get_rag_logger, setup_rag_logger

__all__ = [
    "FileSearchClient",
    "get_rag_logger",
    "setup_rag_logger",
]
