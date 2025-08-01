"""
Скрипт для автоматической классификации и извлечения параметров из тендерных лотов.

Этот пайплайн выполняет следующие шаги:
1.  **Парсинг**: Читает исходный файл и разделяет его на отдельные лоты. Каждый лот
    разбивается на отдельные записи (позиции).
2.  **Классификация**: Для каждого лота определяется основная категория работ
    (например, "нулевой цикл") с помощью двухэтапного процесса:
    a. Быстрая классификация по заголовку и первым записям.
    b. Детальная классификация по каждой записи, если результат первого шага
       неоднозначен.
3.  **Извлечение**: На основе определенной категории выбирается соответствующий
    промпт. С его помощью из текста лота извлекаются структурированные
    параметры (например, объемы, материалы, единицы измерения).
4.  **Сохранение**: Результаты для каждого обработанного лота сохраняются в
    отдельный, версионированный JSON-файл.
"""

import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# Импорт промптов из локального модуля
from prompts import (
    CLASSIFIER_PROMPT,
    GROUNDWORKS_CATEGORY_PROMPT,
    SINGLE_RECORD_CLASSIFIER_PROMPT,
)


# --- 1. КОНФИГУРАЦИЯ ---
@dataclass
class Config:
    """
    Централизованный класс для хранения всех настроек скрипта.

    Собирает все "магические" значения и параметры, загружаемые из переменных
    окружения, в одном месте для удобства управления.

    Attributes:
        OLLAMA_URL (str): URL-адрес сервера Ollama (обязательный).
        TOKEN (str): Токен авторизации для Ollama (необязательный).
        MODEL_NAME (str): Название модели Ollama.
        BATCH_SIZE (int): Количество записей для обработки за один запрос к LLM.
        TIMEOUT (int): Таймаут ожидания ответа от сервера в секундах.
        INPUT_FILE (Path): Путь к исходному файлу с лотами.
        OUTPUT_DIR (Path): Каталог для сохранения итоговых JSON-файлов.
        VERIFY_SSL (bool): Флаг для проверки SSL-сертификата сервера.
    """

    # <--- Укажите адрес вашего сервера Ollama в .env
    OLLAMA_URL: str = os.getenv("OLLAMA_URL")
    # <--- Если требуется токен, укажите его в .env
    TOKEN: str = os.getenv("OLLAMA_TOKEN", "")
    MODEL_NAME: str = os.getenv("OLLAMA_MODEL", "llama3")
    BATCH_SIZE: int = 10
    TIMEOUT: int = 300
    INPUT_FILE: Path = Path("test_10_positions.md")
    OUTPUT_DIR: Path = Path("tender_categories")
    VERIFY_SSL: bool = False


# --- 2. КЛАССЫ ДАННЫХ ---


@dataclass
class ExtractedParameter:
    """Структура для хранения одного извлеченного параметра."""

    category: str
    parameter: str
    value: Any
    unit: Optional[str]


@dataclass
class Record:
    """Представление одной записи (позиции) внутри лота."""

    record_id: int
    text: str
    title: str


@dataclass
class LotData:
    """
    Основной класс, агрегирующий всю информацию по одному лоту.

    Хранит как исходные данные, так и результаты их обработки:
    определенную категорию, извлеченные параметры и возможные ошибки.
    """

    lot_number: int
    lot_title: str
    raw_text: str
    records: List[Record] = field(default_factory=list)
    detected_category: Optional[str] = None
    extracted_params: List[ExtractedParameter] = field(default_factory=list)
    error: Optional[str] = None


# --- 3. МАРШРУТИЗАТОР ПРОМПТОВ ---
EXTRACTION_PROMPTS = {
    "нулевой цикл": GROUNDWORKS_CATEGORY_PROMPT,
    # "отделка": FINISHING_WORKS_PROMPT, # <-- Пример, как добавлять новые категории
}

