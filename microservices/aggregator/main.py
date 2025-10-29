from fastapi import FastAPI, BackgroundTasks, HTTPException
from datetime import date
import requests
import logging
import random
import time
import os
from sqlalchemy.orm import Session

# Upsert company
from sqlalchemy.inspection import inspect


from db import SessionLocal, init_db
from models import Company, Lawyer, InsolvencyCase
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Aggregator Service")

STATSTIDENDE_URL = os.getenv("STATSTIDENDE_URL", "http://statstidende:8001")
CVR_URL = os.getenv("CVR_URL", "http://cvr:8000")
ADVOKAT_URL = os.getenv("ADVOKAT_URL", "http://advokatnoeglen:8003")

init_db()
start_scheduler()


def safe_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Jittered sleep to avoid overloading APIs."""
    time.sleep(random.uniform(min_s, max_s))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}

from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect

def upsert_company(session, case, cvr_data):
    """Insert or update company safely, avoiding null CVR/name and stale sessions."""
    try:
       
       
        cvr = cvr_data.get('cvr')
        name = cvr_data.get('name')
        # only keep existing columns to prevent TypeError
        model_columns = {c.name for c in inspect(Company).columns}
        valid_data = {k: v for k, v in cvr_data.items() if k in model_columns}

        existing = session.query(Company).filter(Company.cvr == cvr).first()
        if existing:
            for k, v in valid_data.items():
                setattr(existing, k, v)
            session.merge(existing)
            logging.info(f"🔁 Updated existing company {name} ({cvr})")
        else:
            session.add(Company(**valid_data))
            logging.info(f"➕ Created new company {name} ({cvr})")

        session.commit()

    except IntegrityError as ie:
        session.rollback()
        logging.error(f"❌ IntegrityError for company {case.get('company_name')} ({cvr}): {ie}")
    except Exception as exc:
        session.rollback()
        logging.warning(f"⚠️ Unexpected error saving company {case.get('company_name')} ({cvr}): {exc}")


def run_daily_sync(date_iso: str | None = None) -> None:
    session: Session = SessionLocal()
    date_iso = date_iso or date.today().isoformat()
    logging.info(f"🔄 Running sync for {date_iso}")

    try:
        response = requests.get(f"{STATSTIDENDE_URL}/insolvencies/{date_iso}", timeout=30)
        response.raise_for_status()
        insolvencies = response.json().get("results", [])
    except Exception as exc:
        logging.error(f"❌ Failed fetching Statstidende data: {exc}")
        session.close()
        return

    logging.info(f"Found {len(insolvencies)} insolvencies")

    for index, case in enumerate(insolvencies, start=1):
        
        lawyer_name = case.get("lawyer_name")
        company_name = case.get("company_name")

        logging.info(f"→ [{index}/{len(insolvencies)}] {company_name} with case: {case}")

        # --- Always fetch CVR enrichment if CVR available ---
        assets = []
        cvr_number = None
        company_fields = None
        company_label = company_name
        if company_name:
            try:
                cvr_response = requests.get(f"{CVR_URL}/assets/{company_name}", timeout=30)
                cvr_response.raise_for_status()
                cvr_data = cvr_response.json()
                cvr_number = cvr_data.get('cvr', None)
                assets = cvr_data.get('assets', None)
                raw = cvr_data.get("raw", cvr_data)

                logging.info(f"Got cvr data: {cvr_data}")
                stamdata = raw.get("stamdata", {})
                udvidet = raw.get("udvidedeOplysninger", {})
                latest_regnskab = None

                # Try to extract the most recent regnskab period
                regnskaber = raw.get("sammenhaengendeRegnskaber", [])
                if regnskaber:
                    latest_regnskab = regnskaber[0].get("periodeFormateret")

                # Extract clean metadata for company
                company_fields = {
                    "cvr": cvr_number,
                    "name": stamdata.get("navn"),
                    "assets": assets,
                    "status": stamdata.get("status", "UNKNOWN"),
                    "address": stamdata.get("adresse"),
                    "zip_city": stamdata.get("postnummerOgBy"),
                    "municipality": udvidet.get("kommune"),
                    "phone": udvidet.get("telefon"),
                    "email": udvidet.get("email"),
                    "industry_code": udvidet.get("hovedbranche", {}).get("branchekode"),
                    "industry_text": udvidet.get("hovedbranche", {}).get("titel"),
                    "fiscal_year_end": udvidet.get("regnskabsaarSlut"),
                    "fiscal_year_start": udvidet.get("regnskabsaarStart"),
                    "capital": udvidet.get("registreretKapital"),
                    "purpose": udvidet.get("formaal"),
                    "latest_regnskab_period": latest_regnskab,
                    "raw_cvr": raw,  # keep full CVR payload
                }

                company_label = company_fields["name"]
                logging.info(f"🏦 Enriching {company_fields['name']} ({cvr_number}), status: {company_fields['status']}")
                # logging.info(company_fields)
                # Extract employee count safely
                antal_ansatte = raw.get("antalAnsatte", {}).get("maanedsbeskaeftigelse", [])
                if antal_ansatte:
                    employees_latest = antal_ansatte[-1].get("antalAnsatte", "N/A")
                else:
                    kvartal = raw.get("antalAnsatte", {}).get("kvartalsbeskaeftigelse", [])
                    employees_latest = kvartal[-1].get("antalAnsatte", "N/A") if kvartal else "N/A"

                logging.info(
                    f"📊 Industry: {company_fields.get('industry_text')} | "
                    f"Employees: {employees_latest} | "
                    f"Latest regnskab: {latest_regnskab}"
                )
                company_fields["employees_latest"] = employees_latest
                safe_sleep(1.0, 1.8)

            except Exception as exc:
                logging.warning(f"⚠️ CVR enrichment failed for {cvr_number}: {exc}")
                safe_sleep(1.0, 2.0)
        else:
            logging.warning(f"⚠️ No CVR for {company_name}, skipping company creation")

        # --- Always fetch lawyer enrichment ---
        lawyer_id = None
        if lawyer_name:
            try:
                lawyer_response = requests.get(
                    f"{ADVOKAT_URL}/lawyer",
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
                    with session.no_autoflush:
                        session.merge(lawyer)
                    session.flush()
                    lawyer_id = lawyer.id
                    logging.info(f"👩‍⚖️ Upserted lawyer {lawyer_name}")
                safe_sleep(1.2, 2.5)
            except Exception as exc:
                logging.warning(f"⚠️ Lawyer fetch failed for {lawyer_name}: {exc}")
                safe_sleep(1.0, 2.0)

        if company_fields:
            if lawyer_id is not None:
                company_fields["lawyer_id"] = lawyer_id
            with session.no_autoflush():
                upsert_company(session, case, company_fields)
            logging.info(f"Done with {company_label}")

        # --- Upsert InsolvencyCase ---
        insolvency = InsolvencyCase(
            message_number=case.get("messageNumber"),
            publication_date=case.get("publicationDate"),
            company_name=company_name,
            cvr=cvr_number,
            court=case.get("court"),
            lawyer_id=lawyer_id,
            raw=case,
        )
        with session.no_autoflush:
            session.merge(insolvency)
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

@app.get("/lawyers/{lawyer_id}")
def get_lawyer_with_cases(lawyer_id: int) -> dict:
    session = SessionLocal()
    lawyer = session.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
    if not lawyer:
        session.close()
        raise HTTPException(status_code=404, detail="Lawyer not found")

    cases = [
        {
            "id": insolvency.id,
            "company": insolvency.company_name,
            "cvr": insolvency.cvr,
            "court": insolvency.court,
            "publication_date": insolvency.publication_date,
        }
        for insolvency in sorted(
            lawyer.cases,
            key=lambda entry: entry.publication_date or "",
            reverse=True,
        )
    ]

    response = {
        "id": lawyer.id,
        "name": lawyer.name,
        "firm": lawyer.firm,
        "city": lawyer.city,
        "email": lawyer.email,
        "cvr": lawyer.cvr,
        "phone": lawyer.phone,
        "cases": cases,
    }

    session.close()
    return response
