from __future__ import annotations

import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()

CVR_SERVICE_URL = os.getenv("CVR_SERVICE_URL", "http://cvr:8000")
STATSTIDENDE_SERVICE_URL = os.getenv("STATSTIDENDE_SERVICE_URL", "http://statstidende:8001")

app = FastAPI(title="Aggregator Service", version="0.1.0")


async def fetch_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Dict[str, Any]:
    response = await client.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/insolvency/{company}")
async def insolvency_overview(company: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        try:
            cvr_data = await fetch_json(client, f"{CVR_SERVICE_URL}/assets", params={"company": company})
        except httpx.HTTPStatusError as exc:  # pragma: no cover - network fallback
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.text) from exc

        stat_data = await fetch_json(
            client,
            f"{STATSTIDENDE_SERVICE_URL}/messages/{{date}}/dekret".format(date=os.getenv("DEFAULT_STATSTIDENDE_DATE", "2024-01-01")),
        )

    return {
        "company": cvr_data.get("name"),
        "cvr": cvr_data.get("cvr"),
        "assets": cvr_data.get("assets", []),
        "statstidende": stat_data.get("results", []),
        "sources": {
            "cvr_service": CVR_SERVICE_URL,
            "statstidende_service": STATSTIDENDE_SERVICE_URL,
        },
    }


@app.get("/statstidende/{date}")
async def statstidende_proxy(date: str) -> Dict[str, Any]:
    async with httpx.AsyncClient() as client:
        data = await fetch_json(client, f"{STATSTIDENDE_SERVICE_URL}/messages/{date}")
    return data


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8002")), reload=False)
