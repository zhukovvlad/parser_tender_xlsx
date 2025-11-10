# app/rag_google_module/__init__.py
"""
RAG Google Module

Этот модуль предоставляет интеграцию с Google File Search API (RAG-as-a-Service).
Использует новый клиент-ориентированный SDK (google-genai) для семантического поиска
и индексации документов в формате JSONL.

Основные компоненты:
- FileSearchClient: Асинхронный клиент для работы с RAG API
  - Создание и управление корпусами (индексами)
  - Загрузка и индексация JSONL-файлов
  - Семантический поиск по корпусу
  - Мониторинг статуса индексации файлов

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
