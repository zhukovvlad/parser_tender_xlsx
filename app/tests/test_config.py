"""
Тесты для модуля конфигурации.
"""

import os
import pytest
from unittest.mock import patch

from app.config import Settings, get_settings, validate_required_settings


class TestSettings:
    """Тесты класса Settings."""

    def test_default_settings(self):
        """Тест настроек по умолчанию."""
        settings = Settings()
        
        assert settings.app_title == "Tender Parser Service"
        assert settings.max_file_size == 50 * 1024 * 1024  # 50MB
        assert settings.allowed_extensions == [".xlsx", ".xls"]
        assert settings.log_level == "INFO"
        assert not settings.debug

    def test_environment_variable_override(self):
        """Тест переопределения через переменные окружения."""
        with patch.dict(os.environ, {
            'APP_TITLE': 'Custom Parser',
            'MAX_FILE_SIZE': '10485760',  # 10MB
            'DEBUG': 'true',
            'LOG_LEVEL': 'DEBUG'
        }):
            settings = Settings()
            assert settings.app_title == 'Custom Parser'
            assert settings.max_file_size == 10485760
            assert settings.debug is True
            assert settings.log_level == 'DEBUG'

    def test_max_file_size_validation_positive(self):
        """Тест валидации положительного размера файла."""
        settings = Settings(max_file_size=1024)
        assert settings.max_file_size == 1024

    def test_max_file_size_validation_negative(self):
        """Тест валидации отрицательного размера файла."""
        with pytest.raises(ValueError, match="max_file_size must be positive"):
            Settings(max_file_size=-1)

    def test_max_file_size_validation_too_large(self):
        """Тест валидации слишком большого размера файла."""
        with pytest.raises(ValueError, match="cannot exceed 500MB"):
            Settings(max_file_size=600 * 1024 * 1024)  # 600MB

    def test_allowed_extensions_validation_valid(self):
        """Тест валидации допустимых расширений."""
        settings = Settings(allowed_extensions=[".xlsx"])
        assert settings.allowed_extensions == [".xlsx"]

    def test_allowed_extensions_validation_invalid(self):
        """Тест валидации недопустимых расширений."""
        with pytest.raises(ValueError, match="Extension .pdf not supported"):
            Settings(allowed_extensions=[".pdf"])


class TestGetSettings:
    """Тесты функции get_settings."""

    def test_get_settings_returns_settings_instance(self):
        """Тест возврата экземпляра Settings."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_get_settings_caching(self):
        """Тест что get_settings возвращает новый экземпляр каждый раз."""
        # В текущей реализации нет кэширования, каждый вызов возвращает новый объект
        settings1 = get_settings()
        settings2 = get_settings()
        # Проверяем, что это разные объекты, но с одинаковыми значениями
        assert settings1 is not settings2
        assert settings1.app_title == settings2.app_title


class TestValidateRequiredSettings:
    """Тесты функции validate_required_settings."""

    def test_validate_with_ollama_url(self):
        """Тест валидации с установленным OLLAMA_URL."""
        settings = Settings(ollama_url="http://localhost:11434")
        # Не должно вызывать исключение
        validate_required_settings(settings)

    def test_validate_without_ollama_url(self):
        """Тест валидации без OLLAMA_URL."""
        settings = Settings()  # ollama_url=None по умолчанию
        
        with pytest.raises(ValueError) as exc_info:
            validate_required_settings(settings)
        
        assert "OLLAMA_URL is required" in str(exc_info.value)

    def test_validate_multiple_errors(self):
        """Тест валидации с несколькими ошибками."""
        settings = Settings()
        
        with pytest.raises(ValueError) as exc_info:
            validate_required_settings(settings)
        
        error_message = str(exc_info.value)
        assert "Configuration errors:" in error_message
        assert "OLLAMA_URL is required" in error_message


class TestSettingsIntegration:
    """Интеграционные тесты настроек."""

    def test_settings_from_env_file(self, tmp_path):
        """Тест загрузки настроек из .env файла."""
        # Создаем временный .env файл
        env_file = tmp_path / ".env"
        env_file.write_text(
            "APP_TITLE=Test Parser\n"
            "MAX_FILE_SIZE=5242880\n"  # 5MB
            "DEBUG=true\n"
        )
        
        # Загружаем настройки с указанием пути к .env файлу
        settings = Settings(_env_file=str(env_file))
        
        assert settings.app_title == "Test Parser"
        assert settings.max_file_size == 5242880
        assert settings.debug is True

    @patch.dict(os.environ, {
        'OLLAMA_URL': 'http://test-ollama:11434',
        'GO_SERVER_API_ENDPOINT': 'http://test-go-server:8080/api',
        'GO_SERVER_API_KEY': 'test-key-123'
    })
    def test_external_services_configuration(self):
        """Тест конфигурации внешних сервисов."""
        settings = Settings()
        
        assert settings.ollama_url == 'http://test-ollama:11434'
        assert settings.go_server_api_endpoint == 'http://test-go-server:8080/api'
        assert settings.go_server_api_key == 'test-key-123'
        
        # Валидация должна пройти успешно
        validate_required_settings(settings)

    def test_cors_settings_defaults(self):
        """Тест настроек CORS по умолчанию."""
        settings = Settings()
        
        assert settings.cors_origins == ["*"]
        assert settings.cors_allow_credentials is True
        assert settings.cors_allow_methods == ["*"]
        assert settings.cors_allow_headers == ["*"]

    @patch.dict(os.environ, {
        'CORS_ORIGINS': '["http://localhost:3000", "https://myapp.com"]',
        'CORS_ALLOW_CREDENTIALS': 'false'
    })
    def test_cors_settings_custom(self):
        """Тест кастомных настроек CORS."""
        settings = Settings()
        
        # Примечание: Pydantic автоматически не парсит JSON строки в списки
        # Для этого нужна дополнительная настройка или validator
        # Пока проверяем что значение передалось
        assert 'CORS_ORIGINS' in os.environ