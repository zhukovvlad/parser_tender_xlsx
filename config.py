"""
Конфигурационный модуль для парсера тендерных документов.

Содержит настройки для различных компонентов системы:
- Настройки API сервера
- Настройки базы данных
- Настройки файловой системы
- Настройки логирования
"""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

@dataclass
class ServerConfig:
    """Конфигурация API сервера."""
    host: str = "0.0.0.0"
    port: int = 9000
    reload: bool = True
    workers: int = 1
    timeout: int = 300
    max_file_size: int = 50 * 1024 * 1024  # 50MB

@dataclass
class DatabaseConfig:
    """Конфигурация базы данных."""
    go_server_url: Optional[str] = None
    go_server_api_key: Optional[str] = None
    postgres_url: Optional[str] = None
    fallback_mode: bool = False
    
    def __post_init__(self):
        self.go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
        self.go_server_api_key = os.getenv("GO_SERVER_API_KEY")
        self.postgres_url = os.getenv("POSTGRES_URL")
        self.fallback_mode = os.getenv("PARSER_FALLBACK_MODE", "false").lower() == "true"

@dataclass
class FileSystemConfig:
    """Конфигурация файловой системы."""
    upload_dir: Path = Path("temp_uploads")
    output_dirs: dict = None
    
    def __post_init__(self):
        self.upload_dir.mkdir(exist_ok=True)
        
        project_root = Path.cwd()
        self.output_dirs = {
            "xlsx": project_root / "tenders_xlsx",
            "json": project_root / "tenders_json", 
            "md": project_root / "tenders_md",
            "chunks": project_root / "tenders_chunks",
            "positions": project_root / "tenders_positions",
            "pending": project_root / "pending_sync"
        }
        
        # Создаем все необходимые директории
        for dir_path in self.output_dirs.values():
            dir_path.mkdir(exist_ok=True)

@dataclass
class LoggingConfig:
    """Конфигурация логирования."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: Optional[Path] = None
    max_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5
    
    def __post_init__(self):
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        self.file_path = log_dir / "parser.log"

@dataclass
class LLMConfig:
    """Конфигурация для работы с LLM."""
    ollama_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "mistral"
    ollama_token: Optional[str] = None
    timeout: int = 120
    max_retries: int = 3
    
    def __post_init__(self):
        self.ollama_url = os.getenv("OLLAMA_URL", self.ollama_url)
        self.ollama_model = os.getenv("OLLAMA_MODEL", self.ollama_model)
        self.ollama_token = os.getenv("OLLAMA_TOKEN")

@dataclass
class ParserConfig:
    """Основная конфигурация парсера."""
    allowed_extensions: tuple = (".xlsx", ".xls")
    max_file_size: int = 50 * 1024 * 1024  # 50MB
    encoding: str = "utf-8"
    chunk_size: int = 1000
    overlap: int = 200
    
    # Компоненты конфигурации
    server: ServerConfig = None
    database: DatabaseConfig = None
    filesystem: FileSystemConfig = None
    logging: LoggingConfig = None
    llm: LLMConfig = None
    
    def __post_init__(self):
        self.server = ServerConfig()
        self.database = DatabaseConfig()
        self.filesystem = FileSystemConfig()
        self.logging = LoggingConfig()
        self.llm = LLMConfig()

# Создаем глобальный экземпляр конфигурации
config = ParserConfig()

# Функции для удобного доступа к конфигурации
def get_server_config() -> ServerConfig:
    """Возвращает конфигурацию сервера."""
    return config.server

def get_database_config() -> DatabaseConfig:
    """Возвращает конфигурацию базы данных."""
    return config.database

def get_filesystem_config() -> FileSystemConfig:
    """Возвращает конфигурацию файловой системы."""
    return config.filesystem

def get_logging_config() -> LoggingConfig:
    """Возвращает конфигурацию логирования."""
    return config.logging

def get_llm_config() -> LLMConfig:
    """Возвращает конфигурацию LLM."""
    return config.llm

def is_fallback_mode() -> bool:
    """Проверяет, включен ли режим fallback."""
    return config.database.fallback_mode

def get_output_directories() -> dict:
    """Возвращает словарь выходных директорий."""
    return config.filesystem.output_dirs