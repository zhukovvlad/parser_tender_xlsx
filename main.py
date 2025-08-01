"""Основной модуль веб-сервиса для обработки тендерных файлов.

Этот модуль запускает FastAPI приложение и определяет следующие API эндпоинты:
- POST /parse-tender/: Принимает XLSX файл, создает фоновую задачу для его
  парсинга и немедленно возвращает ID задачи.
- GET /tasks/{task_id}/status: Позволяет отслеживать статус выполнения
  фоновой задачи (processing, completed, failed).
- GET /health: Проверяет работоспособность сервиса.

Для управления фоновыми задачами используется встроенный механизм FastAPI.
Статусы задач хранятся в Redis для обеспечения надежности и масштабируемости.
"""

import json
import logging
import os
import shutil
import uuid
from pathlib import Path

import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile

from app.parse import parse_file

# --- ЦЕНТРАЛИЗОВАННАЯ НАСТРОЙКА ПРИЛОЖЕНИЯ ---

# Загружаем переменные окружения из файла .env в корне проекта
load_dotenv()

# 1. Настройка логирования
log_dir = Path("logs")
os.makedirs(log_dir, exist_ok=True)

# Читаем уровень логирования из .env (по умолчанию INFO)
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = log_levels.get(log_level_str, logging.INFO)

# Конфигурируем logging ОДИН РАЗ для всего приложения
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "parser_service.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Получаем именованный логгер для текущего модуля (main)
log = logging.getLogger(__name__)


# 2. Настройка подключения к Redis
# Данные для подключения также берутся из переменных окружения
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True,  # Автоматически декодировать ответы из байтов в строки
)

# --- КОНЕЦ БЛОКА НАСТРОЙКИ ---


# Настройка FastAPI приложения
app = FastAPI(
    title="Tender Parser Service",
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version="2.0.0",
)

# Директория для временного хранения загруженных файлов
UPLOAD_DIRECTORY = Path("temp_uploads")
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)


def run_parsing_in_background(task_id: str, file_path: str):
    """
    Выполняет парсинг в фоновом режиме и обновляет статус задачи в Redis.

    Args:
        task_id (str): Уникальный идентификатор задачи.
        file_path (str): Путь к временному файлу для обработки.
    """
    log.info(f"Task {task_id}: Обработка файла {file_path} началась в фоне.")

    status_key = f"task_status:{task_id}"

    # Устанавливаем статус "в обработке" и время жизни ключа (например, 1 час)
    status_processing = json.dumps({"status": "processing"})
    redis_client.set(status_key, status_processing, ex=3600)

    try:
        parse_file(file_path)
        status_completed = json.dumps({"status": "completed"})
        redis_client.set(status_key, status_completed, ex=3600)
        log.info(f"Task {task_id}: Обработка успешно завершена.")
    except Exception as e:
        log.error(f"Task {task_id}: Произошла ошибка - {e}", exc_info=True)
        status_failed = json.dumps({"status": "failed", "error": str(e)})
        redis_client.set(status_key, status_failed, ex=3600)


@app.post("/parse-tender/", status_code=202, tags=["Tender Processing"])
async def create_parsing_task(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
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
    log.info(f"Task {task_id}: Получен файл {file.filename}. Сохранение в: {temp_file_path}")

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"Task {task_id}: Не удалось сохранить файл: {e}")
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл на сервере.")
    finally:
        file.file.close()

    # Добавляем задачу в фоновое выполнение
    background_tasks.add_task(run_parsing_in_background, task_id, str(temp_file_path))

    return {"task_id": task_id, "message": "Задача по обработке файла принята."}


@app.get("/tasks/{task_id}/status", tags=["Task Status"])
async def get_task_status(task_id: str):
    """
    Возвращает текущий статус задачи по ее ID из Redis.
    """
    status_key = f"task_status:{task_id}"
    task_json = redis_client.get(status_key)

    if not task_json:
        raise HTTPException(status_code=404, detail="Задача с таким ID не найдена.")

    return json.loads(task_json)


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Простая проверка работоспособности сервиса."""
    return {"status": "ok"}
