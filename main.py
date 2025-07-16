import logging
import os
import shutil
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse

# Импортируем вашу основную функцию парсинга из переименованного файла
from app.parse import parse_file

# Настройка FastAPI приложения
app = FastAPI(
    title="Tender Parser Service",
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version="1.0.0"
)

# Указываем временную директорию для хранения загруженных файлов
UPLOAD_DIRECTORY = Path("temp_uploads")
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

@app.post("/parse-tender/", tags=["Tender Processing"])
async def parse_tender_file(file: UploadFile = File(...)):
    """
    Принимает XLSX файл, сохраняет его временно и запускает
    полный цикл обработки в фоновом режиме (в данном примере - синхронно).
    """
    if not file.filename or not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Неверный формат файла. Пожалуйста, загрузите XLSX или XLS файл.")

    # Создаем безопасный путь для сохранения файла
    temp_file_path = UPLOAD_DIRECTORY / file.filename
    log.info(f"Получен файл: {file.filename}. Сохранение в: {temp_file_path}")

    # Сохраняем загруженный файл на диск
    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"Не удалось сохранить файл: {e}")
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить файл на сервере: {e}")
    finally:
        file.file.close()

    # --- Ключевой момент ---
    # Вызываем вашу существующую логику парсинга для сохраненного файла.
    # В реальном приложении этот вызов лучше делать в фоновой задаче
    # (например, с помощью Celery или встроенных BackgroundTasks FastAPI),
    # чтобы не заставлять клиента ждать.
    try:
        log.info(f"Запуск парсера для файла: {temp_file_path}")
        # Функция parse_file будет делать всё, что делала раньше,
        # включая отправку JSON на ваш Go-сервер
        parse_file(str(temp_file_path))
    except Exception as e:
        # Даже если парсер упадет, мы должны вернуть ответ клиенту (Go-серверу)
        log.error(f"Ошибка во время выполнения parse_file: {e}")
        # Можно вернуть ошибку, но для асинхронной логики лучше вернуть успех,
        # а ошибку обработать внутри (логи, уведомления).
        pass

    # Отвечаем немедленно, что задача принята
    return JSONResponse(
        status_code=202, # 202 Accepted
        content={"message": "Файл принят в обработку.", "filename": file.filename}
    )

@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Простая проверка работоспособности сервиса."""
    return {"status": "ok"}