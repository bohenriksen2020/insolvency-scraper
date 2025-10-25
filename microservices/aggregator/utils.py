"""Utility helpers for the aggregator service."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y")


def parse_date(value: str | date | None) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")
