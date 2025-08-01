"""
Асинхронный скрипт для извлечения данных из текстовых записей с помощью LLM.

Скрипт читает текстовый файл, разделяет его на отдельные записи,
группирует их в батчи и асинхронно отправляет в API языковой модели (LLM)
для извлечения числовых данных (объемов). Результаты агрегируются и выводятся
в формате JSON.

Основные возможности:
- Загрузка настроек из переменных окружения.
- Асинхронная обработка батчей для высокой производительности.
- Механизм повторных попыток при сбоях сети или сервера.
- Валидация ответов от LLM с использованием Pydantic.
"""

import asyncio
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import List, Optional

import aiohttp
from dotenv import load_dotenv
from prompts import PIT_EXCAVATION_PROMPT
from pydantic import BaseModel, Field, ValidationError

# --- 1. УПРАВЛЕНИЕ НАСТРОЙКАМИ (Pydantic) ---

load_dotenv()


class Settings(BaseModel):
    """
    Класс для хранения и валидации всех настроек скрипта.

    Загружает конфигурацию из переменных окружения или использует значения по умолчанию.

    Attributes:
        ollama_url (str): URL API для чата Ollama.
        model_name (str): Название используемой модели LLM.
        ollama_token (Optional[str]): Необязательный токен авторизации для API.
        input_file (Path): Путь к входному файлу с текстовыми данными.
        batch_size (int): Количество записей, обрабатываемых в одном батче.
        timeout (int): Таймаут для каждого HTTP-запроса в секундах.
        max_retries (int): Максимальное количество повторных попыток при неудачном запросе.
        retry_delay (int): Задержка между повторными попытками в секундах.
    """

    ollama_url: str = Field(
        os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
        description="URL API Ollama",
    )
    model_name: str = Field(os.getenv("OLLAMA_MODEL", "mistral"), description="Название модели")
    ollama_token: Optional[str] = Field(os.getenv("OLLAMA_TOKEN"), description="Токен авторизации")
    input_file: Path = Field(Path("163_163_positions.md"), description="Входной файл")
    batch_size: int = Field(10, description="Размер батча для обработки")
    timeout: int = Field(300, description="Таймаут запроса")
    max_retries: int = Field(3, description="Макс. кол-во повторных попыток")
    retry_delay: int = Field(5, description="Задержка между попытками (сек)")


# --- 2. ВАЛИДАЦИЯ ОТВЕТА LLM (Pydantic) ---


class LLMResponse(BaseModel):
    """
    Модель Pydantic для валидации данных, извлеченных из JSON ответа LLM.

    Ожидает, что ответ будет содержать ключ 'pit_volumes_m3' со списком чисел.

    Attributes:
        pit_volumes_m3 (List[float]): Список извлеченных объемов в кубических метрах.
    """

    pit_volumes_m3: List[float] = Field(default_factory=list)


# --- 3. РЕФАКТОРИНГ ЛОГИКИ ---

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_lot_records(raw_text: str) -> list:
    """
    Разбивает сплошной текст на структурированные записи по разделителю '---'.
    Для каждой записи извлекает поля "Наименование" и "Единица измерения".
    """
    records = []
    # Разделяем документ на отдельные блоки по '---'
    blocks = raw_text.strip().split("---")

    # Пропускаем заголовок документа (первый блок до '---')
    for i, block in enumerate(filter(None, blocks[1:])):
        clean_block = block.strip()
        if not clean_block:
            continue

        # Используем регулярные выражения для точного извлечения полей
        title_match = re.search(r"\*\*Наименование:\*\*\s*(.*)", clean_block)
        unit_match = re.search(r"\*\*Единица измерения:\*\*\s*([\w\.]+)", clean_block)

        title = title_match.group(1).strip() if title_match else f"Неизвестная позиция {i+1}"
        # Извлекаем единицу измерения и убираем точку в конце, если она есть
        unit = unit_match.group(1).strip().replace(".", "") if unit_match else None

        records.append(
            {
                "record_id": i,
                "text": clean_block,
                "title": title,
                "unit": unit,  # Добавляем новое поле 'unit'
            }
        )

    logging.info(f"Найдено и разобрано {len(records)} записей.")
    return records


def filter_records_by_unit(records: list, target_unit: str = "м3") -> list:
    """
    Фильтрует список записей, оставляя только те, у которых поле 'unit'
    точно совпадает с целевой единицей измерения.

    Args:
        records (list): Список словарей с записями из парсера.
        target_unit (str): Целевая единица измерения (например, "м3").

    Returns:
        list: Отфильтрованный список записей.
    """
    # Фильтруем по точному совпадению в поле 'unit'
    filtered_records = [record for record in records if record.get("unit") == target_unit]

    logging.info(
        f"Из {len(records)} записей после фильтрации по единице измерения '{target_unit}' "
        f"осталось {len(filtered_records)}."
    )
    return filtered_records


def extract_final_json(response_text: str) -> dict:
    """
    Извлекает последний валидный JSON-объект из текстовой строки.

    Часто LLM возвращают JSON в окружении дополнительного текста. Эта функция
    находит последнюю открывающую фигурную скобку и пытается декодировать
    подстроку от нее до конца.

    Args:
        response_text (str): Строка, полученная от LLM, потенциально содержащая JSON.

    Returns:
        dict: Распарсенный JSON-объект или пустой словарь, если JSON не найден
              или произошла ошибка декодирования.
    """
    last_brace_index = response_text.rfind("{")
    if last_brace_index == -1:
        return {}
    try:
        return json.loads(response_text[last_brace_index:])
    except json.JSONDecodeError:
        return {}


