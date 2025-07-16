import json
from typing import Any, Dict

import requests


def send_json_to_go_server(
    data_to_send: Dict[str, Any], server_url: str, api_key: str = None
) -> bool:
    """
    Отправляет предоставленные данные (словарь Python) в формате JSON
    на указанный URL сервера с помощью HTTP POST запроса.

    Args:
        data_to_send (Dict[str, Any]): Словарь с данными для отправки.
        server_url (str): URL API эндпоинта Go сервера.
        api_key (str, optional): API ключ для аутентификации. Defaults to None.

    Returns:
        bool: True, если данные успешно отправлены (HTTP 2xx), иначе False.
    """
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = (
            f"Bearer {api_key}"  # Пример использования Bearer токена
        )

    try:
        # Используем параметр json в requests.post, он автоматически сериализует словарь в JSON
        # и установит Content-Type: application/json, если он не был переопределен.
        # Для корректной обработки кириллицы requests по умолчанию использует UTF-8.
        print(f"Отправка JSON на сервер: {server_url}")
        response = requests.post(
            server_url, json=data_to_send, headers=headers, timeout=60
        )  # timeout в секундах
        response.raise_for_status()  # Вызовет исключение для HTTP кодов ошибок 4xx/5xx

        print(
            f"Данные успешно отправлены. Статус ответа сервера: {response.status_code}"
        )
        try:
            print(f"Ответ сервера: {response.json()}")
        except json.JSONDecodeError:
            print(f"Ответ сервера (не JSON): {response.text}")
        return True
    except requests.exceptions.HTTPError as http_err:
        print(f"ОШИБКА HTTP при отправке данных: {http_err}")
        if http_err.response is not None:
            print(f"Тело ответа: {http_err.response.text}")
    except requests.exceptions.ConnectionError as conn_err:
        print(f"ОШИБКА СОЕДИНЕНИЯ при отправке данных: {conn_err}")
    except requests.exceptions.Timeout as timeout_err:
        print(f"ОШИБКА ТАЙМАУТА при отправке данных: {timeout_err}")
    except requests.exceptions.RequestException as req_err:
        print(f"ОБЩАЯ ОШИБКА ЗАПРОСА при отправке данных: {req_err}")

    return False
