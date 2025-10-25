from __future__ import annotations

from fastapi import FastAPI, Query

from fetch import fetch_profile, search_name

app = FastAPI(title="Advokatnøglen Service")


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health check endpoint."""
    return {"status": "ok"}


@app.get("/lawyer")
def get_lawyer(
    name: str = Query(..., description="Full name of the lawyer to search for"),
) -> dict[str, object]:
    """Search Advokatnøglen by name and return parsed profile data."""
    search = search_name(name)
    results: list[dict[str, object]] = []

    for item in search.get("results", []):
        url = item.get("profile_url")
        if not url:
            continue

        try:
            profile = fetch_profile(url)
            results.append({**item, "profile": profile})
        except Exception as exc:  # pragma: no cover - defensive logging
            results.append({**item, "error": f"{type(exc).__name__}: {exc}"})

    return {
        "query_name": name,
        "count": len(results),
        "results": results,
        "search_url": search.get("search_url"),
    }


if __name__ == "__main__":  # pragma: no cover - convenience for local running
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
