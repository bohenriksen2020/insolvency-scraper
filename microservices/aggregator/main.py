from __future__ import annotations

import logging
import os
import random
import time
from datetime import date
from typing import Any, Dict, Optional

import requests
from fastapi import BackgroundTasks, FastAPI, HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from db import SessionLocal, init_db
from models import Company, InsolvencyCase, Lawyer
from scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Aggregator Service")

STATSTIDENDE_URL = os.getenv("STATSTIDENDE_URL", "http://statstidende:8001")
CVR_URL = os.getenv("CVR_URL", "http://cvr:8000")
ADVOKAT_URL = os.getenv("ADVOKAT_URL", "http://advokatnoeglen:8003")

init_db()
start_scheduler()


def safe_sleep(min_s: float = 0.5, max_s: float = 1.5) -> None:
    """Jittered sleep to avoid overloading upstream services."""

    time.sleep(random.uniform(min_s, max_s))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _filter_model_fields(model: type, values: Dict[str, Any]) -> Dict[str, Any]:
    model_columns = {column.name for column in inspect(model).columns}
    return {key: value for key, value in values.items() if key in model_columns}


def _coerce_capital(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def upsert_company(
    session: Session, case: Dict[str, Any], cvr_data: Dict[str, Any]
) -> Optional[Company]:
    cvr = cvr_data.get("cvr")
    if not cvr:
        logging.warning("⚠️ Cannot upsert company without CVR", extra={"case": case})
        return None

    clean_data = _filter_model_fields(Company, cvr_data)
    clean_data.setdefault("name", case.get("company_name"))

    existing = session.get(Company, cvr)
    if existing:
        for key, value in clean_data.items():
            setattr(existing, key, value)
        company = existing
        logging.info("🔁 Updated existing company", extra={"cvr": cvr, "name": existing.name})
    else:
        company = Company(**clean_data)
        session.add(company)
        logging.info("➕ Created new company", extra={"cvr": cvr, "name": company.name})

    session.flush()
    return company


def upsert_lawyer(session: Session, lawyer_data: Dict[str, Any]) -> Optional[Lawyer]:
    name = lawyer_data.get("name")
    if not name:
        return None

    firm = lawyer_data.get("firm")
    existing = (
        session.query(Lawyer)
        .filter(Lawyer.name == name, Lawyer.firm == firm)
        .one_or_none()
    )

    clean_data = _filter_model_fields(Lawyer, lawyer_data)

    if existing:
        for key, value in clean_data.items():
            setattr(existing, key, value)
        lawyer = existing
        logging.info("🔁 Updated lawyer", extra={"name": name, "firm": firm})
    else:
        lawyer = Lawyer(**clean_data)
        session.add(lawyer)
        logging.info("➕ Created lawyer", extra={"name": name, "firm": firm})

    session.flush()
    return lawyer


def upsert_insolvency_case(
    session: Session,
    case: Dict[str, Any],
    company: Optional[Company],
    lawyer: Optional[Lawyer],
) -> InsolvencyCase:
    case_payload = {
        "message_number": case.get("messageNumber"),
        "publication_date": case.get("publicationDate"),
        "company_name": case.get("company_name"),
        "cvr": company.cvr if company else case.get("cvr"),
        "court": case.get("court"),
        "lawyer_id": lawyer.id if lawyer else None,
        "raw": case,
    }

    message_number = case_payload["message_number"]
    insolvency: Optional[InsolvencyCase] = None

    if message_number:
        insolvency = (
            session.query(InsolvencyCase)
            .filter(InsolvencyCase.message_number == message_number)
            .one_or_none()
        )

    if insolvency is None:
        insolvency = InsolvencyCase(**case_payload)
        session.add(insolvency)
        logging.info(
            "➕ Created insolvency case",
            extra={"message_number": message_number, "company": case_payload["company_name"]},
        )
    else:
        for key, value in case_payload.items():
            setattr(insolvency, key, value)
        logging.info(
            "🔁 Updated insolvency case",
            extra={"message_number": message_number, "company": case_payload["company_name"]},
        )

    session.flush()
    return insolvency


def _fetch_cvr_data(company_name: str) -> Optional[Dict[str, Any]]:
    if not company_name:
        return None
    response = requests.get(f"{CVR_URL}/assets/{company_name}", timeout=30)
    if response.status_code == 404:
        logging.info("Company not found in CVR", extra={"company": company_name})
        return None
    response.raise_for_status()
    return response.json()


def _fetch_lawyer_data(lawyer_name: str) -> Optional[Dict[str, Any]]:
    if not lawyer_name:
        return None
    response = requests.get(
        f"{ADVOKAT_URL}/lawyer",
        params={"name": lawyer_name},
        timeout=30,
    )
    if response.status_code == 404:
        logging.info("Lawyer not found", extra={"lawyer": lawyer_name})
        return None
    response.raise_for_status()
    payload = response.json().get("results", [])
    return payload[0] if payload else None


def _build_company_fields(company_name: str, cvr_payload: Dict[str, Any]) -> Dict[str, Any]:
    cvr_number = cvr_payload.get("cvr")
    assets = cvr_payload.get("assets")
    raw = cvr_payload.get("raw", cvr_payload)

    stamdata = raw.get("stamdata", {})
    udvidet = raw.get("udvidedeOplysninger", {})
    regnskaber = raw.get("sammenhaengendeRegnskaber", [])
    latest_regnskab = regnskaber[0].get("periodeFormateret") if regnskaber else None

    antal_ansatte = raw.get("antalAnsatte", {}).get("maanedsbeskaeftigelse", [])
    if antal_ansatte:
        employees_latest = antal_ansatte[-1].get("antalAnsatte", "N/A")
    else:
        kvartal = raw.get("antalAnsatte", {}).get("kvartalsbeskaeftigelse", [])
        employees_latest = kvartal[-1].get("antalAnsatte", "N/A") if kvartal else "N/A"

    return {
        "cvr": cvr_number,
        "name": stamdata.get("navn") or company_name,
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
        "capital": _coerce_capital(udvidet.get("registreretKapital")),
        "purpose": udvidet.get("formaal"),
        "latest_regnskab_period": latest_regnskab,
        "employees_latest": employees_latest,
        "raw_cvr": raw,
    }


def _build_lawyer_fields(profile: Dict[str, Any]) -> Dict[str, Any]:
    firm = profile.get("firm", {})
    return {
        "name": profile.get("name"),
        "firm": firm.get("name"),
        "city": firm.get("city"),
        "email": profile.get("email"),
        "cvr": firm.get("cvr"),
        "phone": firm.get("phone"),
    }


def process_insolvency_case(
    session: Session,
    case: Dict[str, Any],
    index: int,
    total: int,
) -> None:
    company_name = case.get("company_name")
    lawyer_name = case.get("lawyer_name")

    logging.info("→ Processing insolvency", extra={"index": index, "total": total, "company": company_name})

    company_fields: Optional[Dict[str, Any]] = None
    try:
        if company_name:
            cvr_payload = _fetch_cvr_data(company_name)
            if cvr_payload:
                company_fields = _build_company_fields(company_name, cvr_payload)
                logging.info(
                    "🏦 Enriched company",
                    extra={"name": company_fields.get("name"), "cvr": company_fields.get("cvr")},
                )
                safe_sleep(1.0, 1.8)
    except requests.RequestException as exc:
        logging.warning("⚠️ CVR enrichment failed", extra={"company": company_name, "error": str(exc)})
        safe_sleep(1.0, 2.0)

    lawyer: Optional[Lawyer] = None
    try:
        if lawyer_name:
            lawyer_payload = _fetch_lawyer_data(lawyer_name)
            if lawyer_payload:
                profile = lawyer_payload.get("profile", {})
                lawyer_fields = _build_lawyer_fields(profile)
                lawyer = upsert_lawyer(session, lawyer_fields)
                safe_sleep(1.2, 2.5)
    except requests.RequestException as exc:
        logging.warning("⚠️ Lawyer enrichment failed", extra={"lawyer": lawyer_name, "error": str(exc)})
        safe_sleep(1.0, 2.0)

    company: Optional[Company] = None
    if company_fields:
        if lawyer:
            company_fields["lawyer_id"] = lawyer.id
        company = upsert_company(session, case, company_fields)

    upsert_insolvency_case(session, case, company, lawyer)
    safe_sleep(0.3, 0.8)


def run_daily_sync(date_iso: str | None = None) -> None:
    date_iso = date_iso or date.today().isoformat()
    logging.info("🔄 Running sync", extra={"date": date_iso})

    try:
        response = requests.get(f"{STATSTIDENDE_URL}/insolvencies/{date_iso}", timeout=30)
        response.raise_for_status()
        insolvencies = response.json().get("results", [])
    except requests.RequestException as exc:
        logging.error("❌ Failed fetching Statstidende data", extra={"error": str(exc)})
        return

    logging.info("Found insolvencies", extra={"count": len(insolvencies), "date": date_iso})

    with SessionLocal() as session:
        for index, case in enumerate(insolvencies, start=1):
            try:
                process_insolvency_case(session, case, index, len(insolvencies))
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                logging.error(
                    "❌ Integrity error during sync",
                    extra={"case": case, "error": str(exc)},
                )
            except SQLAlchemyError as exc:
                session.rollback()
                logging.exception(
                    "❌ Database error during sync", extra={"case": case, "error": str(exc)}
                )
            except Exception as exc:  # noqa: BLE001 - ensure sync continues on unexpected errors
                session.rollback()
                logging.exception(
                    "⚠️ Unexpected error during sync", extra={"case": case, "error": str(exc)}
                )

    logging.info("✅ Completed sync", extra={"date": date_iso, "count": len(insolvencies)})


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
    with SessionLocal() as session:
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

    return {"count": len(results), "results": results}


@app.get("/lawyers/{lawyer_id}")
def get_lawyer_with_cases(lawyer_id: int) -> dict:
    with SessionLocal() as session:
        lawyer = session.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
        if not lawyer:
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

    return response
