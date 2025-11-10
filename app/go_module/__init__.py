# app/go_module/__init__.py
"""
Go Module

Этот модуль предоставляет интеграцию с Go-бэкендом (tenders-go).
Содержит клиент для взаимодействия с API и систему логирования.

Основные компоненты:
- GoApiClient: Асинхронный HTTP клиент для взаимодействия с Go API
- Логирование: Настраиваемая система логирования для отслеживания запросов и ошибок
"""

from .go_client import GoApiClient
from .logger import get_go_logger, setup_go_logger
from .sync_wrapper import import_tender_sync, update_lot_ai_results_sync

__all__ = [
    "GoApiClient",
    "get_go_logger",
    "setup_go_logger",
    "import_tender_sync",
    "update_lot_ai_results_sync",
]