# --- 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ЛОГИКА ---

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def parse_source_file(file_path: Path) -> List[LotData]:
    """
    Парсит исходный файл и разделяет его на объекты LotData.

    Args:
        file_path (Path): Путь к файлу с данными.

    Returns:
        List[LotData]: Список объектов с данными по каждому лоту.
                       Возвращает пустой список, если файл не найден
                       или в нем нет лотов.
    """
    if not file_path.exists():
        logging.error(f"Файл не найден: {file_path}")
        return []
    text = file_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"# Детализированный отчет по позициям для лота\s*-\s*Лот №(?P<lot_number>\d+)\s*-\s*(?P<lot_title>.+)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        logging.error(f"Не удалось найти лоты в файле {file_path}. Проверьте формат данных.")
        return []

    lots = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        lot = LotData(
            lot_number=int(match.group("lot_number")),
            lot_title=match.group("lot_title").strip(),
            raw_text=text[start:end].strip(),
        )
        lot.records = parse_lot_records(lot.raw_text)
        lots.append(lot)
    logging.info(f"Найдено и распарсено {len(lots)} лотов из файла.")
    return lots


def parse_lot_records(raw_text: str) -> List[Record]:
    """
    Разделяет сырой текст лота на отдельные записи (объекты Record).

    Args:
        raw_text (str): Текст одного лота.

    Returns:
        List[Record]: Список записей, найденных в тексте.
    """
    blocks = re.split(r"(?=\n\*\*Наименование:)", raw_text.strip(), flags=re.IGNORECASE)
    records = []
    for i, block in enumerate(filter(None, blocks)):
        title_match = re.search(r"\*\*Наименование:?\*\*\s*(.*)", block.strip())
        records.append(
            Record(
                record_id=i,
                text=block.strip(),
                title=(title_match.group(1).strip() if title_match else "Неизвестная позиция"),
            )
        )
    return records


