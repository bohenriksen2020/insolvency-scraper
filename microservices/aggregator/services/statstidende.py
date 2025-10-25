"""Client wrapper for interacting with the Statstidende service."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://statstidende:8000"


class StatstidendeService:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("STATSTIDENDE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def fetch_insolvencies(self, target_date: Optional[str] = None) -> List[Dict[str, Any]]:
        endpoint = f"{self.base_url}/insolvencies/today"
        params = {}
        if target_date:
            params["date"] = target_date
        logger.info("Fetching insolvencies from Statstidende", extra={"endpoint": endpoint, "params": params})
        try:
            response = self._client.get(endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ("insolvencies", "results", "data"):
                    if key in payload and isinstance(payload[key], list):
                        return payload[key]
            logger.warning("Unexpected response shape from Statstidende", extra={"type": type(payload).__name__})
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning("Statstidende returned error", extra={"status_code": exc.response.status_code})
            if exc.response.status_code in {403, 404}:
                return []
            raise
        except httpx.HTTPError:
            logger.exception("Failed to fetch insolvencies from Statstidende")
            raise

    def close(self) -> None:
        self._client.close()


__all__ = ["StatstidendeService"]
