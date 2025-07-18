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
from typing import Dict, Any, Tuple, Optional

def register_tender_in_go(
    data_to_send: Dict[str, Any], 
    server_url: str, 
    api_key: str = None
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

    Returns:
        Tuple[bool, Optional[str], Optional[Dict[str, int]]]:
        Кортеж из трёх элементов:
        -   **В случае успеха:** `(True, db_id, lot_ids_map)`
            - `db_id` (str): Уникальный ID тендера из базы данных.
            - `lot_ids_map` (Dict[str, int]): Словарь, где ключ - это
              ключ лота из исходного JSON (например, "LOT_1"), а значение -
              его уникальный ID из базы данных.
        -   **В случае любой ошибки:** `(False, None, None)`. Ошибки
            (сетевые, HTTP-статусы 4xx/5xx, некорректный формат ответа)
            логируются в консоль.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        print(f"Отправка JSON для регистрации тендера на сервер: {server_url}")
        
        response = requests.post(server_url, json=data_to_send, headers=headers, timeout=60)
        
        # Генерирует исключение для HTTP-статусов 4xx (ошибки клиента) и 5xx (ошибки сервера).
        response.raise_for_status()

        response_data = response.json()
        db_id = response_data.get("db_id")
        lot_ids = response_data.get("lots_id")

        # Проверяем, что сервер вернул все необходимые данные.
        # lot_ids может быть пустым словарём {}, если лотов нет, и это валидный случай.
        if not db_id or lot_ids is None:
            print("ОШИБКА: Сервер вернул успешный статус, но не предоставил 'db_id' и/или 'lots_id' в ответе.")
            return False, None, None

        print(f"Тендер успешно зарегистрирован. Получен ID из БД: {db_id}")
        print(f"Получены ID лотов: {lot_ids}")
        return True, str(db_id), lot_ids

    except requests.exceptions.HTTPError as http_err:
        print(f"ОШИБКА HTTP: {http_err}")
        if http_err.response is not None:
            print(f"Тело ответа сервера: {http_err.response.text}")
    except requests.exceptions.RequestException as req_err:
        print(f"ОШИБКА СЕТЕВОГО ЗАПРОСА: {req_err}")
    except (json.JSONDecodeError, KeyError):
        print("ОШИБКА: Не удалось обработать JSON или найти ключ в ответе сервера.")

    # Если выполнение дошло досюда, значит, в блоке try произошла ошибка.
    return False, None, None
