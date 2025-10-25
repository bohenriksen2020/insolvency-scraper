"""Client wrapper for interacting with the Advokatnøglen service."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://advokatnoeglen:8000"


class AdvokatService:
    def __init__(self, base_url: Optional[str] = None) -> None:
        self.base_url = (base_url or os.getenv("ADVOKAT_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))

    def fetch_lawyer(self, name: str) -> Optional[Dict[str, Any]]:
        if not name:
            return None
        endpoint = f"{self.base_url}/lawyer"
        logger.info("Fetching lawyer details", extra={"name": name})
        try:
            response = self._client.get(endpoint, params={"name": name})
            if response.status_code == 404:
                logger.info("Lawyer not found", extra={"name": name})
                return None
            response.raise_for_status()
            data = response.json()
            return data or None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                logger.warning("Access forbidden when fetching lawyer", extra={"name": name})
                return None
            raise
        except httpx.HTTPError:
            logger.exception("Failed to fetch lawyer from Advokatnøglen")
            raise

    def close(self) -> None:
        self._client.close()


__all__ = ["AdvokatService"]