class LLMProcessor:
    """
    Класс, инкапсулирующий логику взаимодействия с API LLM.

    Отвечает за подготовку запросов, отправку, обработку ответов и
    реализацию механизма повторных попыток.

    Attributes:
        settings (Settings): Объект с настройками скрипта.
        prompt (str): Системный промпт для LLM.
        headers (dict): HTTP-заголовки для запросов к API.
    """

    def __init__(self, settings: Settings, prompt: str):
        """
        Инициализирует процессор LLM.

        Args:
            settings (Settings): Объект с настройками скрипта.
            prompt (str): Системный промпт, который будет использоваться для запросов.
        """
        self.settings = settings
        self.prompt = prompt
        self.headers = {"Content-Type": "application/json"}
        if self.settings.ollama_token:
            self.headers["Authorization"] = f"Bearer {self.settings.ollama_token}"

    async def process_batch(self, session: aiohttp.ClientSession, batch_text: str, batch_num: int) -> List[float]:
        """
        Асинхронно отправляет один батч на обработку в LLM с логикой повторных попыток.

        Args:
            session (aiohttp.ClientSession): Активная сессия aiohttp.
            batch_text (str): Текст текущего батча для отправки.
            batch_num (int): Порядковый номер батча (для логирования).

        Returns:
            List[float]: Список извлеченных числовых значений (объемов) или
                         пустой список в случае ошибки.
        """
        payload = {
            "model": self.settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": self.prompt.replace("{Document}", batch_text),
                }
            ],
            "stream": False,
            "options": {"temperature": 0.0},
        }

        for attempt in range(self.settings.max_retries):
            try:
                async with session.post(
                    self.settings.ollama_url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=self.settings.timeout),
                ) as response:
                    response.raise_for_status()  # Вызовет исключение для статусов 4xx/5xx
                    response_json = await response.json()

                    if "message" not in response_json or "content" not in response_json["message"]:
                        logging.error(f"Батч {batch_num}: Некорректный ответ от LLM: {response_json.get('error')}")
                        return []

                    llm_full_response_text = response_json["message"]["content"]
                    logging.debug(f"Батч {batch_num}: Полный ответ от LLM:\n{llm_full_response_text}")

                    extracted_data = extract_final_json(response_json["message"]["content"])

                    validated_response = LLMResponse(**extracted_data)
                    return validated_response.pit_volumes_m3

            except aiohttp.ClientError as e:
                logging.warning(f"Батч {batch_num} Попытка {attempt + 1}: Ошибка сети/сервера: {e}")
            except asyncio.TimeoutError:
                logging.warning(f"Батч {batch_num} Попытка {attempt + 1}: Таймаут запроса.")
            except ValidationError as e:
                logging.error(f"Батч {batch_num}: Ошибка валидации данных от LLM: {e}")
                return []  # Нет смысла повторять, если данные невалидны

            if attempt < self.settings.max_retries - 1:
                await asyncio.sleep(self.settings.retry_delay)

        logging.error(f"Батч {batch_num}: Превышено количество попыток.")
        return []


# --- 4. ОСНОВНАЯ АСИНХРОННАЯ ФУНКЦИЯ ---
async def main():
    """
    Главная асинхронная функция запуска скрипта.

    Выполняет следующие шаги:
    1. Инициализирует настройки.
    2. Читает и парсит входной файл.
    3. Создает батчи из записей.
    4. Асинхронно отправляет все батчи на обработку.
    5. Собирает результаты и выводит итоговый JSON в консоль.
    """
    settings = Settings()  # type: ignore

    if not settings.input_file.exists():
        logging.error(f"Файл не найден: {settings.input_file}")
        return

    document = settings.input_file.read_text(encoding="utf-8")
    all_records = parse_lot_records(document)
    if not all_records:
        logging.warning("Записи не найдены в документе.")
        return

    records_to_process = filter_records_by_unit(all_records, target_unit="м3")

    if not records_to_process:
        logging.warning("После фильтрации не осталось записей для обработки.")
        return

    processor = LLMProcessor(settings, PIT_EXCAVATION_PROMPT)
    all_volumes = []

    async with aiohttp.ClientSession() as session:
        tasks = []
        num_batches = math.ceil(len(records_to_process) / settings.batch_size)

        for i in range(num_batches):
            batch_start = i * settings.batch_size
            batch_end = batch_start + settings.batch_size
            current_batch = records_to_process[batch_start:batch_end]
            logging.info(f"Подготовка батча {i+1}/{num_batches}")

            batch_text = "\n".join(
                [f"### ЗАПИСЬ ID {record['record_id']} ###\n{record['text']}" for record in current_batch]
            )
            task = processor.process_batch(session, batch_text, i + 1)
            tasks.append(task)

        logging.info(f"Отправка {len(tasks)} батчей на асинхронную обработку...")
        batch_results = await asyncio.gather(*tasks)

        for i, volumes in enumerate(batch_results):
            if volumes:
                all_volumes.extend(volumes)
                logging.info(f"Батч {i+1}: Успешно обработан, найдено объемов: {volumes}")
            else:
                logging.info(f"Батч {i+1}: Объемы не найдены или произошла ошибка.")

    final_result = {"pit_volumes_m3": all_volumes}
    print("--- ИТОГОВЫЙ РЕЗУЛЬТАТ ---")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
