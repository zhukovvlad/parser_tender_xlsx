"""
Утилиты общего назначения для парсера тендерных документов.

Содержит вспомогательные функции для:
- Валидации данных
- Работы с файлами
- Форматирования данных
- Обработки ошибок
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from functools import wraps

logger = logging.getLogger(__name__)

# Регулярные выражения для валидации
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
PHONE_REGEX = re.compile(r'^[\+]?[\d\s\-\(\)]{7,15}$')
INN_REGEX = re.compile(r'^\d{10}$|^\d{12}$')


class ValidationError(Exception):
    """Исключение для ошибок валидации."""
    pass


class FileProcessingError(Exception):
    """Исключение для ошибок обработки файлов."""
    pass


def validate_email(email: str) -> bool:
    """
    Валидирует email адрес.
    
    Args:
        email: Строка с email адресом
        
    Returns:
        bool: True если email валиден
    """
    return bool(EMAIL_REGEX.match(email))


def validate_phone(phone: str) -> bool:
    """
    Валидирует номер телефона.
    
    Args:
        phone: Строка с номером телефона
        
    Returns:
        bool: True если телефон валиден
    """
    return bool(PHONE_REGEX.match(phone))


def validate_inn(inn: str) -> bool:
    """
    Валидирует ИНН (10 или 12 цифр).
    
    Args:
        inn: Строка с ИНН
        
    Returns:
        bool: True если ИНН валиден
    """
    return bool(INN_REGEX.match(inn))


def sanitize_filename(filename: str) -> str:
    """
    Очищает имя файла от недопустимых символов.
    
    Args:
        filename: Исходное имя файла
        
    Returns:
        str: Очищенное имя файла
    """
    # Удаляем недопустимые символы
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Ограничиваем длину
    if len(sanitized) > 200:
        name, ext = Path(sanitized).stem, Path(sanitized).suffix
        sanitized = name[:200-len(ext)] + ext
    return sanitized


def generate_file_hash(file_path: Union[str, Path]) -> str:
    """
    Генерирует MD5 хеш файла.
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        str: MD5 хеш файла
        
    Raises:
        FileProcessingError: При ошибке чтения файла
    """
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        raise FileProcessingError(f"Ошибка при генерации хеша файла: {e}")


def format_file_size(size_bytes: int) -> str:
    """
    Форматирует размер файла в человекочитаемом виде.
    
    Args:
        size_bytes: Размер в байтах
        
    Returns:
        str: Отформатированный размер
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def ensure_directory_exists(path: Union[str, Path]) -> Path:
    """
    Создает директорию если она не существует.
    
    Args:
        path: Путь к директории
        
    Returns:
        Path: Объект Path для созданной директории
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_json_load(file_path: Union[str, Path]) -> Optional[Dict[str, Any]]:
    """
    Безопасно загружает JSON файл.
    
    Args:
        file_path: Путь к JSON файлу
        
    Returns:
        Dict или None: Загруженные данные или None при ошибке
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке JSON файла {file_path}: {e}")
        return None


def safe_json_save(data: Dict[str, Any], file_path: Union[str, Path]) -> bool:
    """
    Безопасно сохраняет данные в JSON файл.
    
    Args:
        data: Данные для сохранения
        file_path: Путь к файлу
        
    Returns:
        bool: True если сохранение успешно
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении JSON файла {file_path}: {e}")
        return False


def retry_on_exception(max_retries: int = 3, delay: float = 1.0):
    """
    Декоратор для повторного выполнения функции при исключениях.
    
    Args:
        max_retries: Максимальное количество попыток
        delay: Задержка между попытками в секундах
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Попытка {attempt + 1} не удалась: {e}. Повтор через {delay} сек.")
                    time.sleep(delay)
            return None
        return wrapper
    return decorator


def measure_execution_time(func):
    """
    Декоратор для измерения времени выполнения функции.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = end_time - start_time
        logger.info(f"Функция {func.__name__} выполнена за {execution_time:.2f} секунд")
        return result
    return wrapper


def clean_text(text: str) -> str:
    """
    Очищает текст от лишних пробелов и символов.
    
    Args:
        text: Исходный текст
        
    Returns:
        str: Очищенный текст
    """
    if not text:
        return ""
    
    # Удаляем лишние пробелы
    text = re.sub(r'\s+', ' ', str(text))
    # Удаляем пробелы в начале и конце
    text = text.strip()
    return text


def normalize_currency(amount: Union[str, float, int]) -> Optional[float]:
    """
    Нормализует денежную сумму к float.
    
    Args:
        amount: Сумма в различных форматах
        
    Returns:
        float или None: Нормализованная сумма
    """
    if amount is None:
        return None
    
    try:
        # Если уже число
        if isinstance(amount, (int, float)):
            return float(amount)
        
        # Если строка
        if isinstance(amount, str):
            # Удаляем все кроме цифр, точки и запятой
            cleaned = re.sub(r'[^\d.,\-]', '', amount)
            if not cleaned:
                return None
            
            # Заменяем запятую на точку
            cleaned = cleaned.replace(',', '.')
            
            # Обрабатываем случай с тысячными разделителями
            if cleaned.count('.') > 1:
                parts = cleaned.split('.')
                if len(parts[-1]) <= 2:  # Последняя часть - копейки
                    cleaned = ''.join(parts[:-1]) + '.' + parts[-1]
                else:  # Все точки - тысячные разделители
                    cleaned = cleaned.replace('.', '')
            
            return float(cleaned)
    except (ValueError, TypeError):
        return None
    
    return None


def is_valid_coordinate(coord: str) -> bool:
    """
    Проверяет, является ли строка валидной Excel координатой (например, A1, B2).
    
    Args:
        coord: Строка координаты
        
    Returns:
        bool: True если координата валидна
    """
    return bool(re.match(r'^[A-Z]+\d+$', coord))


def generate_temporary_id() -> str:
    """
    Генерирует временный ID для файлов в fallback режиме.
    
    Returns:
        str: Временный ID
    """
    timestamp = int(time.time())
    random_part = hashlib.md5(str(timestamp).encode()).hexdigest()[:8]
    return f"temp_{timestamp}_{random_part}"


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Форматирует дату и время в строку.
    
    Args:
        dt: Объект datetime
        format_str: Формат строки
        
    Returns:
        str: Отформатированная дата
    """
    return dt.strftime(format_str)


def parse_datetime(date_str: str, format_str: str = "%Y-%m-%d %H:%M:%S") -> Optional[datetime]:
    """
    Парсит строку в объект datetime.
    
    Args:
        date_str: Строка с датой
        format_str: Формат строки
        
    Returns:
        datetime или None: Распарсенная дата
    """
    try:
        return datetime.strptime(date_str, format_str)
    except ValueError:
        return None


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Обрезает текст до указанной длины.
    
    Args:
        text: Исходный текст
        max_length: Максимальная длина
        suffix: Суффикс для обрезанного текста
        
    Returns:
        str: Обрезанный текст
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def get_file_extension(filename: str) -> str:
    """
    Возвращает расширение файла в нижнем регистре.
    
    Args:
        filename: Имя файла
        
    Returns:
        str: Расширение файла
    """
    return Path(filename).suffix.lower()


def is_empty_value(value: Any) -> bool:
    """
    Проверяет, является ли значение пустым.
    
    Args:
        value: Значение для проверки
        
    Returns:
        bool: True если значение пустое
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False