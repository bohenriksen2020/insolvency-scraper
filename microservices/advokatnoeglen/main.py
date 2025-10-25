from __future__ import annotations

import os
from typing import Any, Dict

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()



app = FastAPI(title="Advokatnoeglen Service", version="0.1.0")


async def fetch_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Dict[str, Any]:
    response = await client.get(url, timeout=60, **kwargs)
    response.raise_for_status()
    return response.json()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}




if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8002")), reload=False)
