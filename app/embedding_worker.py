# ======================================================================================
# embedding_worker.py
# --------------------------------------------------------------------------------------
# Этот скрипт является воркером (обработчиком), который выполняет следующие задачи:
# 1. Подключается к базе данных PostgreSQL, где хранятся данные тендеров.
# 2. Находит в справочнике `catalog_positions` стандартизированные позиции работ,
#    у которых еще нет векторных представлений (эмбеддингов), т.е. поле `embedding` IS NULL.
# 3. Загружает предварительно обученную модель-трансформер из библиотеки sentence-transformers.
# 4. Создает текстовые эмбеддинги для найденных позиций.
# 5. Обновляет записи в базе данных, сохраняя сгенерированные эмбеддинги.
#
# Этот процесс обогащает структурированные данные семантическими векторами,
# что позволяет выполнять гибридный поиск (SQL-фильтрация + семантический поиск).
#
# Запуск:
#   - Убедитесь, что все зависимости установлены: pip install -r requirements.txt
#   - Убедитесь, что существует файл .env с учетными данными для БД.
#   - Выполните в терминале: python embedding_worker.py
# ======================================================================================

import os
import time

import numpy as np
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

# Загружаем переменные окружения из .env файла в окружение процесса.
# Это позволяет безопасно хранить учетные данные вне кода и удобно
# работать в локальном окружении. Должен быть вызван до первого обращения к os.getenv.
load_dotenv()


# --- Конфигурация ---

# Безопасно получаем учетные данные из переменных окружения.
# Если переменная не найдена, используется значение по умолчанию.
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "tendersdb")

# Формируем строку подключения для SQLAlchemy.
# psycopg2 - это драйвер, который будет использоваться для работы с PostgreSQL.
DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Название модели-трансформера для создания эмбеддингов.
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
# Размерность вектора для этой модели. Важно, чтобы она совпадала с той, что указана в схеме БД (vector(768)).
VECTOR_DIMENSION = 768


# --- Основная логика ---


def get_db_connection() -> Engine:
    """
    Создает и настраивает движок SQLAlchemy для подключения к PostgreSQL.

    Ключевой особенностью является регистрация обработчика для типа `vector` из pgvector.
    Поскольку SQLAlchemy использует пул соединений, обработчик нужно регистрировать
    для каждого нового соединения, которое создается в этом пуле. Для этого используется
    механизм событий SQLAlchemy (@event.listens_for).

    :return: Сконфигурированный движок SQLAlchemy.
    """
    engine = create_engine(DATABASE_URL)

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn, connection_record):
        # Эта функция вызывается автоматически при создании нового соединения.
        # Имя `_connect` с подчеркиванием используется по конвенции для внутренних
        # или callback-функций, чтобы анализаторы кода не выдавали предупреждений.
        print("Соединение установлено, регистрация адаптера pgvector...")
        # register_vector "учит" драйвер psycopg2 правильно преобразовывать
        # объекты numpy.ndarray и list в формат, понятный типу vector в PostgreSQL.
        register_vector(dbapi_conn)

    return engine


def process_new_positions(engine: Engine, model: SentenceTransformer) -> int:
    """
    Находит в каталоге новые позиции без эмбеддингов, создает их и обновляет в БД.
    Использует `engine.begin()` для автоматического управления транзакцией.

    :param engine: Движок SQLAlchemy для подключения к БД.
    :param model: Загруженная модель sentence-transformer.
    :return: Количество обработанных позиций.
    """
    print("Запуск обработки новых позиций...")

    # Используем `engine.begin()` для автоматического управления транзакцией.
    # Этот блок сам получает соединение, начинает транзакцию,
    # и делает commit() при успехе или rollback() при ошибке.
    try:
        with engine.begin() as connection:
            # 1. Выполняем SELECT
            query = text(
                "SELECT id, standard_job_title, description FROM catalog_positions WHERE embedding IS NULL"
            )
            result = connection.execute(query)
            positions_to_embed = result.fetchall()

            if not positions_to_embed:
                print("Новых позиций для создания эмбеддингов не найдено.")
                return 0

            print(
                f"Найдено {len(positions_to_embed)} новых позиций для создания эмбеддингов."
            )

            ids = [row[0] for row in positions_to_embed]
            texts_to_embed = [
                f"{row[1]}. {row[2]}" if row[2] else row[1]
                for row in positions_to_embed
            ]

            print("Создание эмбеддингов (может занять время)...")
            embeddings: np.ndarray = model.encode(
                texts_to_embed, show_progress_bar=True
            )

            print("Обновление записей в базе данных...")

            # 2. Выполняем UPDATE в цикле в рамках той же транзакции
            for i, record_id in enumerate(ids):
                embedding_numpy_array = embeddings[i]
                update_query = text(
                    "UPDATE catalog_positions SET embedding = :embedding WHERE id = :id"
                )
                connection.execute(
                    update_query, {"embedding": embedding_numpy_array, "id": record_id}
                )

            # 3. connection.commit() здесь НЕ НУЖЕН!
            # Блок `with` сделает это автоматически при выходе из него.
            print(
                f"Успешно обработано {len(ids)} записей. Транзакция будет автоматически подтверждена."
            )

            return len(ids)
    except Exception as e:
        print(f"Ошибка во время транзакции, изменения будут отменены. Ошибка: {e}")
        # `with`-блок автоматически выполнит rollback
        return -1  # Возвращаем -1 или бросаем исключение дальше в знак ошибки


if __name__ == "__main__":
    print("--- Запуск воркера для создания эмбеддингов ---")

    try:
        print(f"Загрузка модели '{EMBEDDING_MODEL_NAME}'...")
        embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        # Проверка, что размерность модели совпадает с ожидаемой.
        model_dim = embedding_model.get_sentence_embedding_dimension()
        if model_dim != VECTOR_DIMENSION:
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: Размерность модели ({model_dim}) не совпадает с ожидаемой ({VECTOR_DIMENSION})!"
            )
            print("Пожалуйста, обновите константу VECTOR_DIMENSION или схему БД.")

        print("Инициализация соединения с базой данных...")
        db_engine = get_db_connection()

        # Пробное соединение, чтобы убедиться, что подключение работает
        # и листенер для pgvector будет активирован.
        with db_engine.connect():
            print(
                "Пробное соединение с БД успешно. Адаптер pgvector активен для последующих запросов."
            )

        # Запуск основной логики обработки
        process_new_positions(db_engine, embedding_model)

        print("\n--- Работа воркера успешно завершена. ---")

    except Exception as e:
        print(f"\n--- Произошла фатальная ошибка ---")
        print(e)
        print("-----------------------------------")
        # В реальном приложении здесь может быть более сложная логика логирования.
