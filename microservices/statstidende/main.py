from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

from fetch import dump_konkurs_dekret

app = FastAPI(title="Statstidende Service")

LAWYER_RE = re.compile(
    r"Kurator:\s*(Advokat\s+)?(?P<name>[A-ZÆØÅa-zæøå\s\-]+),?\s*(?P<firm>[^,]+)?,?\s*(?P<city>[A-ZÆØÅa-zæøå]+)?",
    re.IGNORECASE,
)
CVR_RE = re.compile(r"CVR-?nr\.?\:?\s*(\d{8})")


SUMMARY_MAP = {
    "Selskab": "company_name",
    "Navn": "company_name",
    "CVR-nr": "cvr",
    "CVR": "cvr",
    "Ret": "court",
    "Konkursbo": "company_name",
}


def parse_lawyer(text: str) -> Dict[str, str]:
    match = LAWYER_RE.search(text or "")
    if not match:
        return {}
    return {
        "lawyer_name": (match.group("name") or "").strip(),
        "lawyer_firm": (match.group("firm") or "").strip(),
        "lawyer_city": (match.group("city") or "").strip(),
    }


def extract_basic_fields(message: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the normalized payload returned by the API."""

    serialized = json.dumps(message, ensure_ascii=False)
    lawyer = parse_lawyer(serialized)
    cvr_match = CVR_RE.search(serialized)
    cvr = cvr_match.group(1) if cvr_match else None

    basic = {
        "messageNumber": message.get("messageNumber"),
        "publicationDate": message.get("publicationDate"),
        "company_name": message.get("title") or message.get("ownerName"),
        "cvr": message.get("cvr") or cvr,
        "court": message.get("court") or message.get("publicationName"),
    }
    basic.update(lawyer)

    # Fallback from summaryFields if available
    for summary in message.get("summaryFields", []):
        label = summary.get("label")
        value = summary.get("value")
        key = SUMMARY_MAP.get(label or "")
        if key and value and not basic.get(key):
            basic[key] = value

    return basic


def load_message(path: Path) -> Dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    message: Dict[str, Any] | None
    if isinstance(data, dict) and "message" in data:
        message = data.get("message")
    elif isinstance(data, dict):
        message = data
    else:
        message = None

    if not isinstance(message, dict):
        return None

    normalized = extract_basic_fields(message)
    if any(value for value in normalized.values() if value is not None):
        return normalized
    return None


def get_insolvencies_for_date(date_iso: str) -> Dict[str, Any]:
    out_path = dump_konkurs_dekret(date_iso)
    results: List[Dict[str, Any]] = []

    seen: set[str] = set()
    for json_file in sorted(out_path.glob("*.json")):
        normalized = load_message(json_file)
        if not normalized:
            continue
        msg_no = normalized.get("messageNumber")
        if msg_no and msg_no in seen:
            continue
        if msg_no:
            seen.add(msg_no)
        results.append(normalized)

    return {"date": date_iso, "count": len(results), "results": results}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/insolvencies/today")
def insolvencies_today() -> Dict[str, Any]:
    today_iso = date.today().isoformat()
    return get_insolvencies_for_date(today_iso)


@app.get("/insolvencies/{date_iso}")
def insolvencies_by_date(date_iso: str) -> Dict[str, Any]:
    try:
        date.fromisoformat(date_iso)
    except ValueError as exc:  # pragma: no cover - validation fallback
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD") from exc
    return get_insolvencies_for_date(date_iso)
