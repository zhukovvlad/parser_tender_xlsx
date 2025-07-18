"""
Основной модуль веб-сервиса для обработки тендерных файлов.

Этот модуль запускает FastAPI приложение и определяет следующие API эндпоинты:
- POST /parse-tender/: Принимает XLSX файл, создает фоновую задачу для его
  парсинга и немедленно возвращает ID задачи.
- GET /tasks/{task_id}/status: Позволяет отслеживать статус выполнения
  фоновой задачи (processing, completed, failed).
- GET /health: Проверяет работоспособность сервиса.

Для управления фоновыми задачами используется встроенный механизм BackgroundTasks.
Статусы задач хранятся в памяти (для демонстрационных целей).
"""
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Убедитесь, что все импорты внутри пакета app используют относительный синтаксис (с точкой)
from app.parse import parse_file

# Модели данных для API
class TaskResponse(BaseModel):
    task_id: str
    message: str

class TaskStatus(BaseModel):
    status: str
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str

# ВАЖНО: Это простое хранилище в памяти. Если вы перезапустите сервер,
# все статусы пропадут. Для продакшена лучше использовать
# более надежное решение, например, Redis или отдельную таблицу в БД.
tasks_db: Dict[str, Dict[str, Any]] = {}

# Настройка FastAPI приложения
app = FastAPI(
    title="Tender Parser Service",
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version="2.0.0"
)

UPLOAD_DIRECTORY = Path("temp_uploads")
UPLOAD_DIRECTORY.mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Ограничения для файлов
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'.xlsx', '.xls'}


def run_parsing_in_background(task_id: str, file_path: str) -> None:
    """
    Выполняет парсинг в фоновом режиме и обновляет статус задачи.
    
    Args:
        task_id: Уникальный идентификатор задачи
        file_path: Путь к файлу для обработки
    """
    log.info(f"Task {task_id}: Обработка файла {file_path} началась в фоне.")
    tasks_db[task_id] = {"status": "processing", "file_path": file_path}
    
    try:
        parse_file(file_path)
        tasks_db[task_id] = {"status": "completed", "file_path": file_path}
        log.info(f"Task {task_id}: Обработка успешно завершена.")
    except Exception as e:
        log.error(f"Task {task_id}: Произошла ошибка - {e}", exc_info=True)
        tasks_db[task_id] = {
            "status": "failed", 
            "error": str(e),
            "file_path": file_path
        }
    finally:
        # Удаляем временный файл
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                log.info(f"Task {task_id}: Временный файл удален.")
        except Exception as e:
            log.warning(f"Task {task_id}: Не удалось удалить временный файл: {e}")


def validate_file(file: UploadFile) -> None:
    """
    Валидирует загруженный файл.
    
    Args:
        file: Загруженный файл
        
    Raises:
        HTTPException: При невалидном файле
    """
    if not file.filename:
        raise HTTPException(
            status_code=400, 
            detail="Не указано имя файла."
        )
    
    # Проверяем расширение файла
    file_extension = Path(file.filename).suffix.lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Неверный формат файла. Поддерживаются: {', '.join(ALLOWED_EXTENSIONS)}"
        )


@app.post("/parse-tender/", status_code=202, response_model=TaskResponse, tags=["Tender Processing"])
async def create_parsing_task(
    background_tasks: BackgroundTasks, 
    file: UploadFile = File(...)
) -> TaskResponse:
    """
    Принимает файл, создает для него уникальную задачу и запускает
    обработку в фоновом режиме, немедленно возвращая ID задачи.
    
    Args:
        background_tasks: Менеджер фоновых задач FastAPI
        file: Загружаемый XLSX файл
        
    Returns:
        TaskResponse: Ответ с ID задачи и сообщением
        
    Raises:
        HTTPException: При ошибках валидации или сохранения файла
    """
    validate_file(file)
    
    task_id = str(uuid.uuid4())
    temp_file_path = UPLOAD_DIRECTORY / f"{task_id}_{file.filename}"
    
    log.info(f"Task {task_id}: Получен файл {file.filename}. Сохранение в: {temp_file_path}")

    try:
        # Сохраняем файл
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Проверяем размер файла
        file_size = temp_file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            temp_file_path.unlink()  # Удаляем файл
            raise HTTPException(
                status_code=413,
                detail=f"Файл слишком большой. Максимальный размер: {MAX_FILE_SIZE // (1024*1024)}MB"
            )
        
        log.info(f"Task {task_id}: Файл сохранен, размер: {file_size} bytes")
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Task {task_id}: Не удалось сохранить файл: {e}")
        if temp_file_path.exists():
            temp_file_path.unlink()
        raise HTTPException(
            status_code=500, 
            detail="Не удалось сохранить файл на сервере."
        )
    finally:
        file.file.close()

    # Добавляем задачу в фоновый процесс
    background_tasks.add_task(
        run_parsing_in_background, task_id, str(temp_file_path)
    )

    return TaskResponse(
        task_id=task_id, 
        message="Задача по обработке файла принята."
    )


@app.get("/tasks/{task_id}/status", response_model=TaskStatus, tags=["Task Status"])
async def get_task_status(task_id: str) -> TaskStatus:
    """
    Возвращает текущий статус задачи по ее ID.
    
    Args:
        task_id: Уникальный идентификатор задачи
        
    Returns:
        TaskStatus: Информация о статусе задачи
        
    Raises:
        HTTPException: Если задача не найдена
    """
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(
            status_code=404, 
            detail="Задача с таким ID не найдена."
        )
    
    return TaskStatus(
        status=task["status"],
        error=task.get("error")
    )


@app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
async def health_check() -> HealthResponse:
    """
    Простая проверка работоспособности сервиса.
    
    Returns:
        HealthResponse: Информация о состоянии сервиса
    """
    return HealthResponse(
        status="ok",
        service="tender-parser",
        version="2.0.0"
    )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """
    Глобальный обработчик исключений.
    
    Args:
        request: HTTP запрос
        exc: Исключение
        
    Returns:
        JSONResponse: Ответ с информацией об ошибке
    """
    log.error(f"Необработанная ошибка: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера"}
    )
