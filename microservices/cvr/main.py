from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from parse_xbrl import parse_xbrl_assets

load_dotenv()

BASE_URL = os.getenv("CVR_BASE_URL", "https://datacvr.virk.dk")
CVR_SEARCH_URL = f"{BASE_URL}/gateway/soeg/fritekst"
COMPANY_URL = f"{BASE_URL}/gateway/virksomhed/hentVirksomhed"

HEADERS = {
    "User-Agent": os.getenv(
        "CVR_USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36",
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BASE_URL + "/",
}

session = requests.Session()
session.headers.update(HEADERS)

app = FastAPI(title="CVR Service", version="0.1.0")


@lru_cache(maxsize=1)
def _ensure_cookies() -> None:
    session.get(BASE_URL, timeout=20)


class SearchResponse(BaseModel):
    cvr: str
    name: str


class AssetItem(BaseModel):
    tag: str
    name: str
    value: float


class AssetsResponse(BaseModel):
    cvr: str
    name: str
    assets: List[AssetItem]
    dokument_gateway_url: Optional[str] = None
    dokument_public_url: Optional[str] = None


@app.on_event("startup")
def on_startup() -> None:
    _ensure_cookies()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def search_company(name: str) -> Tuple[Optional[str], Optional[str]]:
    """Find CVR for a company under konkurs."""
    payload = {"fritekstCommand": {"soegOrd": name, "sideIndex": "0", "size": ["10"]}}
    r = session.post(CVR_SEARCH_URL, json=payload, timeout=30)
    r.raise_for_status()

    for entry in r.json().get("enheder", []):
        if entry.get("status") == "UNDERKONKURS":
            return entry.get("cvr"), entry.get("senesteNavn")

    return None, None


def fetch_company_data(cvr: str) -> dict:
    """Fetch full company data from hentVirksomhed."""
    url = f"{COMPANY_URL}?cvrnummer={cvr}&locale=da"
    r = session.get(url, timeout=30)
    if r.status_code == 403:
        _ensure_cookies()
        r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def find_latest_xbrl(company_data: dict, cvr: str) -> Tuple[Optional[str], Optional[str]]:
    """Find the latest regnskab with an XML (XBRL) dokument."""
    filings = company_data.get("sammenhaengendeRegnskaber", [])
    if not filings:
        return None, None

    latest = sorted(filings, key=lambda r: r.get("regnskabsperiodeTil", ""), reverse=True)[0]
    regnskab = latest.get("regnskaber", [{}])[0]

    for ref in regnskab.get("dokumentreferencer", []):
        if ref.get("indholdstype", "").upper() == "XML":
            dokument_id = ref.get("dokumentId")
            url_gateway = (
                f"{BASE_URL}/gateway/dokument/downloadDokumentForVirksomhed"
                f"?dokumentId={dokument_id}&cvrNummer={cvr}"
            )
            url_public = f"{BASE_URL}/dokument/{dokument_id}"
            return url_gateway, url_public

    return None, None


def download_xbrl(url_gateway: str, url_public: str) -> bytes:
    """Try to download XML via gateway first, fallback to public /dokument URL."""
    for url in (url_gateway, url_public):
        r = session.get(url, allow_redirects=True, timeout=30)
        if r.status_code == 200 and "xml" in r.headers.get("Content-Type", "").lower():
            return r.content
        if r.status_code == 403:
            continue
    raise HTTPException(status_code=502, detail="Unable to download XBRL XML")


@app.get("/search", response_model=SearchResponse)
def api_search(company: str = Query(..., description="Company name to search for")) -> SearchResponse:
    _ensure_cookies()
    cvr, name = search_company(company)
    if not cvr or not name:
        raise HTTPException(status_code=404, detail="No insolvent company found")
    return SearchResponse(cvr=cvr, name=name)


@app.get("/assets", response_model=AssetsResponse)
def api_assets(company: str = Query(..., description="Company name to search for")) -> AssetsResponse:
    _ensure_cookies()
    cvr, name = search_company(company)
    if not cvr or not name:
        raise HTTPException(status_code=404, detail="No insolvent company found")

    data = fetch_company_data(cvr)
    url_gateway, url_public = find_latest_xbrl(data, cvr)
    if not url_gateway or not url_public:
        raise HTTPException(status_code=404, detail="No XBRL document found")

    xml_data = download_xbrl(url_gateway, url_public)
    assets = [
        AssetItem(tag=tag, name=label, value=value)
        for tag, label, value in parse_xbrl_assets(xml_data)
    ]

    return AssetsResponse(
        cvr=cvr,
        name=name,
        assets=assets,
        dokument_gateway_url=url_gateway,
        dokument_public_url=url_public,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
