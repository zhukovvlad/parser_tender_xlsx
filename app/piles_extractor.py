"""
Асинхронный скрипт для извлечения характеристик свай из проектной документации.

Скрипт читает текстовый файл, содержащий описания строительных работ,
разделяет его на отдельные записи, группирует в батчи и асинхронно
отправляет в API языковой модели (LLM) для извлечения технических
параметров свай (диаметр, количество, объемы, марки и т.д.),
игнорируя информацию об испытаниях.

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

# Убедитесь, что файл prompts.py находится в той же директории
from prompts import PILE_PROMPT

# Загрузка переменных окружения из .env
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --- 1. НАСТРОЙКИ И КОНФИГУРАЦИЯ ---

class Settings(BaseModel):
    """
    Класс для хранения и валидации всех настроек скрипта.
    Загружает конфигурацию из переменных окружения или использует значения по умолчанию.
    """
    ollama_url: str = Field(os.getenv(
        "OLLAMA_URL", "http://localhost:11434/api/chat"), description="URL API Ollama")
    model_name: str = Field(
        os.getenv("OLLAMA_MODEL", "mistral"), description="Название модели")
    ollama_token: Optional[str] = Field(
        os.getenv("OLLAMA_TOKEN"), description="Токен авторизации")
    input_file: Path = Field(Path("38_38_positions.md"), # Изменено имя файла по умолчанию
                             description="Входной файл")
    batch_size: int = Field(10, description="Размер батча для обработки")
    timeout: int = Field(300, description="Таймаут запроса")
    max_retries: int = Field(2, description="Макс. кол-во повторных попыток")
    retry_delay: int = Field(5, description="Задержка между попытками (сек)")

# --- 2. ВАЛИДАЦИЯ ОТВЕТА LLM (Pydantic) ---

class PileSpecs(BaseModel):
    """
    Модель Pydantic для хранения извлеченных характеристик свай.
    """
    diameter_mm: Optional[float] = None
    count: Optional[int] = None
    concrete_volume_m3: Optional[List[float]] = None
    concrete_grade: Optional[str] = None
    rebar_total_weight_t: Optional[List[float]] = None
    rebar_type: Optional[str] = None
    grouting_volume_m3: Optional[List[float]] = None


class LLMResponse(BaseModel):
    """
    Модель Pydantic для валидации корневой структуры JSON-ответа от LLM.
    """
    pile_specs: Optional[PileSpecs] = None

# --- 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И КЛАССЫ ---

def parse_lot_records(raw_text: str) -> list:
    """
    Разбивает сплошной текст на структурированные записи по маркеру.
    Каждая запись в исходном тексте должна начинаться с маркера '**Наименование:**'.
    """
    records = []
    # Разделение по маркеру, сохраняя сам маркер в начале каждой строки
    blocks = re.split(r'(?=\*\*Наименование:)', raw_text.strip())
    for i, block in enumerate(filter(None, blocks)):
        clean_block = block.strip()
        if not clean_block:
            continue
        title_match = re.search(r'\*\*Наименование:\*\*\s*(.*)', clean_block)
        title = title_match.group(
            1).strip() if title_match else f"Неизвестная позиция {i+1}"
        records.append({"record_id": i, "text": clean_block, "title": title})
    logging.info(f"Найдено и разобрано {len(records)} записей.")
    return records


decoder = json.JSONDecoder()

def extract_final_json(text: str) -> dict:
    """
    Находит и декодирует первый валидный JSON-объект из строки,
    содержащий ключ 'pile_specs'.
    """
    for m in re.finditer(r'\{', text):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
            if isinstance(obj, dict) and "pile_specs" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return {}


class LLMProcessor:
    """
    Класс, инкапсулирующий логику взаимодействия с LLM.
    """

    def __init__(self, settings: Settings, prompt: str):
        self.settings = settings
        self.prompt = prompt
        self.headers = {"Content-Type": "application/json"}
        if self.settings.ollama_token:
            self.headers["Authorization"] = f"Bearer {self.settings.ollama_token}"

    async def process_batch(self, session: aiohttp.ClientSession, batch_text: str, batch_num: int) -> Optional[PileSpecs]:
        """
        Асинхронно отправляет один батч на обработку и валидирует результат.
        """
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": "system", "content": self.prompt.replace("{Document}", batch_text)}],
            "stream": False,
            "options": {"temperature": 0.0}
        }

        for attempt in range(self.settings.max_retries):
            try:
                async with session.post(self.settings.ollama_url, json=payload, headers=self.headers, timeout=aiohttp.ClientTimeout(total=self.settings.timeout)) as response:
                    response.raise_for_status()
                    response_json = await response.json()

                    if "message" not in response_json or "content" not in response_json["message"]:
                        logging.error(f"Батч {batch_num}: Некорректный ответ от LLM: {response_json.get('error')}")
                        continue

                    raw_content = response_json["message"]["content"]
                    logging.debug(f"Батч {batch_num}: Получен сырой ответ:\n{raw_content}")

                    extracted_data = extract_final_json(raw_content)
                    if not extracted_data:
                        logging.warning(f"Батч {batch_num}: Не удалось извлечь JSON из ответа.")
                        return None

                    try:
                        validated_response = LLMResponse(**extracted_data)
                        if validated_response.pile_specs and any(v is not None for v in validated_response.pile_specs.model_dump().values()):
                            logging.info(f"Батч {batch_num}: Данные успешно валидированы.")
                            return validated_response.pile_specs
                        else:
                            logging.warning(f"Батч {batch_num}: Извлеченные данные пусты.")
                            return None
                    except ValidationError as e:
                        logging.error(f"Батч {batch_num}: Ошибка валидации Pydantic: {e}\nИзвлеченные данные: {extracted_data}")
                        return None

            except aiohttp.ClientError as e:
                logging.warning(f"Батч {batch_num} Попытка {attempt + 1}: Ошибка сети/сервера: {e}")
            except asyncio.TimeoutError:
                logging.warning(f"Батч {batch_num} Попытка {attempt + 1}: Таймаут запроса.")
            except Exception as e:
                logging.error(f"Батч {batch_num} Попытка {attempt + 1}: Произошла непредвиденная ошибка: {e}")

            if attempt < self.settings.max_retries - 1:
                await asyncio.sleep(self.settings.retry_delay)

        logging.error(f"Батч {batch_num}: Превышено количество попыток.")
        return None


def merge_pile_specs(batch_results: List[Optional[PileSpecs]]) -> dict:
    """
    Объединяет результаты из всех батчей в один итоговый JSON-объект.
    """
    final_specs: dict[str, Any] = {
        "diameter_mm": None,
        "count": None,
        "concrete_grade": None,
        "rebar_type": None,
    }

    # Списки для агрегации
    concrete_volumes = []
    rebar_weights = []
    grouting_volumes = []

    for result in batch_results:
        if not isinstance(result, PileSpecs):
            continue

        # Уникальные значения (берем первое найденное)
        for key in ["diameter_mm", "count", "concrete_grade", "rebar_type"]:
            if getattr(result, key) is not None and final_specs[key] is None:
                final_specs[key] = getattr(result, key)

        # Списки (собираем все значения)
        if result.concrete_volume_m3:
            concrete_volumes.extend(result.concrete_volume_m3)
        if result.rebar_total_weight_t:
            rebar_weights.extend(result.rebar_total_weight_t)
        if result.grouting_volume_m3:
            grouting_volumes.extend(result.grouting_volume_m3)

    # Заполняем агрегированные списки (или null, если пусты)
    final_specs["concrete_volume_m3"] = concrete_volumes if concrete_volumes else None
    final_specs["rebar_total_weight_t"] = rebar_weights if rebar_weights else None
    final_specs["grouting_volume_m3"] = grouting_volumes if grouting_volumes else None

    return {"pile_specs": final_specs}


async def main():
    """
    Главная асинхронная функция, управляющая процессом обработки.
    """
    settings = Settings() # type: ignore

    if not settings.input_file.exists():
        logging.error(f"Файл не найден: {settings.input_file}")
        print(json.dumps({"pile_specs": {}}, indent=2, ensure_ascii=False))
        return

    document = settings.input_file.read_text(encoding="utf-8")
    records = parse_lot_records(document)
    if not records:
        logging.warning("Записи не найдены в документе.")
        print(json.dumps({"pile_specs": {}}, indent=2, ensure_ascii=False))
        return

    processor = LLMProcessor(settings, PILE_PROMPT)
    async with aiohttp.ClientSession() as session:
        tasks = []
        num_batches = math.ceil(len(records) / settings.batch_size)

        for i in range(num_batches):
            start, end = i * settings.batch_size, (i + 1) * settings.batch_size
            current_batch = records[start:end]
            logging.info(f"Подготовка батча {i+1}/{num_batches}")

            batch_text = "\n---\n".join([record['text'] for record in current_batch])
            task = processor.process_batch(session, batch_text, i+1)
            tasks.append(task)

        logging.info(f"Отправка {len(tasks)} батчей на асинхронную обработку...")
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Фильтруем результаты, чтобы исключить исключения перед слиянием
        valid_results = [r for r in batch_results if isinstance(r, PileSpecs)]

    final_result = merge_pile_specs(valid_results)

    print("\n--- ИТОГОВЫЙ РЕЗУЛЬТАТ ---")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())