"""
Клиент для отправки AI-результатов по лоту на Go-сервис.

Гибко формирует endpoint из переменных окружения и отправляет payload,
который сервер должен применить к полю lots.lot_key_parameters.

Переменные окружения (в порядке приоритета):
- GO_SERVER_AI_RESULTS_ENDPOINT_TEMPLATE — полный шаблон URL с плейсхолдерами
    {tender_id} и {lot_id}, например:
    http://localhost:8080/api/v1/tenders/{tender_id}/lots/{lot_id}/ai-results
- GO_SERVER_BASE_URL — базовый URL API, например: http://localhost:8080/api/v1
    Тогда будет использован путь /tenders/{tender_id}/lots/{lot_id}/ai-results
- GO_SERVER_API_ENDPOINT — единая точка входа (база), например
    http://localhost:8080/api/v1
    (если передан старый полный путь вида /import-tender — он будет обрезан до базы)

Авторизация: заголовок Authorization: Bearer <GO_SERVER_API_KEY>, если ключ задан.

Формат тела по умолчанию:
{
    "tender_id": "...",
    "lot_id": "...",
    "lot_key_parameters": {
        "ai": {
            "source": "gemini",
            "category": "...",
            "data": { ... },
            "processed_at": "ISO8601"
        }
    }
}

Если сервер ожидает иной формат — можно переопределить полностью endpoint и
адаптировать на стороне Go, игнорируя лишние поля.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

# Local logger for visibility of outbound requests
log = logging.getLogger("ai_results_client")


def _derive_base_from_import_endpoint(import_endpoint: str) -> str:
    """Получить базовый URL из GO_SERVER_API_ENDPOINT.

    Поддерживаются старые значения переменной, когда указывали полный путь
    до импорта: .../import-tender или .../tenders.
    Примеры:
        http://localhost:8080/api/v1/import-tender -> http://localhost:8080/api/v1
        http://localhost:8080/api/tenders          -> http://localhost:8080/api
    """
    url = import_endpoint.rstrip("/")
    for suffix in ("/import-tender", "/tenders"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def build_ai_results_endpoint(tender_id: str | int, lot_id: str | int) -> str:
    tpl = os.getenv("GO_SERVER_AI_RESULTS_ENDPOINT_TEMPLATE")
    if tpl:
        return tpl.format(tender_id=tender_id, lot_id=lot_id)

    base = os.getenv("GO_SERVER_BASE_URL")
    if not base:
        import_ep = os.getenv("GO_SERVER_API_ENDPOINT")  # например: http://host/api/v1
        if import_ep:
            base = _derive_base_from_import_endpoint(import_ep)
        else:
            # разумный дефолт — v1 API
            base = "http://localhost:8080/api/v1"

    base = base.rstrip("/")
    url = f"{base}/tenders/{tender_id}/lots/{lot_id}/ai-results"
    try:
        log.debug("AI results endpoint built: %s", url)
    except Exception:
        pass
    return url


def make_default_payload(
    tender_id: str | int,
    lot_id: str | int,
    category: str,
    ai_data: Dict[str, Any],
    processed_at: str,
) -> Dict[str, Any]:
    return {
        "tender_id": str(tender_id),
        "lot_id": str(lot_id),
        "lot_key_parameters": {
            "ai": {
                "source": "gemini",
                "category": category,
                "data": ai_data or {},
                "processed_at": processed_at,
            }
        },
    }


def send_lot_ai_results(
    tender_id: str | int,
    lot_id: str | int,
    category: str,
    ai_data: Dict[str, Any],
    processed_at: str,
    *,
    timeout: int = 30,
    idempotency_key: str | None = None,
) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]]]:
    """POST AI-результаты на Go.

    Возвращает (ok, status_code, response_json|None).
    """
    url = build_ai_results_endpoint(tender_id, lot_id)
    payload = make_default_payload(tender_id, lot_id, category, ai_data, processed_at)

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("GO_SERVER_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    try:
        log.info(
            "POST AI results -> %s (idempotency=%s, auth=%s)",
            url,
            bool(idempotency_key),
            bool(api_key),
        )
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        status = resp.status_code
        try:
            data = resp.json()
        except Exception:
            data = None
        if status >= 400:
            log.warning("AI results POST failed: status=%s body=%s", status, data)
            return False, status, data
        log.info("AI results POST ok: status=%s", status)
        return True, status, data
    except requests.RequestException as e:
        log.error("AI results POST exception: %s", e)
        return False, None, None


def save_ai_results_offline(
    tender_id: str | int,
    lot_id: str | int,
    category: str,
    ai_data: Dict[str, Any],
    processed_at: str,
    reason: str = "network_error",
) -> Path:
    """Сохраняет payload для последующей синхронизации."""
    payload = make_default_payload(tender_id, lot_id, category, ai_data, processed_at)
    payload["_sync"] = {"reason": reason, "endpoint": build_ai_results_endpoint(tender_id, lot_id)}

    out_dir = Path("pending_sync_json") / "ai_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{tender_id}_{lot_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    try:
        log.warning("Saved AI results offline: %s", file_path)
    except Exception:
        pass
    return file_path
