from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException

from fetch import dump_konkurs_dekret
import logging
logging.basicConfig(level=logging.INFO)


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


def parse_lawyer(text_or_obj: str | dict) -> Dict[str, str]:
    """Extract lawyer info from text or structured message."""
    if isinstance(text_or_obj, dict):
        # structured data path
        personkreds = text_or_obj.get("personkreds", {}).get("personkredser", [])
        for role in personkreds:
            rolle = role.get("rolle", {}).get("name", "")
            if "LIKVIDATOR" in rolle.upper() or "KURATOR" in rolle.upper():
                person = role.get("personRoller", [{}])[0]
                return {
                    "lawyer_name": person.get("senesteNavn"),
                    "lawyer_city": person.get("adresse", "").split("\n")[-1] if person.get("adresse") else None,
                }

    # text fallback
    text = text_or_obj if isinstance(text_or_obj, str) else json.dumps(text_or_obj, ensure_ascii=False)
    match = LAWYER_RE.search(text)
    if not match:
        return {}
    return {
        "lawyer_name": (match.group("name") or "").strip(),
        "lawyer_firm": (match.group("firm") or "").strip(),
        "lawyer_city": (match.group("city") or "").strip(),
    }


def extract_basic_fields(message: Dict[str, Any]) -> Dict[str, Any]:
    """Extract normalized payload from Statstidende message with nested JSON 'document' field."""
    # --- decode the embedded document JSON if possible ---
    doc = None
    if isinstance(message.get("document"), str):
        try:
            doc = json.loads(message["document"])
        except json.JSONDecodeError:
            pass
    elif isinstance(message.get("document"), dict):
        doc = message["document"]

    cvr = None
    company_name = message.get("title") or message.get("ownerName")
    court = None
    lawyer_name = None

    if doc and isinstance(doc, dict):
        for group in doc.get("fieldgroups", []):
            name = group.get("name", "")
            for field in group.get("fields", []):
                field_name = (field.get("name") or "").lower()
                value = field.get("value")

                # CVR
                if "cvr" in field_name and not cvr:
                    cvr = re.sub(r"\D", "", value) if value else None

                # Court
                if "skifteret" in name.lower() or "skifteret" in field_name:
                    court = value

                # Lawyer
                if "kurator" in name.lower():
                    if value and "advokat" in value.lower():
                        lawyer_name = value.replace("Advokat", "").strip()
                    elif value and not lawyer_name:
                        lawyer_name = value.strip()

    # --- Fallbacks from summaryFields ---
    for summary in message.get("summaryFields", []):
        label = summary.get("name") or summary.get("label")
        val = summary.get("value")
        if not cvr and label and "cvr" in label.lower() and val:
            cvr = re.sub(r"\D", "", val)
        if not court and label and "ret" in label.lower():
            court = val

    # --- Assemble normalized output ---
    result = {
        "messageNumber": message.get("messageNumber"),
        "publicationDate": message.get("publicationDate"),
        "company_name": company_name,
        "cvr": cvr,
        "court": court,
        "lawyer_name": lawyer_name,
        "raw": message,
    }

    logging.info(
        f"📦 Extracted → company={company_name} | cvr={cvr} | lawyer={lawyer_name} | court={court}"
    )
    return result


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
