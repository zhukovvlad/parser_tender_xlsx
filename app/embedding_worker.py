# ======================================================================================
# embedding_worker.py
# --------------------------------------------------------------------------------------
# Этот скрипт является воркером (обработчиком), который выполняет следующие задачи:
# 1. Подключается к базе данных PostgreSQL.
# 2. Загружает модель-трансформер для создания эмбеддингов.
# 3. Создает и сохраняет нормализованные эмбеддинги для позиций.
#
# Режимы работы:
# - По умолчанию: обрабатывает только новые позиции (где embedding IS NULL).
#   Запуск: python embedding_worker.py
#
# - С флагом --update-all: принудительно пересоздает эмбеддинги для ВСЕХ позиций.
#   Это полезно при смене модели или для исправления старых данных.
#   Запуск: python embedding_worker.py --update-all
# ======================================================================================

import os
import argparse  # Добавлено для обработки аргументов командной строки
import numpy as np
from dotenv import load_dotenv
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sentence_transformers import SentenceTransformer
from pgvector.psycopg2 import register_vector

# Загружаем переменные окружения из .env файла
load_dotenv()

# --- Конфигурация ---
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "tendersdb")

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

EMBEDDING_MODEL_NAME = "paraphrase-multilingual-mpnet-base-v2"
VECTOR_DIMENSION = 768


# --- Основная логика ---


def get_db_connection() -> Engine:
    """Создает и настраивает движок SQLAlchemy для подключения к PostgreSQL."""
    engine = create_engine(DATABASE_URL)

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn, connection_record):
        register_vector(dbapi_conn)

    return engine


def process_positions(
    engine: Engine, model: SentenceTransformer, update_all: bool = False
) -> int:
    """
    Находит позиции, создает для них эмбеддинги и обновляет в БД.

    :param engine: Движок SQLAlchemy для подключения к БД.
    :param model: Загруженная модель sentence-transformer.
    :param update_all: Если True, обрабатывает все записи. Если False, только новые.
    :return: Количество обработанных позиций.
    """
    if update_all:
        print("--- РЕЖИМ: ОБНОВЛЕНИЕ ВСЕХ ЭМБЕДДИНГОВ ---")
        query = text(
            "SELECT id, standard_job_title, description FROM catalog_positions"
        )
    else:
        print("--- РЕЖИM: ОБРАБОТКА ТОЛЬКО НОВЫХ ПОЗИЦИЙ ---")
        query = text(
            "SELECT id, standard_job_title, description FROM catalog_positions WHERE embedding IS NULL"
        )

    try:
        with engine.begin() as connection:
            result = connection.execute(query)
            positions_to_embed = result.fetchall()

            if not positions_to_embed:
                print("Позиций для обработки не найдено.")
                return 0

            print(f"Найдено {len(positions_to_embed)} позиций для обработки.")

            ids = [row[0] for row in positions_to_embed]
            texts_to_embed = [
                f"{row[1]}. {row[2]}" if row[2] else row[1]
                for row in positions_to_embed
            ]

            print("Создание нормализованных эмбеддингов (может занять время)...")
            # ВАЖНО: normalize_embeddings=True создает векторы единичной длины.
            # Это упрощает и ускоряет последующее вычисление косинусной схожести.
            embeddings: np.ndarray = model.encode(
                texts_to_embed, show_progress_bar=True, normalize_embeddings=True
            )

            print("Обновление записей в базе данных...")

            for i, record_id in enumerate(ids):
                embedding_numpy_array = embeddings[i]
                update_query = text(
                    "UPDATE catalog_positions SET embedding = :embedding, updated_at = now() WHERE id = :id"
                )
                connection.execute(
                    update_query, {"embedding": embedding_numpy_array, "id": record_id}
                )

            print(
                f"Успешно обработано {len(ids)} записей. Транзакция будет автоматически подтверждена."
            )

            return len(ids)
    except Exception as e:
        print(f"Ошибка во время транзакции, изменения будут отменены. Ошибка: {e}")
        return -1


if __name__ == "__main__":
    # Настройка парсера аргументов командной строки
    parser = argparse.ArgumentParser(
        description="Воркер для создания эмбеддингов для позиций в каталоге."
    )
    parser.add_argument(
        "--update-all",
        action="store_true",  # Этот флаг не требует значения, достаточно его наличия
        help="Принудительно пересчитать эмбеддинги для всех записей в таблице.",
    )
    args = parser.parse_args()

    print("--- Запуск воркера для создания эмбеддингов ---")

    try:
        print(f"Загрузка модели '{EMBEDDING_MODEL_NAME}'...")
        embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

        model_dim = embedding_model.get_sentence_embedding_dimension()
        if model_dim != VECTOR_DIMENSION:
            print(
                f"ПРЕДУПРЕЖДЕНИЕ: Размерность модели ({model_dim}) не совпадает с ожидаемой ({VECTOR_DIMENSION})!"
            )

        print("Инициализация соединения с базой данных...")
        db_engine = get_db_connection()

        with db_engine.connect():
            print("Пробное соединение с БД успешно.")

        # Запуск основной логики с передачей флага
        process_positions(db_engine, embedding_model, update_all=args.update_all)

        print("\n--- Работа воркера успешно завершена. ---")

    except Exception as e:
        print(f"\n--- Произошла фатальная ошибка ---")
        print(e)
        print("-----------------------------------")
