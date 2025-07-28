"""
Асинхронный скрипт для извлечения характеристик "стены в грунте".

Скрипт читает текстовый файл, содержащий описания строительных работ,
разделяет его на отдельные записи, группирует в батчи и асинхронно
отправляет в API языковой модели (LLM) для извлечения технических
параметров, таких как толщина стены, объемы бетона, марка бетона и
характеристики арматуры.

Результаты из всех батчей объединяются в единый JSON-объект и выводятся
в консоль. Скрипт обладает отказоустойчивостью за счет механизма
повторных попыток и гибкой валидации ответов от LLM.
"""

import asyncio
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import List, Optional, Any

import aiohttp
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

from prompts import SLURRY_WALL_PROMPT

# Загрузка переменных окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)

# --- 1. НАСТРОЙКИ И КОНФИГУРАЦИЯ ---


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
    model_name: str = Field(
        os.getenv("OLLAMA_MODEL", "mistral"), description="Название модели"
    )
    ollama_token: Optional[str] = Field(
        os.getenv("OLLAMA_TOKEN"), description="Токен авторизации"
    )
    input_file: Path = Field(Path("38_38_positions.md"), description="Входной файл")
    batch_size: int = Field(5, description="Размер батча для обработки")
    timeout: int = Field(300, description="Таймаут запроса")
    max_retries: int = Field(3, description="Макс. кол-во повторных попыток")
    retry_delay: int = Field(5, description="Задержка между попытками (сек)")

    class Config:
        arbitrary_types_allowed = True
        validate_assignment = True


# --- 2. ВАЛИДАЦИЯ ОТВЕТА LLM (Pydantic) ---


class SlurryWallSpecs(BaseModel):
    """
    Модель Pydantic для хранения извлеченных характеристик "стены в грунте".

    Attributes:
        thickness_mm (Optional[float]): Толщина стены в миллиметрах.
        concrete_volume_m3 (Optional[List[float]]): Список объемов бетона в м³.
        concrete_grade (Optional[str]): Марка используемого бетона.
        rebar_type (Optional[str]): Тип (класс) используемой арматуры.
        rebar_total_weight_t (Optional[List[float]]): Список весов арматуры в тоннах.
    """

    thickness_mm: Optional[float] = None
    concrete_volume_m3: Optional[List[float]] = None
    concrete_grade: Optional[str] = None
    rebar_type: Optional[str] = None
    rebar_total_weight_t: Optional[List[float]] = None


class LLMResponse(BaseModel):
    """
    Модель Pydantic для валидации корневой структуры JSON-ответа от LLM.

    Ожидается, что ответ будет содержать вложенный объект с ключом 'slurry_wall_specs'.

    Attributes:
        slurry_wall_specs (Optional[SlurryWallSpecs]): Вложенный объект с
            характеристиками "стены в грунте".
    """

    slurry_wall_specs: Optional[SlurryWallSpecs] = None


def parse_lot_records(raw_text: str) -> list:
    """
    Разбивает сплошной текст на структурированные записи по маркеру.

    Каждая запись в исходном тексте должна начинаться с маркера '**Наименование:**'.

    Args:
        raw_text (str): Входной текст, содержащий одну или несколько записей.

    Returns:
        list: Список словарей, где каждый словарь представляет одну запись
              и содержит 'record_id', 'text' и 'title'.
    """
    records = []
    # Разделение по маркеру, сохраняя сам маркер в начале каждой строки
    blocks = re.split(r"(?=\*\*Наименование:)", raw_text.strip())
    for i, block in enumerate(filter(None, blocks)):
        clean_block = block.strip()
        title_match = re.search(r"\*\*Наименование:?\*\*\s*(.*)", clean_block)
        title = (
            title_match.group(1).strip()
            if title_match
            else f"Неизвестная позиция {i+1}"
        )
        records.append({"record_id": i, "text": clean_block, "title": title})
    return records


decoder = json.JSONDecoder()


def extract_final_json(text: str) -> dict:
    """
    Находит и декодирует первый валидный JSON-объект из строки.

    Функция итерирует по тексту, находя все символы '{'. С позиции каждого
    такого символа она пытается декодировать JSON. Возвращается первый
    успешно декодированный объект, который является словарем и содержит
    ключ 'slurry_wall_specs'. Этот метод устойчив к "мусору", который
    LLM может добавлять до или после JSON-объекта.

    Args:
        text (str): Строка ответа от LLM, потенциально содержащая JSON.

    Returns:
        dict: Первый найденный и валидный JSON-объект или пустой словарь.
    """
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[m.start() :])
            if isinstance(obj, dict) and "slurry_wall_specs" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return {}


