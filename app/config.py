"""
Модуль конфигурации приложения.

Централизует управление настройками приложения через переменные окружения
с валидацией и значениями по умолчанию.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


class Config:
    """Класс конфигурации приложения."""

    # Настройки сервера
    GO_SERVER_API_ENDPOINT: Optional[str] = os.getenv("GO_SERVER_API_ENDPOINT")
    GO_SERVER_API_KEY: Optional[str] = os.getenv("GO_SERVER_API_KEY")

    # Режим работы
    PARSER_FALLBACK_MODE: bool = (
        os.getenv("PARSER_FALLBACK_MODE", "false").lower() == "true"
    )

    # Логирование
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_DIR: Path = Path(os.getenv("LOG_DIR", "logs"))

    # Настройки LLM (для llm_test.py)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")
    OLLAMA_TOKEN: Optional[str] = os.getenv("OLLAMA_TOKEN")

    # Директории
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", "temp_uploads"))

    @classmethod
    def validate(cls) -> bool:
        """
        Валидирует критические настройки конфигурации.

        Returns:
            True если конфигурация валидна, False иначе
        """
        if not cls.PARSER_FALLBACK_MODE and not cls.GO_SERVER_API_ENDPOINT:
            return False

        # Создаем необходимые директории
        cls.LOG_DIR.mkdir(exist_ok=True)
        cls.UPLOAD_DIR.mkdir(exist_ok=True)

        return True


# Глобальный экземпляр конфигурации
config = Config()
