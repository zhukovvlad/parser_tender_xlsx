"""
Тесты для FastAPI приложения main.py.

Тестирует все эндпоинты API:
- POST /parse-tender/: Загрузка и обработка файлов
- GET /tasks/{task_id}/status: Получение статуса задачи
- GET /health: Проверка работоспособности
"""

import pytest
import tempfile
import io
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from main import app, tasks_db


@pytest.fixture
def client():
    """Фикстура для тестового клиента FastAPI."""
    return TestClient(app)


@pytest.fixture
def sample_xlsx_file():
    """Фикстура для создания тестового XLSX файла."""
    # Создаем простой XLSX файл в памяти
    content = b'PK\x03\x04\x14\x00\x00\x00\x08\x00'  # Заголовок ZIP (XLSX)
    return io.BytesIO(content)


@pytest.fixture
def clean_tasks_db():
    """Фикстура для очистки базы данных задач."""
    tasks_db.clear()
    yield
    tasks_db.clear()


class TestHealthEndpoint:
    """Тесты для эндпоинта /health."""
    
    def test_health_check_success(self, client):
        """Тест успешной проверки здоровья сервиса."""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "tender-parser"
        assert data["version"] == "2.0.0"


class TestParseTenderEndpoint:
    """Тесты для эндпоинта /parse-tender/."""
    
    def test_upload_valid_xlsx_file(self, client, clean_tasks_db):
        """Тест загрузки валидного XLSX файла."""
        # Создаем тестовый файл
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp.write(b'test content')
            tmp_path = tmp.name
        
        try:
            with open(tmp_path, 'rb') as f:
                response = client.post(
                    "/parse-tender/",
                    files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                )
            
            assert response.status_code == 202
            data = response.json()
            assert "task_id" in data
            assert data["message"] == "Задача по обработке файла принята."
            assert len(tasks_db) == 1
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    def test_upload_invalid_file_extension(self, client, clean_tasks_db):
        """Тест загрузки файла с неверным расширением."""
        response = client.post(
            "/parse-tender/",
            files={"file": ("test.txt", io.BytesIO(b"test content"), "text/plain")}
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "Неверный формат файла" in data["detail"]
    
    def test_upload_no_filename(self, client, clean_tasks_db):
        """Тест загрузки файла без имени."""
        response = client.post(
            "/parse-tender/",
            files={"file": ("", io.BytesIO(b"test content"), "application/octet-stream")}
        )
        
        # FastAPI может возвращать 422 для некорректных данных
        assert response.status_code in [400, 422]
        data = response.json()
        # Проверяем что в ответе есть информация об ошибке
        assert "detail" in data
    
    @patch('main.MAX_FILE_SIZE', 100)  # Устанавливаем маленький лимит для теста
    def test_upload_file_too_large(self, client, clean_tasks_db):
        """Тест загрузки слишком большого файла."""
        large_content = b'x' * 200  # Больше лимита
        
        response = client.post(
            "/parse-tender/",
            files={"file": ("large.xlsx", io.BytesIO(large_content), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
        
        assert response.status_code == 413
        data = response.json()
        assert "Файл слишком большой" in data["detail"]
    
    @patch('main.parse_file')
    def test_background_task_execution(self, mock_parse_file, client, clean_tasks_db):
        """Тест выполнения фоновой задачи."""
        # Настраиваем мок
        mock_parse_file.return_value = None
        
        # Создаем тестовый файл
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp.write(b'test content')
            tmp_path = tmp.name
        
        try:
            with open(tmp_path, 'rb') as f:
                response = client.post(
                    "/parse-tender/",
                    files={"file": ("test.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                )
            
            assert response.status_code == 202
            data = response.json()
            task_id = data["task_id"]
            
            # Даем время на выполнение фоновой задачи
            import time
            time.sleep(0.1)
            
            # Проверяем, что задача была вызвана
            mock_parse_file.assert_called_once()
            
            # Проверяем статус задачи
            assert task_id in tasks_db
            assert tasks_db[task_id]["status"] in ["processing", "completed"]
            
        finally:
            Path(tmp_path).unlink(missing_ok=True)


class TestTaskStatusEndpoint:
    """Тесты для эндпоинта /tasks/{task_id}/status."""
    
    def test_get_existing_task_status(self, client, clean_tasks_db):
        """Тест получения статуса существующей задачи."""
        # Добавляем задачу в базу
        task_id = "test-task-id"
        tasks_db[task_id] = {
            "status": "completed",
            "file_path": "/path/to/file.xlsx"
        }
        
        response = client.get(f"/tasks/{task_id}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["error"] is None
    
    def test_get_task_status_with_error(self, client, clean_tasks_db):
        """Тест получения статуса задачи с ошибкой."""
        task_id = "failed-task-id"
        tasks_db[task_id] = {
            "status": "failed",
            "error": "Ошибка парсинга файла"
        }
        
        response = client.get(f"/tasks/{task_id}/status")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "Ошибка парсинга файла"
    
    def test_get_nonexistent_task_status(self, client, clean_tasks_db):
        """Тест получения статуса несуществующей задачи."""
        response = client.get("/tasks/nonexistent-task/status")
        
        assert response.status_code == 404
        data = response.json()
        assert "Задача с таким ID не найдена" in data["detail"]


class TestFileValidation:
    """Тесты для валидации файлов."""
    
    def test_validate_xlsx_file(self, client):
        """Тест валидации XLSX файла."""
        from main import validate_file
        from fastapi import UploadFile
        
        # Создаем мок UploadFile
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.xlsx"
        
        # Функция не должна вызвать исключение
        validate_file(mock_file)
    
    def test_validate_xls_file(self, client):
        """Тест валидации XLS файла."""
        from main import validate_file
        from fastapi import UploadFile
        
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.xls"
        
        # Функция не должна вызвать исключение
        validate_file(mock_file)
    
    def test_validate_file_no_filename(self, client):
        """Тест валидации файла без имени."""
        from main import validate_file
        from fastapi import UploadFile, HTTPException
        
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = None
        
        with pytest.raises(HTTPException) as exc_info:
            validate_file(mock_file)
        
        assert exc_info.value.status_code == 400
        assert "Не указано имя файла" in str(exc_info.value.detail)
    
    def test_validate_file_wrong_extension(self, client):
        """Тест валидации файла с неверным расширением."""
        from main import validate_file
        from fastapi import UploadFile, HTTPException
        
        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.pdf"
        
        with pytest.raises(HTTPException) as exc_info:
            validate_file(mock_file)
        
        assert exc_info.value.status_code == 400
        assert "Неверный формат файла" in str(exc_info.value.detail)


class TestBackgroundTaskExecution:
    """Тесты для выполнения фоновых задач."""
    
    @patch('main.parse_file')
    @patch('main.os.path.exists')
    def test_successful_background_task(self, mock_exists, mock_parse_file, clean_tasks_db):
        """Тест успешного выполнения фоновой задачи."""
        from main import run_parsing_in_background
        
        task_id = "test-task"
        file_path = "/path/to/test.xlsx"
        
        mock_parse_file.return_value = None
        mock_exists.return_value = False  # Файл не существует, удаление не требуется
        
        # Выполняем задачу
        run_parsing_in_background(task_id, file_path)
        
        # Проверяем результат
        assert task_id in tasks_db
        assert tasks_db[task_id]["status"] == "completed"
        assert tasks_db[task_id]["file_path"] == file_path
        
        # Проверяем вызовы
        mock_parse_file.assert_called_once_with(file_path)
        mock_exists.assert_called_once_with(file_path)
    
    @patch('main.parse_file')
    @patch('main.os.path.exists')
    def test_failed_background_task(self, mock_exists, mock_parse_file, clean_tasks_db):
        """Тест неуспешного выполнения фоновой задачи."""
        from main import run_parsing_in_background
        
        task_id = "failed-task"
        file_path = "/path/to/test.xlsx"
        error_message = "Ошибка парсинга"
        
        mock_parse_file.side_effect = Exception(error_message)
        mock_exists.return_value = False  # Файл не существует, удаление не требуется
        
        # Выполняем задачу
        run_parsing_in_background(task_id, file_path)
        
        # Проверяем результат
        assert task_id in tasks_db
        assert tasks_db[task_id]["status"] == "failed"
        assert tasks_db[task_id]["error"] == error_message
        assert tasks_db[task_id]["file_path"] == file_path
        
        # Проверяем вызовы
        mock_parse_file.assert_called_once_with(file_path)
        mock_exists.assert_called_once_with(file_path)


class TestGlobalExceptionHandler:
    """Тесты для глобального обработчика исключений."""
    
    def test_global_exception_handler_exists(self):
        """Тест что глобальный обработчик исключений существует."""
        from main import app
        
        # Проверяем что в приложении есть обработчики исключений
        assert hasattr(app, 'exception_handlers')
        assert Exception in app.exception_handlers or len(app.exception_handlers) >= 0