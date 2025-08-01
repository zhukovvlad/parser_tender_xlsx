# app/gemini_module/processor.py

import json
import os
import re

from google import genai

from .config import DEFAULT_MODEL, get_message
from .logger import get_gemini_logger


class TenderProcessor:
    """
    Класс для полной обработки тендерного файла с помощью Gemini API.
    """

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.file = None
        self.logger = get_gemini_logger()

    def upload(self, file_path: str):
        """Загружает файл на сервер Gemini."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Файл не найден: {file_path}")

        self.logger.info(f"Загружаю файл: {file_path}")
        self.file = self.client.files.upload(file=file_path)
        self.logger.info(get_message("file_uploaded", file_id=self.file.name))
        return self

    def analyze(self, prompt: str, model_name: str = None):
        """Базовый метод для отправки запроса к файлу."""
        if not self.file:
            raise ValueError("Файл не загружен. Вызовите .upload()")

        # Используем модель из конфига, если не указана явно
        model = model_name or DEFAULT_MODEL

        self.logger.debug(f"Отправляю запрос к модели {model}")
        response = self.client.models.generate_content(model=model, contents=[self.file, prompt])

        if not response.candidates:
            self.logger.warning("Модель не вернула кандидатов в ответе")
            return ""

        result = response.candidates[0].content.parts[0].text.strip()
        self.logger.debug(f"Получен ответ длиной {len(result)} символов")
        return result

    def classify(self, categories: list[str], fallback_label: str = "не найдено") -> str:
        """Классифицирует документ строго по заданному списку категорий."""
        if not self.file:
            raise ValueError("Файл не загружен.")

        categories_str = ", ".join([f"'{cat}'" for cat in categories])
        self.logger.debug(f"Классифицирую документ по категориям: {categories_str}")

        prompt = f"""
        Ты — инженер-сметчик. На основе краткого заголовка и при необходимости — полного текста работ, определи, к какой категории относится лот строительного тендера. Выбери ОДНУ категорию из списка: {categories_str}.
        Если не подходит ни одна, верни: '{fallback_label}'.
        Ответ должен содержать ТОЛЬКО название категории или метку '{fallback_label}'.
        """
        result = self.analyze(prompt)

        if result not in categories and result != fallback_label:
            self.logger.warning(get_message("invalid_category", result=result))
            return fallback_label

        self.logger.info(f"Документ классифицирован как: {result}")
        return result

    def extract_json(self, category: str, configs: dict, model_name: str = None) -> dict:
        """
        Извлекает данные, используя JSON-структуру и промпт-подсказку,
        соответствующие переданной категории.
        """
        self.logger.debug(f"Извлекаю JSON данные для категории: {category}")

        config = configs.get(category)
        if not config:
            raise ValueError(f"Конфигурация для категории '{category}' не найдена.")

        json_structure_prompt = config.get("json_structure")
        if not json_structure_prompt:
            raise ValueError(f"Структура JSON для категории '{category}' не найдена в конфигурации.")

        prompt_hint = config.get(
            "prompt_hint",
            "Проанализируй документ и извлеки из него ключевые параметры.",
        )
        full_prompt = f"""
        {prompt_hint}

        Твой ответ должен быть СТРОГО в формате JSON, без пояснений или markdown-оберток.
        Используй эту структуру:
        {json_structure_prompt}
        """
        response_text = self.analyze(full_prompt, model_name=model_name)

        try:
            clean = re.sub(r"```(?:json)?\s*(.*?)```", r"\1", response_text, flags=re.DOTALL).strip()
            result = json.loads(clean)
            self.logger.info(f"Успешно извлечены JSON данные для категории '{category}'")
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"Не удалось распарсить JSON для категории '{category}': {e}")
            self.logger.debug(f"Ответ модели:\n{response_text}")
            raise ValueError(f"Не удалось распарсить JSON. Ответ модели:\n{response_text}")

    def delete_uploaded_file(self):
        """Удаляет загруженный файл с серверов Google."""
        if not self.file:
            self.logger.info("Нет загруженного файла для удаления")
            return

        try:
            self.logger.info(f"Удаляю файл {self.file.name} с сервера")
            self.client.files.delete(name=self.file.name)
            self.logger.info(get_message("file_deleted", file_id=self.file.name))
            self.file = None
        except Exception as e:
            self.logger.error(get_message("cleanup_error", error=str(e)))
