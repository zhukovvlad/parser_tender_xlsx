# app/go_module/go_client.py

import json
import os
from typing import Any, Dict, List, Optional

import httpx

from .logger import get_go_logger


class GoApiClient:
    """
    Асинхронный клиент для взаимодействия с API Go-бэкенда (tenders-go).
    Является единой точкой входа для ВСЕХ Python-воркеров.

    Архитектура:
    -----------
    Клиент создает новый httpx.AsyncClient для каждого запроса через контекстный менеджер.
    Это решает проблему с Event Loop в многопроцессных Celery воркерах, где каждый процесс
    имеет свой Event Loop.

    Управление соединениями:
    -----------------------
    - Каждый метод использует `async with self._get_client() as client:`
    - Соединения автоматически закрываются после завершения запроса
    - Нет утечек памяти и открытых соединений
    - Не требуется явный вызов .close()

    Таймауты:
    ---------
    - Стандартные операции: 60 секунд (read)
    - Импорт тендера: 600 секунд (большие JSON, обработка в Go)
    - Connect: 10 секунд
    - Write: 30-60 секунд

    Аутентификация:
    --------------
    Использует Bearer токен из переменной окружения GO_SERVER_API_KEY.

    Обработка ошибок:
    ----------------
    - HTTPStatusError: логируется и пробрасывается для retry в Celery
    - JSONDecodeError: если Go вернул невалидный JSON
    - Все исключения логируются с полным контекстом

    Переменные окружения:
    --------------------
    - GO_SERVER_API_ENDPOINT: базовый URL (обязательно)
    - GO_SERVER_API_KEY: токен авторизации (опционально)
    - GO_HTTP_TIMEOUT: таймаут для обычных запросов (по умолчанию 60)
    - GO_IMPORT_TENDER_TIMEOUT: таймаут для импорта (по умолчанию 600)

    Примеры использования:
    ---------------------
    >>> client = GoApiClient()
    >>> # В async функции:
    >>> result = await client.import_full_tender(tender_data)
    >>> positions = await client.get_unmatched_positions(limit=50)
    """

    def __init__(self):
        self.base_url = os.getenv("GO_SERVER_API_ENDPOINT")
        if not self.base_url:
            raise ValueError("GO_SERVER_API_ENDPOINT не установлен в .env")

        # Удаляем слеш в конце, чтобы базовая часть всегда была чистой (без /)
        self.base_url = self.base_url.rstrip("/")

        # Базовая валидация URL
        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            raise ValueError(
                f"GO_SERVER_API_ENDPOINT должен начинаться с http:// или https://, получено: {self.base_url}"
            )

        self.api_key = os.getenv("GO_SERVER_API_KEY")

        self.timeout = httpx.Timeout(connect=10, read=float(os.getenv("GO_HTTP_TIMEOUT", "60")), write=30, pool=10)

        self.import_tender_timeout = httpx.Timeout(
            connect=10, read=float(os.getenv("GO_IMPORT_TENDER_TIMEOUT", "600")), write=60, pool=10
        )

        self.logger = get_go_logger()

        # self.client удален из __init__, чтобы избежать привязки к старому Event Loop
        # Используйте _get_client() для создания клиента в текущем контексте.

        self.logger.info(f"GoApiClient инициализирован для {self.base_url}")

    def _get_client(self, timeout: Optional[httpx.Timeout] = None) -> httpx.AsyncClient:
        """
        Создает новый экземпляр httpx.AsyncClient для текущего Event Loop.

        Каждый вызов создает отдельный клиент, что критично для работы в Celery,
        где воркеры работают в разных процессах с разными Event Loop.

        Args:
            timeout: Кастомный таймаут для запроса. Если None, используется self.timeout.

        Returns:
            httpx.AsyncClient: Настроенный async HTTP клиент

        Note:
            Клиент должен использоваться через `async with` для автоматического закрытия.
        """

        use_timeout = self.timeout if timeout is None else timeout

        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=use_timeout,
        )

    def _get_headers(self) -> Dict[str, str]:
        """
        Формирует HTTP заголовки для запросов к Go API.

        Returns:
            Dict[str, str]: Словарь заголовков:
                - Accept: application/json (всегда)
                - Authorization: Bearer <token> (если GO_SERVER_API_KEY установлен)
        """
        headers = {"Accept": "application/json"}
        if self.api_key:
            # Используем Bearer-токен, как стандарт
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _handle_response(self, response: httpx.Response) -> Any:
        """
        Централизованный обработчик ответов и ошибок от Go API.

        Проверяет статус код, парсит JSON, обрабатывает ошибки.

        Args:
            response: Объект ответа от httpx

        Returns:
            Any: Распарсенный JSON ответ, или None для 204 статуса

        Raises:
            httpx.HTTPStatusError: При 4xx/5xx ошибках (логируется и пробрасывается)
            ValueError: При невалидном JSON в теле ответа
            Exception: Другие критические ошибки
        """
        try:
            # Проверка на 4xx и 5xx ошибки
            response.raise_for_status()

            if response.status_code == 204:
                return None

            return response.json()
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            self.logger.exception(f"Ошибка API Go ({e.response.status_code}): {error_body}")
            # Пробрасываем ошибку дальше, чтобы Celery мог ее поймать
            raise

        except json.JSONDecodeError as err:
            ctype = response.headers.get("content-type")
            url = str(response.request.url)
            self.logger.exception(
                f"Некорректный JSON от API Go. URL: {url}. Status: {response.status_code}. Content-Type: {ctype}. "
                f"Body: {response.text[:200]}"
            )
            raise ValueError(f"Invalid JSON response from Go API: {response.text[:100]}") from err

        except Exception as e:
            self.logger.exception(f"Критическая ошибка клиента Go API: {e}")
            raise

    # --- МЕТОДЫ ДЛЯ СТАРОГО ВОРКЕРА (GeminiWorker) ---

    async def import_full_tender(self, tender_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Импортирует полный тендер в Go бэкенд (Процесс 1: Парсинг и импорт).

        Отправляет полный JSON тендера со всеми лотами, позициями и метаданными.
        Go сервер создает записи в БД и возвращает их идентификаторы.

        Args:
            tender_data: Полный JSON тендера, содержащий:
                - tender_id: ID тендера в ETP
                - lots: список лотов с позициями
                - metadata: дополнительные данные

        Returns:
            Dict[str, Any]: Ответ от Go сервера:
                {
                    "tender_db_id": int,  # ID созданного тендера в БД
                    "lot_ids_map": {      # Маппинг external_id -> db_id для лотов
                        "lot_1": 1,
                        "lot_2": 2
                    },
                    "new_catalog_items_pending": bool  # Есть ли новые позиции для индексации
                }

        Raises:
            httpx.HTTPStatusError: При ошибках на стороне Go API

        Note:
            Использует увеличенный таймаут (600s) для обработки больших тендеров.
        """
        self.logger.info(f"Отправка полного тендера в Go (ETP ID: {tender_data.get('tender_id')})...")
        async with self._get_client(timeout=self.import_tender_timeout) as client:
            response = await client.post("/import-tender", json=tender_data, headers=self._get_headers())
            return self._handle_response(response)

    async def update_lot_key_parameters(self, lot_db_id: str, ai_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновляет AI-результаты (ключевые параметры) для лота (Процесс 1: AI обработка).

        Сохраняет результаты обработки Gemini AI: категорию, смету, таблицы работ и другие параметры.

        Args:
            lot_db_id: Database ID лота (не external_id!)
            ai_data: AI результаты, содержащие:
                - category: категория работ (тип мостостроения, котлован и т.д.)
                - cmu_table: таблица работ с позициями
                - smeta_summary: итоги по смете
                - tender_id: (опционально) для совместимости
                - lot_id: (добавляется автоматически)

        Returns:
            Dict[str, Any]: Подтверждение от Go сервера

        Raises:
            httpx.HTTPStatusError: При ошибках валидации или сохранения
        """
        self.logger.info(f"Обновление key_parameters для лота {lot_db_id}...")
        # Формат payload совместимый со старым API
        async with self._get_client() as client:
            response = await client.post(
                f"/lots/{lot_db_id}/ai-results",  # Эндпоинт совместимый со старым API
                json=ai_data,  # ai_data уже содержит полный payload
                headers=self._get_headers(),
            )
            return self._handle_response(response)

    # --- МЕТОДЫ ДЛЯ НОВОГО ВОРКЕРА (RagWorker) ---

    async def get_unmatched_positions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает несопоставленные позиции для RAG-матчинга (Процесс 2: Сопоставление).

        Возвращает позиции из тендеров, для которых еще не найдена запись в каталоге.
        Используется RAG воркером для поиска совпадений через File Search.

        Args:
            limit: Максимальное количество позиций (по умолчанию 100)

        Returns:
            List[Dict[str, Any]]: Список позиций для обработки:
                [
                    {
                        "position_item_id": int,      # ID позиции в БД
                        "hash": str,                  # Хеш леммы для кеша
                        "rich_context_string": str    # Контекст: "Лот: ... | Раздел: ... | Позиция: ..."
                    },
                    ...
                ]

        Note:
            Позиции с catalog_position_id = NULL.
        """
        self.logger.debug(f"Запрос {limit} необработанных позиций...")
        async with self._get_client() as client:
            response = await client.get(
                "/positions/unmatched",
                params={"limit": limit},
                headers=self._get_headers(),  # (Предполагаемый эндпоинт)
            )
            return self._handle_response(response)

    async def post_position_match(self, match_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Сохраняет результат успешного сопоставления позиции (Процесс 2: Сопоставление).

        Обновляет position_items.catalog_position_id и добавляет запись в matching_cache
        для последующего переиспользования.

        Args:
            match_data: Данные о сопоставлении:
                {
                    "position_item_id": int,      # ID позиции в тендере
                    "catalog_position_id": int,   # ID найденной записи в каталоге
                    "hash": str                   # Хеш леммы для кеша
                }

        Returns:
            Dict[str, Any]: Подтверждение от Go сервера

        Note:
            Go сервер атомарно обновляет position_items и matching_cache.
        """
        self.logger.debug(f"Отправка сопоставления: {match_data.get('position_item_id')}")
        async with self._get_client() as client:
            response = await client.post(
                "/positions/match", json=match_data, headers=self._get_headers()  # (Предполагаемый эндпоинт)
            )
            return self._handle_response(response)

    async def get_unindexed_catalog_items(self, limit: int = 1000, offset: int = 0) -> List[Dict]:
        """
        Получает неиндексированные записи каталога для File Search (Процесс 3: Индексация).

        Возвращает записи из catalog_positions, которые еще не добавлены в RAG.
        Поддерживает пагинацию для обработки больших объемов.

        Args:
            limit: Максимальное количество записей за запрос (по умолчанию 1000)
            offset: Смещение для пагинации (по умолчанию 0)

        Returns:
            List[Dict]: Список записей для индексации:
                [
                    {
                        "catalog_id": int,            # ID записи в каталоге
                        "rich_context_string": str    # Контекст: "Работа: ... | Описание: ..."
                    },
                    ...
                ]

        Note:
            Записи с indexed = false или NULL.
        """
        self.logger.debug(f"Запрос {limit} неиндексированных записей каталога (offset={offset})...")
        async with self._get_client() as client:
            response = await client.get(
                "/catalog/unindexed", params={"limit": limit, "offset": offset}, headers=self._get_headers()
            )
            return self._handle_response(response)

    async def post_catalog_indexed(self, catalog_ids: List[int]) -> Dict[str, Any]:
        """
        Отмечает записи каталога как проиндексированные (Процесс 3: Индексация).

        Обновляет флаг indexed = true для указанных catalog_ids после успешной
        индексации в Google File Search.

        Args:
            catalog_ids: Список ID записей, успешно добавленных в File Search

        Returns:
            Dict[str, Any]: Подтверждение с количеством обновленных записей:
                {"updated_count": int}

        Note:
            Отправляется батчами после успешной индексации чанков в RAG.
        """
        self.logger.debug(f"Сообщение об индексации {len(catalog_ids)} ID...")
        async with self._get_client() as client:
            response = await client.post(
                "/catalog/indexed",  # (Предполагаемый эндпоинт)
                json={"catalog_ids": catalog_ids},
                headers=self._get_headers(),
            )
            return self._handle_response(response)

    async def post_suggest_merge(self, main_id: int, duplicate_id: int, score: float) -> Dict[str, Any]:
        """
        Создает предложение слияния дубликатов в каталоге (Процесс 3: Дедупликация).

        Сохраняет найденный потенциальный дубликат для последующей ручной проверки
        или автоматического слияния.

        Args:
            main_id: ID основной (оставляемой) записи в каталоге
            duplicate_id: ID дубликата (кандидата на слияние)
            score: Оценка схожести от 0.0 до 1.0 (порог обычно 0.95+)

        Returns:
            Dict[str, Any]: Подтверждение создания предложения:
                {"merge_suggestion_id": int}

        Note:
            Go сервер проверяет, что записи существуют и не были объединены ранее.
        """
        self.logger.debug(f"Предложение слияния: {duplicate_id} -> {main_id} (score: {score})")
        payload = {"main_position_id": main_id, "duplicate_position_id": duplicate_id, "similarity_score": score}
        async with self._get_client() as client:
            response = await client.post(
                "/merges/suggest", json=payload, headers=self._get_headers()  # (Предполагаемый эндпоинт)
            )
            return self._handle_response(response)

    async def get_all_active_catalog_items(self, limit: int, offset: int) -> List[Dict]:
        """
        Получает активные записи каталога для поиска дубликатов (Процесс 3Б: Дедупликация).

        Возвращает записи каталога с флагом is_active = true для анализа на дубликаты.
        Поддерживает пагинацию для обработки всего каталога.

        Args:
            limit: Количество записей за запрос (рекомендуется 100-500)
            offset: Смещение для пагинации

        Returns:
            List[Dict]: Список активных записей каталога:
                [
                    {
                        "position_item_id": int,        # ID записи (catalog_id)
                        "job_title_in_proposal": str,   # Нормализованное название работы
                        "rich_context_string": str      # Полный контекст для сравнения
                    },
                    ...
                ]

        Note:
            Используется для попарного сравнения и поиска семантических дубликатов.
        """
        self.logger.debug(f"Запрос батча активного каталога (limit={limit}, offset={offset})...")
        params = {"limit": limit, "offset": offset}
        async with self._get_client() as client:
            response = await client.get("/catalog/active", params=params, headers=self._get_headers())
            return self._handle_response(response)
