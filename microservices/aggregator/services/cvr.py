"""Client wrapper for interacting with the CVR service."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://cvr:8000"

ASSET_FIELDS = {
    "tangible_assets",
    "fixtures",
    "inventories",
    "vehicles",
    "land_buildings",
}


class CvrService:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("CVR_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    def fetch_company(self, cvr: str) -> Optional[Dict[str, Any]]:
        if not cvr:
            return None
        endpoint = f"{self.base_url}/company/{cvr}"
        logger.info("Fetching company assets", extra={"cvr": cvr})
        try:
            response = self._client.get(endpoint)
            if response.status_code == 404:
                logger.info("Company not found", extra={"cvr": cvr})
                return None
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning("Access forbidden when fetching company", extra={"cvr": cvr})
                return None
            raise
        except httpx.HTTPError:
            logger.exception("Failed to fetch company from CVR service")
            raise

    def extract_assets(self, payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
        data: Dict[str, Any] = payload
        if "assets" in payload and isinstance(payload["assets"], dict):
            data = payload["assets"]
        return {field: data.get(field) for field in ASSET_FIELDS}

    def close(self) -> None:
        self._client.close()


__all__ = ["CvrService", "ASSET_FIELDS"]
