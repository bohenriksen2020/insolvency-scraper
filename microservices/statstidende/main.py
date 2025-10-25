from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from typing import Dict, List

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()

BASE = os.getenv("STATSTIDENDE_BASE_URL", "https://www.statstidende.dk")
UA = os.getenv("STATSTIDENDE_USER_AGENT", "Mozilla/5.0 (compatible; KonkursFetcher/1.0)")

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
})

app = FastAPI(title="Statstidende Service", version="0.1.0")


@lru_cache(maxsize=1)
def _bootstrap_headers() -> None:
    session.get(f"{BASE}/", timeout=15)


@app.on_event("startup")
def on_startup() -> None:
    _bootstrap_headers()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def normalize_document_inplace(message: Dict) -> Dict:
    """Ensure message.document is a JSON string and attach parsed version."""
    doc = message.get("document")
    if isinstance(doc, str):
        parsed = json.loads(doc)
    elif isinstance(doc, dict):
        parsed = doc
    else:
        raise ValueError("document missing or invalid type")

    if "fieldgroups" not in parsed or "defaultfieldgroups" not in parsed:
        raise ValueError("document missing required keys")

    message["_document_obj"] = parsed
    message["document"] = json.dumps(parsed, ensure_ascii=False)
    message["fieldGroups"] = parsed.get("fieldgroups", [])
    message["defaultFieldGroups"] = parsed.get("defaultfieldgroups", [])
    return message


def messagesearch_day(date_iso: str) -> Dict:
    """Robust fetch for /api/messagesearch for a single date."""

    session.headers.update({
        "Referer": f"{BASE}/messages",
        "Accept-Language": "da-DK,da;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    })

    def build_params(page: int, ps: int, o: int, include_m: bool) -> List[tuple]:
        params = [
            ("d", "false"),
            ("fromDate", f"{date_iso}T00:00:00"),
            ("toDate", f"{date_iso}T00:00:00"),
            ("userOnly", "false"),
            ("messagesforuser", ""),
            ("o", str(o)),
            ("page", str(page)),
            ("ps", str(ps)),
        ]
        if include_m:
            for m in [
                "603102f09e3f5ad99538175719970bde",
                "14a1d71df21558e5ade0214f90482cdc",
                "24295ca1259a5876ba7bf8ef496feed6",
                "383f18001b395f39825061a5c0798fad",
                "018d01410efb5472a6989328817df00a",
                "941c2e759f325408a946031217b6d669",
            ]:
                params.append(("m", m))
        return params

    def try_one(ps: int, o: int, include_m: bool) -> Dict | None:
        url = f"{BASE}/api/messagesearch"
        p = build_params(page=0, ps=ps, o=o, include_m=include_m)
        r = session.get(url, params=p, timeout=20)
        if r.status_code == 500:
            return None
        r.raise_for_status()
        data = r.json()
        results = list(data.get("results", []))
        page_count = int(data.get("pageCount", 1))

        # paginate through pages
        for page in range(1, page_count):
            p = build_params(page=page, ps=ps, o=o, include_m=include_m)
            rr = session.get(url, params=p, timeout=20)
            if rr.status_code == 500:
                return None
            rr.raise_for_status()
            dd = rr.json()
            results.extend(dd.get("results", []))
            time.sleep(0.12)

        return {"pageCount": page_count, "resultCount": len(results), "results": results}

    attempts = [
        (10, 40, True),
        (10, 40, False),
        (20, 40, False),
        (10, 0, False),
        (50, 0, False),
    ]

    last_err = None
    for ps, o, include_m in attempts:
        try:
            out = try_one(ps=ps, o=o, include_m=include_m)
            if out is not None:
                return out
        except requests.HTTPError as exc:  # pragma: no cover - network fallback
            last_err = exc
            time.sleep(0.15)

    if last_err:
        raise last_err
    raise RuntimeError("messagesearch failed for all parameter combinations")


def get_message_full(message_number: str) -> Dict:
    """Fetch full message JSON like the frontend does."""
    r = session.get(f"{BASE}/api/message/{message_number}", timeout=20)
    r.raise_for_status()
    payload = r.json()
    msg = payload.get("message") or payload
    normalize_document_inplace(msg)
    return payload


@app.get("/messages/{date_iso}")
def api_messages(date_iso: str) -> Dict:
    try:
        return messagesearch_day(date_iso)
    except requests.HTTPError as exc:  # pragma: no cover - network fallback
        raise HTTPException(status_code=exc.response.status_code, detail=str(exc)) from exc


@app.get("/messages/{date_iso}/dekret")
def api_messages_dekret(date_iso: str) -> Dict:
    search = api_messages(date_iso)
    hits = [
        r
        for r in search.get("results", [])
        if r.get("sectionName") == "Konkursboer" and r.get("messageTypeName") == "Dekret"
    ]
    enriched = []
    for it in hits:
        msg_no = it.get("messageNumber")
        if not msg_no:
            continue
        payload = get_message_full(msg_no)
        msg = payload.get("message") or payload
        snapshot = {
            "$id": "1",
            "sectionName": msg.get("sectionName"),
            "messageTypeName": msg.get("messageTypeName"),
            "messageTypeId": msg.get("messageTypeId"),
            "messageNumber": msg.get("messageNumber"),
            "document": msg.get("document"),
            "title": msg.get("title"),
            "summaryFields": msg.get("summaryFields", []),
            "state": msg.get("state"),
            "logs": payload.get("logs", []),
            "publicationDate": msg.get("publicationDate"),
            "ownerName": msg.get("ownerName", ""),
            "publicationId": msg.get("publicationId"),
        }
        enriched.append(snapshot)
        time.sleep(0.2)
    return {"resultCount": len(enriched), "results": enriched}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8001")), reload=False)
