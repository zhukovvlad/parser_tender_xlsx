# app/tests/test_workers.py

"""
Тесты для новой модульной структуры воркеров.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from app.workers.gemini import GeminiWorker, GeminiManager, GeminiIntegration


class TestGeminiWorker:
    """Тесты для GeminiWorker"""
    
    @patch('app.workers.gemini.worker.TenderProcessor')
    def test_worker_creation(self, mock_processor):
        """Тест создания воркера"""
        worker = GeminiWorker("test_api_key")
        assert worker is not None
        mock_processor.assert_called_once_with("test_api_key")
    
    def test_worker_status(self):
        """Тест получения статуса воркера"""
        if not os.getenv("GOOGLE_API_KEY"):
            pytest.skip("GOOGLE_API_KEY не найден")
        
        worker = GeminiWorker(os.getenv("GOOGLE_API_KEY"))
        status = worker.get_status()
        
        assert "worker_type" in status
        assert status["worker_type"] == "gemini"
        assert "status" in status
        assert "timestamp" in status


class TestGeminiManager:
    """Тесты для GeminiManager"""
    
    def test_manager_creation(self):
        """Тест создания менеджера"""
        if not os.getenv("GOOGLE_API_KEY"):
            pytest.skip("GOOGLE_API_KEY не найден")
        
        manager = GeminiManager(os.getenv("GOOGLE_API_KEY"))
        assert manager is not None
        assert manager.worker is not None
        assert manager.max_retries == 3


class TestGeminiIntegration:
    """Тесты для GeminiIntegration"""
    
    def test_integration_creation(self):
        """Тест создания интеграции"""
        integration = GeminiIntegration()
        assert integration is not None
    
    def test_integration_with_api_key(self):
        """Тест интеграции с API ключом"""
        if not os.getenv("GOOGLE_API_KEY"):
            pytest.skip("GOOGLE_API_KEY не найден")
        
        integration = GeminiIntegration(api_key=os.getenv("GOOGLE_API_KEY"))
        assert integration.manager is not None
    
    def test_redis_setup(self):
        """Тест настройки Redis"""
        # Должно вернуть None если Redis недоступен
        client = GeminiIntegration.setup_redis_client(host="nonexistent")
        assert client is None


class TestWorkersImport:
    """Тесты импортов модуля workers"""
    
    def test_main_imports(self):
        """Тест основных импортов"""
        from app.workers import GeminiWorker, GeminiManager, GeminiIntegration
        
        assert GeminiWorker is not None
        assert GeminiManager is not None  
        assert GeminiIntegration is not None
    
    def test_gemini_module_imports(self):
        """Тест импортов из модуля gemini"""
        from app.workers.gemini import GeminiWorker, GeminiManager, GeminiIntegration
        
        assert GeminiWorker is not None
        assert GeminiManager is not None
        assert GeminiIntegration is not None


@pytest.mark.integration
class TestFullIntegration:
    """Интеграционные тесты (требуют API ключ)"""
    
    @pytest.fixture
    def sample_positions_file(self):
        """Создает временный файл позиций для тестов"""
        content = """
# Тестовые позиции

## Работы по устройству котлована

1. Разработка грунта - 1000 м³
2. Устройство ограждающих конструкций - 500 м
3. Водопонижение - 30 дней

## Бетонные работы

1. Подготовка под фундамент - 200 м³
2. Устройство фундамента - 800 м³
"""
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='_positions.md', delete=False) as f:
            f.write(content)
            return f.name
    
    def test_end_to_end_processing(self, sample_positions_file):
        """Тест полного цикла обработки файла"""
        if not os.getenv("GOOGLE_API_KEY"):
            pytest.skip("GOOGLE_API_KEY не найден для интеграционного теста")
        
        try:
            # Создаем воркер
            worker = GeminiWorker(os.getenv("GOOGLE_API_KEY"))
            
            # Обрабатываем файл
            from app.gemini_module.constants import TENDER_CATEGORIES, TENDER_CONFIGS, FALLBACK_CATEGORY
            
            result = worker.process_positions_file(
                tender_id="integration_test",
                lot_id="test_lot",
                positions_file_path=sample_positions_file,
                categories=TENDER_CATEGORIES,
                configs=TENDER_CONFIGS,
                fallback_category=FALLBACK_CATEGORY
            )
            
            # Проверяем результат
            assert result is not None
            assert "tender_id" in result
            assert "lot_id" in result
            assert "category" in result
            assert "status" in result
            assert result["tender_id"] == "integration_test"
            assert result["lot_id"] == "test_lot"
            
            # Если обработка успешна, проверяем AI данные
            if result["status"] == "success":
                assert "ai_data" in result
                print(f"✅ Успешно обработано. Категория: {result['category']}")
                print(f"✅ Извлечено полей: {len(result.get('ai_data', {}))}")
            else:
                print(f"⚠️ Обработка завершилась с ошибкой: {result.get('error')}")
                
        finally:
            # Очищаем временный файл
            if os.path.exists(sample_positions_file):
                os.unlink(sample_positions_file)


if __name__ == "__main__":
    # Запуск быстрых тестов
    pytest.main([__file__, "-v", "-m", "not integration"])
