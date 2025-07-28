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
from typing import Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks

from app.parse import parse_file
from app.config import config
from app.exceptions import TenderParsingError

# --- ЕДИНСТВЕННЫЙ БЛОК НАСТРОЙКИ ЛОГГИРОВАНИЯ ---

load_dotenv()  # Загружаем переменные из .env

# 1. Определяем директорию для логов
log_dir = Path("logs")
os.makedirs(log_dir, exist_ok=True)

# 2. Читаем уровень логирования из .env
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = log_levels.get(log_level_str, logging.INFO)

# 3. Конфигурируем logging ОДИН РАЗ с двумя обработчиками
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "parser_service.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# 4. Получаем логгер для текущего модуля
log = logging.getLogger(__name__)

# --- КОНЕЦ БЛОКА НАСТРОЙКИ ЛОГГИРОВАНИЯ ---

# Хранилище статусов задач в памяти
tasks_db: Dict[str, Dict[str, Any]] = {}

# Настройка FastAPI приложения
app = FastAPI(
    title="Tender Parser Service",
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version="2.0.0",
)

UPLOAD_DIRECTORY = config.UPLOAD_DIR
UPLOAD_DIRECTORY.mkdir(exist_ok=True)


def run_parsing_in_background(task_id: str, file_path: str) -> None:
    """
    Выполняет парсинг в фоновом режиме и обновляет статус задачи.
    
    Args:
        task_id: Уникальный идентификатор задачи
        file_path: Путь к файлу для обработки
    """
    log.info(f"Task {task_id}: Обработка файла {file_path} началась в фоне.")
    tasks_db[task_id] = {"status": "processing"}
    try:
        parse_file(file_path)
        tasks_db[task_id] = {"status": "completed"}
        log.info(f"Task {task_id}: Обработка успешно завершена.")
    except TenderParsingError as e:
        log.error(f"Task {task_id}: Ошибка парсинга тендера - {e}", exc_info=True)
        tasks_db[task_id] = {"status": "failed", "error": f"Parsing error: {e}"}
    except Exception as e:
        log.error(f"Task {task_id}: Произошла неожиданная ошибка - {e}", exc_info=True)
        tasks_db[task_id] = {"status": "failed", "error": f"Unexpected error: {e}"}


@app.post("/parse-tender/", status_code=202, tags=["Tender Processing"])
async def create_parsing_task(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    """
    Принимает файл, создает для него уникальную задачу и запускает
    обработку в фоновом режиме, немедленно возвращая ID задачи.
    """
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Неверный формат файла. Пожалуйста, загрузите XLSX или XLS файл.",
        )

    task_id = str(uuid.uuid4())
    temp_file_path = UPLOAD_DIRECTORY / f"{task_id}_{file.filename}"
    log.info(
        f"Task {task_id}: Получен файл {file.filename}. Сохранение в: {temp_file_path}"
    )

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"Task {task_id}: Не удалось сохранить файл: {e}")
        raise HTTPException(
            status_code=500, detail="Не удалось сохранить файл на сервере."
        )
    finally:
        file.file.close()

    background_tasks.add_task(run_parsing_in_background, task_id, str(temp_file_path))

    return {"task_id": task_id, "message": "Задача по обработке файла принята."}


@app.get("/tasks/{task_id}/status", tags=["Task Status"])
async def get_task_status(task_id: str):
    """
    Возвращает текущий статус задачи по ее ID.
    """
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача с таким ID не найдена.")
    return task


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Простая проверка работоспособности сервиса."""
    return {"status": "ok"}
