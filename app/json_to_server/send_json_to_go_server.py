"""
json_to_server/send_json_to_go_server.py

Назначение:
Этот модуль предоставляет функцию-клиент для взаимодействия с API Go-сервера.
Его основная задача — инкапсулировать логику отправки данных нового тендера,
обработки ответа и извлечения ключевых идентификаторов, сгенерированных
базой данных.

Основная функция:
- `register_tender_in_go`: Выполняет POST-запрос с JSON-данными тендера,
  обрабатывает различные сценарии ответа (успех, сетевые ошибки, ошибки
  сервера) и возвращает унифицированный результат.
"""

import json
import requests
import os
import logging
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional


def generate_fallback_ids(
    data_to_send: Dict[str, Any], source_filename: str
) -> Tuple[str, Dict[str, int]]:
    """
    Генерирует временные ID для offline режима когда сервер недоступен.

    Args:
        data_to_send (Dict[str, Any]): Данные тендера
        source_filename (str): Имя исходного файла для генерации уникальных ID

    Returns:
        Tuple[str, Dict[str, int]]: Временный ID тендера и словарь временных ID лотов
    """
    # Используем timestamp + hash от имени файла для уникальности
    timestamp = int(time.time())
    filename_hash = abs(hash(source_filename)) % 10000

    # Генерируем временный ID тендера в формате "temp_TIMESTAMP_HASH"
    temp_tender_id = f"temp_{timestamp}_{filename_hash}"

    # Генерируем временные ID для лотов
    temp_lot_ids = {}
    lots_data = data_to_send.get("lots", {})

    for i, lot_key in enumerate(lots_data.keys(), 1):
        # Формат: temp_TIMESTAMP_HASH_lot_N
        temp_lot_ids[lot_key] = f"temp_{timestamp}_{filename_hash}_lot_{i}"

    logging.warning(
        f"Сгенерированы временные ID: tender={temp_tender_id}, lots={temp_lot_ids}"
    )
    return temp_tender_id, temp_lot_ids


def register_tender_in_go(
    data_to_send: Dict[str, Any],
    server_url: str,
    api_key: str = None,
    fallback_mode: bool = False,
) -> Tuple[bool, Optional[str], Optional[Dict[str, int]]]:
    """
    Отправляет JSON-данные тендера на Go-сервер для регистрации в базе данных.

    Функция выполняет POST-запрос и ожидает в ответ JSON, содержащий
    уникальные идентификаторы (primary keys), которые были сгенерированы
    базой данных при создании новых записей для тендера и его лотов.

    Args:
        data_to_send (Dict[str, Any]): Словарь с полными данными тендера,
                                     сформированный из XLSX-файла.
        server_url (str): Полный URL API-эндпоинта Go-сервера,
                          отвечающего за импорт тендеров.
        api_key (str, optional): API-ключ для аутентификации запроса.
                                 Если предоставлен, добавляется в заголовок
                                 Authorization как Bearer токен.
        fallback_mode (bool, optional): Если True, при неудачной отправке
                                       функция генерирует временные ID
                                       для продолжения обработки в offline режиме.
                                       По умолчанию False.

    Returns:
        Tuple[bool, Optional[str], Optional[Dict[str, int]]]:
        Кортеж из трёх элементов:
        -   **В случае успеха:** `(True, db_id, lot_ids_map)`
            - `db_id` (str): Уникальный ID тендера из базы данных.
            - `lot_ids_map` (Dict[str, int]): Словарь, где ключ - это
              ключ лота из исходного JSON (например, "LOT_1"), а значение -
              его уникальный ID из базы данных.
        -   **В случае ошибки без fallback_mode:** `(False, None, None)`
        -   **В случае ошибки с fallback_mode:** `(True, temp_id, temp_lot_ids_map)`
            где temp_id и temp_lot_ids_map - временные ID для offline режима.
            Ошибки логируются в консоль.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        logging.info(f"Отправка JSON для регистрации тендера на сервер: {server_url}")

        response = requests.post(
            server_url, json=data_to_send, headers=headers, timeout=60
        )

        # Генерирует исключение для HTTP-статусов 4xx (ошибки клиента) и 5xx (ошибки сервера).
        response.raise_for_status()

        response_data = response.json()
        db_id = response_data.get("db_id")
        lot_ids = response_data.get("lots_id")

        # Проверяем, что сервер вернул все необходимые данные.
        # lot_ids может быть пустым словарём {}, если лотов нет, и это валидный случай.
        if not db_id or lot_ids is None:
            logging.error(
                "Сервер вернул успешный статус, но не предоставил 'db_id' и/или 'lots_id' в ответе."
            )
            if fallback_mode:
                logging.warning(
                    "Активирован резервный режим из-за некорректного ответа сервера"
                )
                return _handle_fallback_mode(data_to_send)
            return False, None, None

        logging.info(f"Тендер успешно зарегистрирован. Получен ID из БД: {db_id}")
        logging.info(f"Получены ID лотов: {lot_ids}")
        return True, str(db_id), lot_ids

    except requests.exceptions.HTTPError as http_err:
        logging.error(f"ОШИБКА HTTP: {http_err}")
        if http_err.response is not None:
            logging.error(f"Тело ответа сервера: {http_err.response.text}")
        if fallback_mode:
            logging.warning("Активирован резервный режим из-за HTTP ошибки")
            return _handle_fallback_mode(data_to_send)
    except requests.exceptions.RequestException as req_err:
        logging.error(f"ОШИБКА СЕТЕВОГО ЗАПРОСА: {req_err}")
        if fallback_mode:
            logging.warning("Активирован резервный режим из-за сетевой ошибки")
            return _handle_fallback_mode(data_to_send)
    except (json.JSONDecodeError, KeyError) as parse_err:
        logging.error(
            f"ОШИБКА: Не удалось обработать JSON или найти ключ в ответе сервера: {parse_err}"
        )
        if fallback_mode:
            logging.warning("Активирован резервный режим из-за ошибки парсинга ответа")
            return _handle_fallback_mode(data_to_send)

    # Если выполнение дошло досюда, значит, в блоке try произошла ошибка.
    return False, None, None


def _handle_fallback_mode(
    data_to_send: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, int]]:
    """
    Обрабатывает резервный режим: генерирует временные ID и создает файл для последующей синхронизации.

    Args:
        data_to_send (Dict[str, Any]): Данные тендера

    Returns:
        Tuple[bool, str, Dict[str, int]]: True, временный ID тендера, словарь временных ID лотов
    """
    # Генерируем временные ID
    temp_tender_id, temp_lot_ids = generate_fallback_ids(data_to_send, "unknown_source")

    # Создаем директорию для неотправленных файлов
    pending_dir = Path("pending_sync")
    pending_dir.mkdir(exist_ok=True)

    # Сохраняем данные для последующей синхронизации
    pending_file = pending_dir / f"{temp_tender_id}.json"
    sync_data = {
        "timestamp": time.time(),
        "temp_tender_id": temp_tender_id,
        "temp_lot_ids": temp_lot_ids,
        "tender_data": data_to_send,
        "sync_status": "pending",
    }

    try:
        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(sync_data, f, ensure_ascii=False, indent=2)
        logging.info(f"Данные сохранены для последующей синхронизации: {pending_file}")
    except Exception as e:
        logging.error(f"Не удалось сохранить файл для синхронизации: {e}")

    # Преобразуем временные ID лотов в int для совместимости
    temp_lot_ids_int = {k: hash(v) % 1000000 for k, v in temp_lot_ids.items()}

    return True, temp_tender_id, temp_lot_ids_int