class LLMProcessor:
    """
    Класс, инкапсулирующий логику взаимодействия с LLM.

    Отвечает за подготовку запросов, асинхронную отправку, обработку
    ответов, реализацию механизма повторных попыток и гибкую валидацию
    полученных данных.
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

    async def process_batch(
        self, session: aiohttp.ClientSession, batch_text: str, batch_num: int
    ) -> Optional[SlurryWallSpecs]:
        """
        Асинхронно отправляет один батч на обработку и валидирует результат.

        Выполняет POST-запрос к API LLM. В случае успеха извлекает JSON
        из ответа и пытается его валидировать. Реализована двухступенчатая
        валидация: сначала проверяется идеальная структура, затем - "плоский"
        JSON, который оборачивается в нужную структуру.
        При сетевых ошибках или таймаутах выполняет повторные попытки.

        Args:
            session (aiohttp.ClientSession): Активная сессия aiohttp.
            batch_text (str): Текст текущего батча для отправки.
            batch_num (int): Порядковый номер батча (для логирования).

        Returns:
            Optional[SlurryWallSpecs]: Объект с извлеченными данными или None,
                                       если данные не найдены или произошла
                                       неустранимая ошибка.
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
                    response.raise_for_status()
                    response_json = await response.json()

                    if (
                        "message" not in response_json
                        or "content" not in response_json["message"]
                    ):
                        logging.error(
                            f"Батч {batch_num}: Некорректный ответ от LLM: {response_json.get('error')}"
                        )
                        continue  # Попробуем еще раз

                    raw_content = response_json["message"]["content"]
                    logging.debug(
                        f"Батч {batch_num}: ПОЛУЧЕН СЫРОЙ ОТВЕТ:\n--- ОТВЕТ LLM ---\n{raw_content}\n--- КОНЕЦ ОТВЕТА ---"
                    )

                    extracted_data = extract_final_json(raw_content)
                    if not extracted_data:
                        logging.warning(
                            f"Батч {batch_num}: Не удалось извлечь JSON из ответа."
                        )
                        return None  # Если JSON нет, нет смысла пробовать снова

                    validated_response = None
                    try:
                        # 1. Первая попытка валидации - ожидаемая структура
                        validated_response = LLMResponse(**extracted_data)
                    except ValidationError:
                        # 2. Вторая попытка - если модель вернула "плоский" JSON
                        logging.warning(
                            f"Батч {batch_num}: Структура не соответствует LLMResponse. Пробуем завернуть ответ."
                        )
                        try:
                            # Заворачиваем "плоский" JSON в ожидаемую структуру
                            wrapped_data = {
                                "slurry_wall_specs": SlurryWallSpecs(**extracted_data)
                            }
                            validated_response = LLMResponse(**wrapped_data)
                        except ValidationError as e:
                            logging.error(
                                f"Батч {batch_num}: Ошибка валидации даже после оборачивания: {e}\nИзвлеченные данные: {extracted_data}"
                            )
                            return None

                    if (
                        validated_response
                        and validated_response.slurry_wall_specs
                        and any(
                            v is not None
                            for v in validated_response.slurry_wall_specs.model_dump().values()
                        )
                    ):
                        logging.info(
                            f"Батч {batch_num}: Валидированные данные: {validated_response.slurry_wall_specs.model_dump()}"
                        )
                        return validated_response.slurry_wall_specs
                    else:
                        logging.warning(
                            f"Батч {batch_num}: Данные не содержат параметров стены в грунте или пусты."
                        )
                        return None

            except aiohttp.ClientResponseError as e:
                logging.warning(
                    f"Батч {batch_num} Попытка {attempt + 1}: Ошибка сети/сервера: {e}"
                )
            except asyncio.TimeoutError:
                logging.warning(
                    f"Батч {batch_num} Попытка {attempt + 1}: Таймаут запроса."
                )
            except Exception as e:
                # Общий обработчик на случай других непредвиденных ошибок
                logging.error(
                    f"Батч {batch_num} Попытка {attempt + 1}: Произошла непредвиденная ошибка: {e}"
                )

            if attempt < self.settings.max_retries - 1:
                await asyncio.sleep(self.settings.retry_delay)

        logging.error(f"Батч {batch_num}: Превышено количество попыток.")
        return None


