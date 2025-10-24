#!/usr/bin/env python3
"""
Statstidende scraper for Konkursboer / Dekret messages.
Downloads message listings and full message JSON documents.
"""

import json
import time
from pathlib import Path
from typing import Dict, List
import requests

BASE = "https://www.statstidende.dk"
UA = "Mozilla/5.0 (compatible; KonkursFetcher/1.0)"

session = requests.Session()
session.headers.update({
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
})


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
    """
    Robust fetch for /api/messagesearch for a single date.
    Tries the UI's parameter combination first, then falls back.
    """

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

    # Try different param combinations
    attempts = [
        (10, 40, True),   # exact UI: ps=10, o=40, with m=
        (10, 40, False),  # remove m=
        (20, 40, False),  # bigger page size
        (10, 0,  False),  # different order param
        (50, 0,  False),  # large page, minimal params
    ]

    last_err = None
    for ps, o, include_m in attempts:
        try:
            out = try_one(ps=ps, o=o, include_m=include_m)
            if out is not None:
                return out
        except requests.HTTPError as e:
            last_err = e
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


def dump_konkurs_dekret(date_iso: str, out_dir: str = "out_konkurs_dekret") -> Path:
    """Fetch Konkursboer/Dekret messages for a date and save them."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    search = messagesearch_day(date_iso)
    hits = [
        r for r in search["results"]
        if r.get("sectionName") == "Konkursboer"
        and r.get("messageTypeName") == "Dekret"
    ]
    print(f"[i] {search['resultCount']} total on {date_iso}, {len(hits)} Konkursboer/Dekret")

    for i, it in enumerate(hits, 1):
        msg_no = it.get("messageNumber")
        if not msg_no:
            continue
        try:
            payload = get_message_full(msg_no)
            raw_path = out_path / f"{msg_no}.raw.json"
            raw_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            msg = payload.get("message") or payload
            snapshot = {
                "$id": "1",
                "sectionName": msg.get("sectionName"),
                "messageTypeName": msg.get("messageTypeName"),
                "messageTypeId": msg.get("messageTypeId"),
                "messageNumber": msg.get("messageNumber"),
                "document": msg["document"],  # string
                "title": msg.get("title"),
                "summaryFields": msg.get("summaryFields", []),
                "state": msg.get("state"),
                "logs": payload.get("logs", []),
                "isMyMessage": msg.get("isMyMessage", False),
                "isTeamsMessage": msg.get("isTeamsMessage", False),
                "isMessageSearchable": msg.get("isMessageSearchable", True),
                "publicationDate": msg.get("publicationDate"),
                "ownerName": msg.get("ownerName", ""),
                "publicationId": msg.get("publicationId"),
                "submitDate": msg.get("submitDate"),
                "hasBeenReprintedAndCorrectingMessagesIsPublished": msg.get(
                    "hasBeenReprintedAndCorrectingMessagesIsPublished", False
                ),
                "concurrencyToken": msg.get("concurrencyToken"),
            }
            (out_path / f"{msg_no}.frontend.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"[✓] {i}/{len(hits)} {msg_no}")
            time.sleep(0.35)
        except Exception as ex:
            print(f"[x] {msg_no}: {ex}")

    return out_path


if __name__ == "__main__":
    # Example: scrape 2025-10-24 (same date as your sample)
    dump_konkurs_dekret("2025-10-23")
