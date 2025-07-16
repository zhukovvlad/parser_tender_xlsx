"""
Configuration management for the tender parser application.

This module provides centralized configuration handling using Pydantic
for validation and type safety.
"""

import os
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with validation."""
    
    # FastAPI settings
    app_title: str = "Tender Parser Service"
    app_description: str = "Сервис для асинхронной обработки тендерных XLSX файлов"
    app_version: str = "2.0.0"
    debug: bool = False
    
    # File upload settings
    max_file_size: int = Field(
        default=50 * 1024 * 1024,  # 50MB
        description="Maximum file size in bytes"
    )
    upload_directory: str = "temp_uploads"
    allowed_extensions: list[str] = [".xlsx", ".xls"]
    
    # LLM settings
    ollama_url: Optional[str] = None
    ollama_model: str = "mistral"
    ollama_token: Optional[str] = None
    
    # External services
    go_server_api_endpoint: Optional[str] = None
    go_server_api_key: Optional[str] = None
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(levelname)s - %(message)s"
    
    # Database settings (for future use)
    database_url: Optional[str] = None
    redis_url: Optional[str] = None
    
    # Security
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]
    
    @field_validator("max_file_size")
    @classmethod
    def validate_max_file_size(cls, v):
        """Validate maximum file size."""
        if v <= 0:
            raise ValueError("max_file_size must be positive")
        if v > 500 * 1024 * 1024:  # 500MB absolute limit
            raise ValueError("max_file_size cannot exceed 500MB")
        return v
    
    @field_validator("allowed_extensions")
    @classmethod
    def validate_allowed_extensions(cls, v):
        """Validate file extensions."""
        valid_extensions = [".xlsx", ".xls"]
        for ext in v:
            if ext not in valid_extensions:
                raise ValueError(f"Extension {ext} not supported")
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_settings() -> Settings:
    """Get application settings."""
    return Settings()


def validate_required_settings(settings: Settings) -> None:
    """Validate that required settings are present."""
    errors = []
    
    # Check LLM settings if LLM functionality is used
    if not settings.ollama_url:
        errors.append("OLLAMA_URL is required for LLM functionality")
    
    if errors:
        raise ValueError(f"Configuration errors: {'; '.join(errors)}")


# Global settings instance
settings = get_settings()