def merge_slurry_wall_specs(batch_results: List[Optional[SlurryWallSpecs]]) -> dict:
    """
    Объединяет результаты из всех батчей в один итоговый JSON-объект.

    Функция итерирует по списку результатов, полученных от обработки батчей.
    Она агрегирует все числовые списки (объемы, веса) и берет первое
    не-None значение для строковых и числовых полей (толщина, марка).

    Args:
        batch_results (List[Optional[SlurryWallSpecs]]): Список результатов,
            возвращенных методом `process_batch`. Может содержать None.

    Returns:
        dict: Финальный словарь с объединенными характеристиками "стены в грунте",
              готовый для сериализации в JSON.
    """
    final_specs: dict[str, Any] = {
        "thickness_mm": None,
        "concrete_volume_m3": None,
        "concrete_grade": None,
        "rebar_type": None,
        "rebar_total_weight_t": None,
    }

    concrete_volumes = []
    rebar_weights = []

    for result in batch_results:
        # Пропускаем пустые результаты или исключения
        if not isinstance(result, SlurryWallSpecs) or not any(
            v is not None for v in result.model_dump().values()
        ):
            continue
        # Берем первое не-None значение для уникальных полей
        if result.thickness_mm is not None and final_specs["thickness_mm"] is None:
            final_specs["thickness_mm"] = result.thickness_mm
        if result.concrete_grade is not None and final_specs["concrete_grade"] is None:
            final_specs["concrete_grade"] = result.concrete_grade
        if result.rebar_type is not None and final_specs["rebar_type"] is None:
            final_specs["rebar_type"] = result.rebar_type

        # Собираем все значения из списков
        if result.concrete_volume_m3:
            concrete_volumes.extend(result.concrete_volume_m3)
        if result.rebar_total_weight_t:
            rebar_weights.extend(result.rebar_total_weight_t)

    # Заполняем агрегированные списки, если они не пусты
    final_specs["concrete_volume_m3"] = concrete_volumes if concrete_volumes else None
    final_specs["rebar_total_weight_t"] = rebar_weights if rebar_weights else None

    return {"slurry_wall_specs": final_specs}


async def main():
    """
    Главная асинхронная функция, управляющая процессом обработки.

    Выполняет следующие шаги:
    1. Инициализирует настройки.
    2. Читает и парсит входной файл на записи.
    3. Создает батчи из записей.
    4. Асинхронно запускает обработку всех батчей с помощью `asyncio.gather`.
    5. Объединяет полученные результаты в один итоговый объект.
    6. Выводит результат в стандартный вывод в формате JSON.
    """
    settings = Settings()  # type: ignore

    if not settings.input_file.exists():
        logging.error(f"Файл не найден: {settings.input_file}")
        print(json.dumps({"slurry_wall_specs": {}}, indent=2, ensure_ascii=False))
        return

    document = settings.input_file.read_text(encoding="utf-8")
    records = parse_lot_records(document)
    if not records:
        logging.warning("Записи не найдены в документе.")
        print(json.dumps({"slurry_wall_specs": {}}, indent=2, ensure_ascii=False))
        return

    processor = LLMProcessor(settings, SLURRY_WALL_PROMPT)
    async with aiohttp.ClientSession() as session:
        tasks = []
        num_batches = math.ceil(len(records) / settings.batch_size)

        for i in range(num_batches):
            batch_start = i * settings.batch_size
            batch_end = batch_start + settings.batch_size
            current_batch = records[batch_start:batch_end]
            logging.info(f"Подготовка батча {i+1}/{num_batches}")

            batch_text = "\n".join(
                [
                    f"### ЗАПИСЬ ID {record['record_id']} ###\n{record['text']}"
                    for record in current_batch
                ]
            )
            task = processor.process_batch(session, batch_text, i + 1)
            tasks.append(task)

        logging.info(f"Отправка {len(tasks)} батчей на асинхронную обработку...")
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logging.error(
                    f"Батч {i+1}: Во время выполнения задачи произошла ошибка: {result}"
                )
            elif isinstance(result, SlurryWallSpecs) and any(
                v is not None for v in result.model_dump().values()
            ):
                logging.info(f"Батч {i+1}: Найдены параметры: {result.model_dump()}")
            else:
                logging.info(
                    f"Батч {i+1}: Полезные данные не найдены или произошла ошибка при обработке."
                )

    filtered_results = [
        r for r in batch_results if isinstance(r, (SlurryWallSpecs, type(None)))
    ]
    final_result = merge_slurry_wall_specs(filtered_results)

    print("--- ИТОГОВЫЙ РЕЗУЛЬТАТ ---")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
