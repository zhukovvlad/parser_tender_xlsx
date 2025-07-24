# strut_system_test.py

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
from pydantic import BaseModel, Field, ValidationError

from prompts import STRUT_SYSTEM_PROMPT

load_dotenv()

class Settings(BaseModel):
    ollama_url: str = Field(os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"), description="URL API Ollama")
    model_name: str = Field(os.getenv("OLLAMA_MODEL", "mistral"), description="Название модели")
    ollama_token: Optional[str] = Field(os.getenv("OLLAMA_TOKEN"), description="Токен авторизации")
    input_file: Path = Field(Path("38_38_positions.md"), description="Входной файл")
    batch_size: int = Field(10, description="Размер батча для обработки")
    timeout: int = Field(300, description="Таймаут запроса")
    max_retries: int = Field(3, description="Макс. кол-во повторных попыток")
    retry_delay: int = Field(5, description="Задержка между попытками (сек)")

class StrutSystemResponse(BaseModel):
    strut_system_weights_t: List[float] = Field(default_factory=list)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_lot_records(raw_text: str) -> list:
    records = []
    blocks = raw_text.strip().split('---')
    for i, block in enumerate(filter(None, blocks[1:])):
        clean_block = block.strip()
        if not clean_block: continue
        title_match = re.search(r'\*\*Наименование:\*\*\s*(.*)', clean_block)
        unit_match = re.search(r'\*\*Единица измерения:\*\*\s*([\w\.]+)', clean_block)
        title = title_match.group(1).strip() if title_match else f"Неизвестная позиция {i+1}"
        unit = unit_match.group(1).strip().replace('.', '') if unit_match else None
        records.append({"record_id": i, "text": clean_block, "title": title, "unit": unit})
    logging.info(f"Найдено и разобрано {len(records)} записей.")
    return records

def filter_records_by_unit(records: list, target_unit: str = "т") -> list:
    filtered_records = [record for record in records if record.get("unit") == target_unit]
    logging.info(f"Из {len(records)} записей после фильтрации по единице измерения '{target_unit}' осталось {len(filtered_records)}.")
    return filtered_records

# Старая функция заменена на новую, более надёжную.
def extract_final_json(response_text: str) -> dict:
    """
    Надёжно извлекает JSON из ответа LLM, который может содержать
    дополнительный текст и разметку markdown.
    """
    # Сначала ищем JSON внутри блока ```json ... ```
    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logging.error(f"Ошибка декодирования JSON из блока markdown: {e}")
            return {}

    # Если блока нет, ищем первый попавшийся валидный JSON
    try:
        # Находим первую открывающую скобку и пытаемся декодировать
        first_brace_index = response_text.find('{')
        if first_brace_index != -1:
            # Используем raw_decode для поиска полного объекта JSON
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(response_text[first_brace_index:])
            return obj
    except (json.JSONDecodeError, IndexError):
        # Если ничего не найдено, возвращаем пустой словарь
        logging.warning("JSON в ответе не найден.")
        return {}
    
    return {}

class LLMProcessor:
    def __init__(self, settings: Settings, prompt: str):
        self.settings = settings
        self.prompt = prompt
        self.headers = {"Content-Type": "application/json"}
        if self.settings.ollama_token:
            self.headers["Authorization"] = f"Bearer {self.settings.ollama_token}"

    async def process_batch(self, session: aiohttp.ClientSession, batch_text: str, batch_num: int) -> List[float]:
        payload = {
            "model": self.settings.model_name,
            "messages": [{"role": "system", "content": self.prompt.replace("{Document}", batch_text)}],
            "stream": False, "options": {"temperature": 0.0}
        }
        for attempt in range(self.settings.max_retries):
            try:
                async with session.post(
                    self.settings.ollama_url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=self.settings.timeout)
                ) as response:
                    response.raise_for_status()
                    response_json = await response.json()
                    if "message" not in response_json or "content" not in response_json["message"]:
                        logging.error(f"Батч {batch_num}: Некорректный ответ от LLM: {response_json.get('error')}")
                        return []
                    
                    # Эта строка теперь будет выводить ответ в консоль
                    llm_full_response_text = response_json["message"]["content"]
                    logging.debug(f"Батч {batch_num}: Полный ответ от LLM:\n{llm_full_response_text}")

                    extracted_data = extract_final_json(llm_full_response_text)
                    validated_response = StrutSystemResponse(**extracted_data)
                    return validated_response.strut_system_weights_t
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logging.warning(f"Батч {batch_num} Попытка {attempt + 1}: Ошибка сети/сервера: {e}")
            except ValidationError as e:
                logging.error(f"Батч {batch_num}: Ошибка валидации данных от LLM: {e}")
                return []
            if attempt < self.settings.max_retries - 1:
                await asyncio.sleep(self.settings.retry_delay)
        logging.error(f"Батч {batch_num}: Превышено количество попыток.")
        return []

async def main():
    settings = Settings()
    if not settings.input_file.exists():
        logging.error(f"Файл не найден: {settings.input_file}")
        return
    document = settings.input_file.read_text(encoding="utf-8")
    all_records = parse_lot_records(document)
    if not all_records:
        logging.warning("Записи не найдены в документе.")
        return
    records_to_process = filter_records_by_unit(all_records, target_unit="т")
    if not records_to_process:
        logging.warning("После фильтрации не осталось записей для обработки.")
        return
    processor = LLMProcessor(settings, STRUT_SYSTEM_PROMPT)
    all_weights = []
    async with aiohttp.ClientSession() as session:
        tasks = []
        num_batches = math.ceil(len(records_to_process) / settings.batch_size)
        for i in range(num_batches):
            batch_start, batch_end = i * settings.batch_size, (i + 1) * settings.batch_size
            current_batch = records_to_process[batch_start:batch_end]
            logging.info(f"Подготовка батча {i+1}/{num_batches}")
            batch_text = "\n".join([f"### ЗАПИСЬ ID {record['record_id']} ###\n{record['text']}" for record in current_batch])
            tasks.append(processor.process_batch(session, batch_text, i + 1))
        logging.info(f"Отправка {len(tasks)} батчей на асинхронную обработку...")
        batch_results = await asyncio.gather(*tasks)
        for i, weights in enumerate(batch_results):
            if weights:
                all_weights.extend(weights)
                logging.info(f"Батч {i+1}: Успешно обработан, найден вес: {weights}")
            else:
                logging.info(f"Батч {i+1}: Вес не найден или произошла ошибка.")
    final_result = {"strut_system_weights_t": all_weights}
    print("\n--- ИТОГОВЫЙ РЕЗУЛЬТАТ ---")
    print(json.dumps(final_result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())