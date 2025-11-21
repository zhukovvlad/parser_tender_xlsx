# app/go_module/go_client.py

import os
from typing import Any, Dict, List

import httpx

from .logger import get_go_logger


class GoApiClient:
    """
    Асинхронный клиент для взаимодействия с API Go-бэкенда (tenders-go).
    Является единой точкой входа для ВСЕХ Python-воркеров.
    """

    def __init__(self):
        self.base_url = os.getenv("GO_SERVER_API_ENDPOINT")
        if not self.base_url:
            raise ValueError("GO_SERVER_API_ENDPOINT не установлен в .env")

        # Базовая валидация URL
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            raise ValueError(
                f"GO_SERVER_API_ENDPOINT должен начинаться с http:// или https://, получено: {self.base_url}"
            )

        self.api_key = os.getenv("GO_SERVER_API_KEY")
        self.timeout = int(os.getenv("GO_HTTP_TIMEOUT", 60))

        self.logger = get_go_logger()

        # self.client удален из __init__, чтобы избежать привязки к старому Event Loop
        # Используйте _get_client() для создания клиента в текущем контексте.

        self.logger.info(f"GoApiClient инициализирован для {self.base_url}")

    def _get_client(self):
        """Создает новый экземпляр клиента для текущего Event Loop."""
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    def _get_headers(self) -> Dict[str, str]:
        """Возвращает заголовки для аутентификации."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # Используем Bearer-токен, как стандарт
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _handle_response(self, response: httpx.Response) -> Any:
        """
        Централизованный обработчик ответов и ошибок.
        """
        try:
            # Проверка на 4xx и 5xx ошибки
            response.raise_for_status()
            # Возвращаем JSON, если ответ успешен
            return response.json()
        except httpx.HTTPStatusError as e:
            self.logger.exception(f"Ошибка API Go ({e.response.status_code}): {e.response.text}")
            # Пробрасываем ошибку дальше, чтобы Celery мог ее поймать
            raise
        except Exception as e:
            self.logger.exception(f"Критическая ошибка клиента Go API: {e}")
            raise

    # --- МЕТОДЫ ДЛЯ СТАРОГО ВОРКЕРА (GeminiWorker) ---

    async def import_full_tender(self, tender_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        (ЗАМЕНА) Отправляет полный JSON тендера в Go (Процесс 1).

        Ожидает в ответ:
        {
            "tender_db_id": "1",
            "lot_ids_map": {"lot_1": 1, "lot_2": 2}
        }
        """
        self.logger.info(f"Отправка полного тендера в Go (ETP ID: {tender_data.get('tender_id')})...")
        async with self._get_client() as client:
            response = await client.post(
                "/import-tender", json=tender_data, headers=self._get_headers()  # Эндпоинт совместимый со старым API
            )
            return await self._handle_response(response)

    async def update_lot_key_parameters(self, lot_db_id: str, ai_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        (ЗАМЕНА) Обновляет поле lot_key_parameters для лота (Процесс 1).
        Использует POST для совместимости со старым API.
        """
        self.logger.info(f"Обновление key_parameters для лота {lot_db_id}...")
        # Формат payload совместимый со старым API
        async with self._get_client() as client:
            response = await client.post(
                f"/lots/{lot_db_id}/ai-results",  # Эндпоинт совместимый со старым API
                json=ai_data,  # ai_data уже содержит полный payload
                headers=self._get_headers(),
            )
            return await self._handle_response(response)

    # --- МЕТОДЫ ДЛЯ НОВОГО ВОРКЕРА (RagWorker) ---

    async def get_unmatched_positions(self, limit: int = 100) -> List[Dict]:
        """
        (НОВЫЙ) Получает 'NULL' position_items для сопоставления (Процесс 2).

        Ожидает в ответ:
        [
            {
                "position_item_id": 9999,
                "hash": "hash_of_lemma",
                "rich_context_string": "Лот: ... | Раздел: ... | Позиция: ..."
            },
            ...
        ]
        """
        self.logger.debug(f"Запрос {limit} необработанных позиций...")
        async with self._get_client() as client:
            response = await client.get(
                "/positions/unmatched", params={"limit": limit}, headers=self._get_headers()  # (Предполагаемый эндпоинт)
            )
            return await self._handle_response(response)

    async def post_position_match(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        (НОВЫЙ) Отправляет успешное сопоставление в Go (Процесс 2).
        Go-бэкенд должен обновить position_items И matching_cache.

        Payload:
        {
            "position_item_id": 9999,
            "catalog_position_id": 42,
            "hash": "hash_of_lemma"
        }
        """
        self.logger.debug(f"Отправка сопоставления: {match_data.get('position_item_id')}")
        async with self._get_client() as client:
            response = await client.post(
                "/positions/match", json=match_data, headers=self._get_headers()  # (Предполагаемый эндпоинт)
            )
            return await self._handle_response(response)

    async def get_unindexed_catalog_items(self, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """
        (НОВЫЙ) Получает записи каталога для индексации в File Search (Процесс 3).

        Ожидает в ответ:
        [
            {
                "catalog_id": 123,
                "rich_context_string": "Лот: ... | Позиция: ..."
            },
            ...
        ]
        """
        self.logger.debug(f"Запрос {limit} неиндексированных записей каталога (offset={offset})...")
        async with self._get_client() as client:
            response = await client.get(
                "/catalog/unindexed", params={"limit": limit, "offset": offset}, headers=self._get_headers()
            )
            return await self._handle_response(response)

    async def post_catalog_indexed(self, catalog_ids: List[int]) -> Dict[str, Any]:
        """
        (НОВЫЙ) Сообщает Go, что пачка ID была проиндексирована (Процесс 3).
        """
        self.logger.debug(f"Сообщение об индексации {len(catalog_ids)} ID...")
        async with self._get_client() as client:
            response = await client.post(
                "/catalog/indexed",  # (Предполагаемый эндпоинт)
                json={"catalog_ids": catalog_ids},
                headers=self._get_headers(),
            )
            return await self._handle_response(response)

    async def post_suggest_merge(self, main_id: int, duplicate_id: int, score: float) -> Dict[str, Any]:
        """
        (НОВЫЙ) Предлагает слияние двух записей каталога (Процесс 3).
        """
        self.logger.debug(f"Предложение слияния: {duplicate_id} -> {main_id} (score: {score})")
        payload = {"main_position_id": main_id, "duplicate_position_id": duplicate_id, "similarity_score": score}
        async with self._get_client() as client:
            response = await client.post(
                "/merges/suggest", json=payload, headers=self._get_headers()  # (Предполагаемый эндпоинт)
            )
            return await self._handle_response(response)

    async def get_all_active_catalog_items(self, limit: int, offset: int) -> List[Dict]:
        """
        (НОВЫЙ) Получает 'активные' записи каталога для поиска дубликатов (Процесс 3, Часть Б).
        Использует пагинацию (limit/offset).

        Ожидает в ответ:
        [
            {
                "position_item_id": 123, // Это catalog_id
                "job_title_in_proposal": "лемма...",
                "rich_context_string": "Работа: лемма... | Описание: ..."
            },
            ...
        ]
        """
        self.logger.debug(f"Запрос батча активного каталога (limit={limit}, offset={offset})...")
        params = {"limit": limit, "offset": offset}
        async with self._get_client() as client:
            response = await client.get("/catalog/active", params=params, headers=self._get_headers())
            return await self._handle_response(response)

    async def close(self):
        """
        Закрывает асинхронный клиент.
        Вызывать при graceful shutdown воркера.
        """
        self.logger.info("Закрытие GoApiClient...")
        await self.client.aclose()
