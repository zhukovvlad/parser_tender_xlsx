import argparse
import json

import requests


def send_json_from_file(filepath, url):
    """
    Читает JSON из файла и отправляет его POST-запросом на указанный URL.

    Args:
        filepath (str): Путь к JSON-файлу.
        url (str): URL сервера, на который отправляется запрос.
    """
    try:
        # Открываем и читаем JSON-файл
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Устанавливаем заголовок, указывающий на тип контента
        headers = {"Content-Type": "application/json"}

        # Отправляем POST-запрос с JSON-данными в теле
        response = requests.post(url, json=data, headers=headers)

        # Проверяем статус ответа
        response.raise_for_status()  # Вызовет исключение для кодов 4xx/5xx

        print(f"✅ Успешно отправлено! Статус-код: {response.status_code}")
        print("Ответ сервера:")
        print(response.json())

    except FileNotFoundError:
        print(f"❌ Ошибка: Файл не найден по пути: {filepath}")
    except json.JSONDecodeError:
        print(f"❌ Ошибка: Не удалось декодировать JSON из файла: {filepath}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка при отправке запроса: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Отправка JSON-файла на сервер POST-запросом."
    )
    parser.add_argument("filepath", help="Путь к JSON-файлу.")
    parser.add_argument(
        "--url",
        default="http://localhost:8080/api/v1/import-tender",
        help="URL сервера для отправки (по умолчанию: http://localhost:8080/api/v1/import-tender).",
    )
    args = parser.parse_args()

    send_json_from_file(args.filepath, args.url)
