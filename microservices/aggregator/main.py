from fastapi import FastAPI, BackgroundTasks
from datetime import date
import requests
import logging
import random
import time

from .db import SessionLocal, init_db
from .models import Company, Lawyer, InsolvencyCase
from .scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Aggregator Service")

STATSTIDENDE = "http://statstidende:8000"
CVR = "http://cvr:8000"
ADVOKAT = "http://advokatnoeglen:8000"

init_db()
start_scheduler()


def safe_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Jittered sleep to avoid overloading APIs."""
    time.sleep(random.uniform(min_s, max_s))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def run_daily_sync(date_iso: str | None = None) -> None:
    session = SessionLocal()
    date_iso = date_iso or date.today().isoformat()
    logging.info(f"🔄 Running sync for {date_iso}")

    try:
        response = requests.get(f"{STATSTIDENDE}/insolvencies/{date_iso}", timeout=30)
        response.raise_for_status()
        insolvencies = response.json().get("results", [])
    except Exception as exc:  # pragma: no cover - network errors
        logging.error(f"❌ Failed fetching Statstidende data: {exc}")
        session.close()
        return

    for index, case in enumerate(insolvencies, start=1):
        cvr = case.get("cvr")
        lawyer_name = case.get("lawyer_name")
        logging.info(f"→ [{index}/{len(insolvencies)}] {case.get('company_name')}")

        # --- CVR enrichment ---
        assets = []
        if cvr:
            try:
                cvr_response = requests.get(f"{CVR}/assets/{cvr}", timeout=30)
                cvr_response.raise_for_status()
                cvr_data = cvr_response.json()
                assets = cvr_data.get("assets", [])
                company = Company(
                    cvr=cvr,
                    name=case.get("company_name"),
                    status="UNDERKONKURS",
                    assets=assets,
                )
                session.merge(company)
                safe_sleep(0.8, 1.5)
            except Exception as exc:  # pragma: no cover - network errors
                logging.warning(f"⚠️ CVR failed for {cvr}: {exc}")
                safe_sleep(1.0, 2.0)

        # --- Lawyer enrichment ---
        lawyer_id = None
        if lawyer_name:
            try:
                lawyer_response = requests.get(
                    f"{ADVOKAT}/lawyer",
                    params={"name": lawyer_name},
                    timeout=30,
                )
                lawyer_response.raise_for_status()
                lawyer_data = lawyer_response.json()
                results = lawyer_data.get("results", [])
                if results:
                    profile = results[0].get("profile", {})
                    firm = profile.get("firm", {})
                    lawyer = Lawyer(
                        name=profile.get("name"),
                        firm=firm.get("name"),
                        city=firm.get("city"),
                        email=profile.get("email"),
                        cvr=firm.get("cvr"),
                        phone=firm.get("phone"),
                    )
                    session.add(lawyer)
                    session.flush()
                    lawyer_id = lawyer.id
                safe_sleep(1.2, 2.5)
            except Exception as exc:  # pragma: no cover - network errors
                logging.warning(f"⚠️ Lawyer lookup failed for {lawyer_name}: {exc}")
                safe_sleep(1.0, 2.0)

        insolvency = InsolvencyCase(
            message_number=case.get("messageNumber"),
            publication_date=case.get("publicationDate"),
            company_name=case.get("company_name"),
            cvr=cvr,
            court=case.get("court"),
            lawyer_id=lawyer_id,
            raw=case,
        )
        session.add(insolvency)
        session.commit()

        safe_sleep(0.3, 0.8)

    session.close()
    logging.info(f"✅ Completed sync for {len(insolvencies)} insolvencies on {date_iso}")


@app.post("/sync/today")
def sync_today(background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(run_daily_sync)
    return {"message": "Daily sync started"}


@app.post("/sync/{date_iso}")
def sync_date(date_iso: str, background_tasks: BackgroundTasks) -> dict:
    background_tasks.add_task(run_daily_sync, date_iso)
    return {"message": f"Sync started for {date_iso}"}


@app.get("/insolvencies/recent")
def get_recent() -> dict:
    session = SessionLocal()
    rows = (
        session.query(InsolvencyCase)
        .order_by(InsolvencyCase.publication_date.desc())
        .limit(50)
        .all()
    )
    results = [
        {
            "id": row.id,
            "company": row.company_name,
            "cvr": row.cvr,
            "court": row.court,
            "lawyer": row.lawyer.name if row.lawyer else None,
            "date": row.publication_date,
        }
        for row in rows
    ]
    session.close()
    return {"count": len(results), "results": results}