def run_llm_request(prompt: str, user_content: str, config: Config) -> Optional[Dict[str, Any]]:
    """
    Выполняет синхронный запрос к LLM и возвращает ответ в виде словаря.

    Функция отправляет POST-запрос, обрабатывает возможные ошибки сети и
    таймауты, а также пытается извлечь из ответа модели первый валидный
    JSON-объект.

    Args:
        prompt (str): Системный промпт для LLM.
        user_content (str): Пользовательский контент (текст для анализа).
        config (Config): Объект конфигурации.

    Returns:
        Optional[Dict[str, Any]]: Словарь с данными из JSON-ответа или None
                                  в случае ошибки.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if config.TOKEN:
            headers["Authorization"] = f"Bearer {config.TOKEN}"
        response = requests.post(
            config.OLLAMA_URL,
            json={
                "model": config.MODEL_NAME,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            headers=headers,
            timeout=config.TIMEOUT,
            verify=config.VERIFY_SSL,
        )
        response.raise_for_status()
        j = response.json()
        if "message" not in j or "content" not in j["message"]:
            logging.error(f"Некорректный ответ от LLM: {j.get('error', 'Отсутствует поле message.content')}")
            return None

        response_text = j["message"]["content"]
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))

        logging.warning(f"В ответе LLM не найден JSON-объект. Ответ: {response_text[:200]}...")
        return None

    except requests.Timeout:
        logging.error("Запрос к LLM превысил таймаут.")
    except requests.RequestException as e:
        logging.error(f"Ошибка сети при запросе к LLM: {e}")
    except json.JSONDecodeError:
        logging.error("Не удалось декодировать JSON из ответа LLM.")
    except Exception as e:
        logging.error(f"Непредвиденная ошибка при работе с LLM: {e}")
    return None


def process_lot(lot: LotData, config: Config):
    """
    Выполняет полный цикл обработки одного лота.

    Процесс включает в себя классификацию, выбор промпта и извлечение
    параметров по батчам.

    Args:
        lot (LotData): Объект лота для обработки.
        config (Config): Объект конфигурации.
    """
    logging.info(f"--- Обработка Лота №{lot.lot_number}: '{lot.lot_title}' ---")
    if not lot.records:
        logging.warning(f"Лот №{lot.lot_number}: нет записей для анализа.")
        return

    # --- ШАГ 1: Быстрая классификация по срезу записей ---
    logging.info("Шаг 1: Быстрая классификация...")
    sample_records = lot.records[: min(10, len(lot.records))]
    classifier_input = f"lot_title: {lot.lot_title}\nraw_text: {' '.join(rec.title for rec in sample_records)}"
    category_response = run_llm_request(CLASSIFIER_PROMPT, classifier_input, config)
    detected_category = category_response.get("category") if category_response else None

    # --- ШАГ 2: Детальный анализ при неопределенной категории ---
    if not detected_category or detected_category in ["прочее", "генподряд"]:
        logging.warning(
            f"Результат быстрой проверки неоднозначен ('{detected_category}'). Запускаю детальный анализ..."
        )
        all_categories = []
        for record in lot.records:
            # Пропускаем очевидно нерелевантные записи
            if "оформление" in record.title.lower() or "гаранти" in record.title.lower():
                continue
            cat_resp = run_llm_request(SINGLE_RECORD_CLASSIFIER_PROMPT, record.title, config)
            if cat_resp and "category" in cat_resp:
                all_categories.append(cat_resp["category"])
        if all_categories:
            # Выбираем самую частую категорию
            detected_category = Counter(all_categories).most_common(1)[0][0]

    lot.detected_category = detected_category
    if not lot.detected_category:
        lot.error = "Не удалось определить категорию лота даже после детального анализа."
        logging.error(f"Лот №{lot.lot_number}: {lot.error}")
        return
    logging.info(f"Лоту №{lot.lot_number} присвоена итоговая категория: '{lot.detected_category}'")

    # --- ШАГ 3: Извлечение параметров по батчам ---
    extraction_prompt = EXTRACTION_PROMPTS.get(lot.detected_category)
    if not extraction_prompt:
        logging.warning(f"Для категории '{lot.detected_category}' не найден промпт. Извлечение параметров пропущено.")
        return

    logging.info(f"Шаг 3: Запускаю извлечение параметров для '{lot.detected_category}'.")
    num_batches = math.ceil(len(lot.records) / config.BATCH_SIZE)
    for i in range(num_batches):
        batch_start = i * config.BATCH_SIZE
        batch_end = batch_start + config.BATCH_SIZE
        current_batch = lot.records[batch_start:batch_end]
        logging.info(f"  - Отправка пакета {i+1}/{num_batches}...")

        batch_prompt_lines = [f"[RECORD_ID={record.record_id}]\n{record.text}" for record in current_batch]
        batch_to_process = "\n---END_OF_RECORD---\n".join(batch_prompt_lines)

        parsed_data = run_llm_request(extraction_prompt, batch_to_process, config)
        if not parsed_data:
            logging.warning(f"  - Пакет {i+1} не вернул данных.")
            continue

        extracted_count = 0
        for params_list in parsed_data.values():
            for params_dict in params_list:
                lot.extracted_params.append(ExtractedParameter(**params_dict))
                extracted_count += 1
        logging.info(f"  - [ОК] Пакет {i+1} обработан. Извлечено {extracted_count} параметров.")


def save_results(lot: LotData, config: Config):
    """
    Сохраняет извлеченные параметры лота в версионированный JSON-файл.

    Args:
        lot (LotData): Обработанный объект лота.
        config (Config): Объект конфигурации.
    """
    if not lot.extracted_params:
        logging.info(f"Для лота №{lot.lot_number} нет данных для сохранения.")
        return

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Формирование имени файла: <исходный_файл>.<номер_лота>.<категория>_<время>.json
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    src_name = config.INPUT_FILE.stem
    category_slug = lot.detected_category.replace(" ", "_")
    filename = f"{src_name}.lot_{lot.lot_number}.{category_slug}_{ts}.json"

    filepath = config.OUTPUT_DIR / filename
    output_data = [param.__dict__ for param in lot.extracted_params]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logging.info(f"✅ Результаты для лота №{lot.lot_number} сохранены в: {filepath}")


def main():
    """Главная исполняющая функция скрипта."""
    config = Config()
    if not config.OLLAMA_URL or not config.MODEL_NAME:
        logging.error("Переменные окружения OLLAMA_URL и OLLAMA_MODEL должны быть установлены. Завершение работы.")
        return

    all_lots = parse_source_file(config.INPUT_FILE)
    if not all_lots:
        logging.info("Нет лотов для обработки. Завершение работы.")
        return

    for lot in all_lots:
        process_lot(lot, config)
        save_results(lot, config)

    logging.info("\n🎉 Пайплайн завершен!")


if __name__ == "__main__":
    main()
