# app/workers/__init__.py
"""
Модуль воркеров для различных типов обработки.
Каждый воркер находится в отдельной папке со всей своей функциональностью.
"""

from .gemini import GeminiIntegration, GeminiManager, GeminiWorker

__all__ = [
    "GeminiWorker",
    "GeminiManager",
    "GeminiIntegration",
]
