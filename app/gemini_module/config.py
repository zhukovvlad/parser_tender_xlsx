# app/gemini_module/config.py
"""
Конфигурация для модуля анализа тендерных документов.

Этот модуль содержит настройки по умолчанию, параметры моделей
и вспомогательные функции для работы с Gemini API.
"""

from pathlib import Path
from typing import Dict, List, Optional

# ======================================================================
# === КОНФИГУРАЦИЯ GEMINI API ===
# ======================================================================

# Настройки модели по умолчанию
MODEL_CONFIG = {
    "default_model": "models/gemini-2.5-flash",  # Обновляем до актуальной версии
    "fallback_model": "models/gemini-2.5-flash",
    "temperature": 0.1,  # Низкая температура для более детерминированных результатов
    "max_tokens": 8192,
}

# Настройки для обработки файлов
FILE_CONFIG = {
    "supported_extensions": [".md", ".txt", ".json", ".xlsx", ".docx"],
    "max_file_size_mb": 50,
    "default_input_file": "42_42_positions.md",
    "output_format": "json",
    "encoding": "utf-8",
}

# Настройки логирования и отладки
LOGGING_CONFIG = {
    "default_level": "INFO",
    "verbose_level": "DEBUG",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "enable_file_logging": True,
    "log_file": "logs/gemini.log",
    "logger_name": "gemini_module",
}

# Настройки для retry и таймаутов
RETRY_CONFIG = {
    "max_retries": 3,
    "base_delay": 1.0,  # секунды
    "max_delay": 60.0,  # секунды
    "backoff_factor": 2.0,
    "timeout": 120,  # секунды
}

# ======================================================================
# === МЕТАДАННЫЕ И СООБЩЕНИЯ ===
# ======================================================================

# Метаданные для результатов анализа
ANALYSIS_METADATA = {
    "version": "2.0.0",
    "analyzer": "TenderProcessor",
    "api_provider": "Google Gemini",
    "model": MODEL_CONFIG["default_model"],
}

# Шаблоны сообщений с эмодзи
MESSAGES = {
    # Процесс анализа
    "start": "🚀 Запускаем интеллектуальный анализ документа",
    "upload": "📤 Загружаю файл на сервер",
    "classify": "⏳ Определяю категорию документа...",
    "extract": "⏳ Извлекаю данные по шаблону",
    "success": "✅ Анализ завершён успешно",
    # Статусы и результаты
    "file_uploaded": "✅ Файл загружен. ID: {file_id}",
    "classified": "✅ Документ классифицирован как: '{category}'",
    "data_extracted": "✅ Данные извлечены по шаблону для '{category}'",
    # Ошибки и предупреждения
    "error": "❌ Произошла ошибка",
    "warning": "⚠️ Предупреждение",
    "file_not_found": "❌ Файл не найден: {filename}",
    "api_key_missing": "❌ API ключ не найден. Установите переменную окружения GOOGLE_API_KEY",
    "invalid_category": "⚠️ Модель вернула непредусмотренный ответ: '{result}'. Возвращаем fallback.",
    # Очистка и завершение
    "cleanup": "🧹 Очищаю ресурсы...",
    "file_deleted": "🗑️ Файл {file_id} удалён.",
    "cleanup_error": "⚠️ Ошибка при очистке ресурсов: {error}",
    # Сохранение результатов
    "saving": "💾 Сохраняю результаты в файл: {filename}",
    "saved": "💾 Результаты сохранены в файл: {filename}",
    "save_error": "❌ Ошибка при сохранении результатов: {error}",
}

# ======================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
# ======================================================================


def get_model_config(model_name: Optional[str] = None) -> Dict:
    """
    Возвращает конфигурацию модели.

    Args:
        model_name: Имя модели (опционально)

    Returns:
        Словарь с конфигурацией модели
    """
    config = MODEL_CONFIG.copy()
    if model_name:
        config["model"] = model_name
    else:
        config["model"] = config["default_model"]
    return config


def validate_input_file(file_path: Path) -> tuple[bool, Optional[str]]:
    """
    Проверяет валидность входного файла.

    Args:
        file_path: Путь к файлу

    Returns:
        Кортеж (валиден, сообщение об ошибке)
    """
    if not file_path.exists():
        return False, f"Файл не существует: {file_path}"

    if file_path.suffix.lower() not in FILE_CONFIG["supported_extensions"]:
        supported = ", ".join(FILE_CONFIG["supported_extensions"])
        return False, f"Неподдерживаемое расширение файла. Поддерживаются: {supported}"

    # Проверка размера файла
    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > FILE_CONFIG["max_file_size_mb"]:
        return False, f"Файл слишком большой: {size_mb:.1f}MB (максимум: {FILE_CONFIG['max_file_size_mb']}MB)"

    return True, None


def get_available_test_files(directory: Path = None) -> List[Path]:
    """
    Возвращает список доступных тестовых файлов.

    Args:
        directory: Директория для поиска (по умолчанию текущая)

    Returns:
        Список путей к тестовым файлам
    """
    if directory is None:
        directory = Path(".")

    test_files = []
    for ext in FILE_CONFIG["supported_extensions"]:
        test_files.extend(directory.glob(f"*{ext}"))

    return sorted(test_files)


def create_error_report(error: Exception, context: Dict) -> Dict:
    """
    Создаёт детальный отчёт об ошибке.

    Args:
        error: Исключение
        context: Контекст выполнения

    Returns:
        Словарь с информацией об ошибке
    """
    return {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context,
        "metadata": ANALYSIS_METADATA,
        "timestamp": context.get("timestamp"),
        "file_path": context.get("file_path"),
    }


def get_message(key: str, **kwargs) -> str:
    """
    Возвращает отформатированное сообщение.

    Args:
        key: Ключ сообщения
        **kwargs: Параметры для форматирования

    Returns:
        Отформатированное сообщение
    """
    message_template = MESSAGES.get(key, f"Неизвестное сообщение: {key}")
    try:
        return message_template.format(**kwargs)
    except KeyError as e:
        return f"{message_template} (ошибка форматирования: {e})"


# ======================================================================
# === ЭКСПОРТ КОНСТАНТ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ ===
# ======================================================================

# Экспортируем основные константы для легкого импорта
DEFAULT_MODEL = MODEL_CONFIG["default_model"]
SUPPORTED_EXTENSIONS = FILE_CONFIG["supported_extensions"]
MAX_FILE_SIZE_MB = FILE_CONFIG["max_file_size_mb"]
DEFAULT_INPUT_FILE = FILE_CONFIG["default_input_file"]
