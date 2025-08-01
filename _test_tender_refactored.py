#!/usr/bin/env python3
"""
Тестовый скрипт для анализа тендерных документов с помощью Gemini API.

Этот модуль демонстрирует использование TenderProcessor для:
1. Классификации документов по категориям
2. Извлечения структурированных данных из документов
3. Обработки ошибок и управления ресурсами

Использование:
    python _test_tender.py [путь_к_файлу]

Переменные окружения:
    GOOGLE_API_KEY: API ключ для доступа к Gemini API
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

from app.gemini_module import TenderProcessor, get_message, validate_input_file
from app.gemini_module.constants import FALLBACK_CATEGORY, TENDER_CATEGORIES, TENDER_CONFIGS

# Загружаем переменные окружения в начале
load_dotenv()


# Настройка логирования с учетом переменной окружения
def setup_logging(verbose: bool = False) -> None:
    """
    Настраивает логирование на основе переменных окружения и аргументов.

    Args:
        verbose: Если True, устанавливает DEBUG уровень независимо от .env
    """
    # Получаем уровень из переменной окружения или используем INFO по умолчанию
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Преобразуем строку в объект уровня логирования
    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }

    # Если передан verbose флаг, принудительно устанавливаем DEBUG
    if verbose:
        log_level = logging.DEBUG
        logger_msg = f"Уровень логирования: DEBUG (принудительно установлен через --verbose)"
    else:
        log_level = log_levels.get(log_level_str, logging.INFO)
        logger_msg = f"Уровень логирования: {log_level_str} (из переменной окружения LOG_LEVEL)"

    # Настраиваем базовую конфигурацию
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,  # Принудительно переопределяем существующую конфигурацию
    )

    # Сообщаем о текущем уровне логирования
    logger = logging.getLogger(__name__)
    logger.info(logger_msg)


logger = logging.getLogger(__name__)


class TenderAnalyzer:
    """
    Класс для анализа тендерных документов с использованием Gemini API.

    Attributes:
        api_key: API ключ для доступа к Gemini
        processor: Экземпляр TenderProcessor для обработки документов
    """

    def __init__(self, api_key: str):
        """
        Инициализация анализатора.

        Args:
            api_key: API ключ для Gemini API

        Raises:
            ValueError: Если API ключ пустой или None
        """
        if not api_key:
            raise ValueError("API ключ не может быть пустым")

        self.api_key = api_key
        self.processor: Optional[TenderProcessor] = None

    def analyze_document(self, input_file: Path) -> Dict:
        """
        Выполняет полный анализ документа.

        Args:
            input_file: Путь к файлу для анализа

        Returns:
            Словарь с результатами анализа

        Raises:
            FileNotFoundError: Если файл не существует
            ValueError: Если произошла ошибка при анализе
        """
        if not input_file.exists():
            raise FileNotFoundError(f"Файл не найден: {input_file}")

        logger.info("🚀 Запускаем интеллектуальный анализ документа: %s", input_file.name)

        try:
            # Инициализация и загрузка файла
            self.processor = TenderProcessor(api_key=self.api_key)
            self.processor.upload(str(input_file))

            # Этап 1: Классификация
            logger.info("⏳ Определяю категорию документа...")
            tender_type = self._classify_document()
            logger.info("✅ Документ классифицирован как: '%s'", tender_type)

            # Этап 2: Извлечение данных
            logger.info("⏳ Извлекаю данные по шаблону для '%s'...", tender_type)
            extracted_data = self._extract_data(tender_type)

            # Добавляем метаданные
            result = {
                **extracted_data,
                "determined_tender_type": tender_type,
                "source_file": input_file.name,
                "analysis_success": True,
            }

            logger.info("🎉 Анализ завершён успешно")
            return result

        except Exception as e:
            logger.error("❌ Ошибка при анализе документа: %s", str(e))
            return {
                "analysis_success": False,
                "error_message": str(e),
                "source_file": input_file.name,
            }
        finally:
            self._cleanup()

    def _classify_document(self) -> str:
        """Классифицирует документ по категориям."""
        if not self.processor:
            raise ValueError("Processor не инициализирован")

        return self.processor.classify(categories=TENDER_CATEGORIES, fallback_label=FALLBACK_CATEGORY)

    def _extract_data(self, tender_type: str) -> Dict:
        """Извлекает структурированные данные из документа."""
        if not self.processor:
            raise ValueError("Processor не инициализирован")

        return self.processor.extract_json(category=tender_type, configs=TENDER_CONFIGS)

    def _cleanup(self):
        """Очищает ресурсы и удаляет загруженные файлы."""
        if self.processor:
            try:
                self.processor.delete_uploaded_file()
            except Exception as e:
                logger.warning("⚠️ Ошибка при очистке ресурсов: %s", str(e))


def setup_environment() -> str:
    """
    Настраивает окружение и загружает API ключ.

    Returns:
        API ключ для Gemini

    Raises:
        ValueError: Если API ключ не найден
    """
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")

    if not api_key:
        raise ValueError("❌ API ключ не найден. Установите переменную окружения GOOGLE_API_KEY")

    return api_key


def parse_arguments() -> argparse.Namespace:
    """
    Парсит аргументы командной строки.

    Returns:
        Распарсенные аргументы
    """
    parser = argparse.ArgumentParser(
        description="Анализ тендерных документов с помощью Gemini API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python _test_tender.py                           # Использует файл по умолчанию
  python _test_tender.py document.md               # Анализирует указанный файл
  python _test_tender.py --output results.json    # Сохраняет результат в файл
        """,
    )

    parser.add_argument(
        "input_file",
        nargs="?",
        default="42_42_positions.md",
        help="Путь к файлу для анализа (по умолчанию: 42_42_positions.md)",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Путь для сохранения результата в JSON файл",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Включить подробный вывод",
    )

    return parser.parse_args()


def save_results(results: Dict, output_file: Path):
    """
    Сохраняет результаты анализа в JSON файл.

    Args:
        results: Результаты анализа
        output_file: Путь для сохранения
    """
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info("💾 Результаты сохранены в файл: %s", output_file)
    except Exception as e:
        logger.error("❌ Ошибка при сохранении результатов: %s", str(e))


def print_results(results: Dict):
    """
    Выводит результаты анализа в консоль.

    Args:
        results: Результаты анализа
    """
    print("\n" + "=" * 60)
    print("🎉 РЕЗУЛЬТАТЫ АНАЛИЗА ДОКУМЕНТА")
    print("=" * 60)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("=" * 60)


def main():
    """Основная функция программы."""
    try:
        # Парсинг аргументов
        args = parse_arguments()

        # Настройка логирования на основе .env и аргументов
        setup_logging(verbose=args.verbose)

        # Настройка окружения
        api_key = setup_environment()

        # Анализ документа
        analyzer = TenderAnalyzer(api_key)
        results = analyzer.analyze_document(Path(args.input_file))

        # Вывод результатов
        print_results(results)

        # Сохранение в файл (если указано)
        if args.output:
            save_results(results, args.output)

        # Возвращаем код выхода в зависимости от успеха
        return 0 if results.get("analysis_success", False) else 1

    except Exception as e:
        logger.error("❌ Критическая ошибка: %s", str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
