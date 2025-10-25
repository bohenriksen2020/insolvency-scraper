from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from .db import Base, SessionLocal, engine, session_scope
from .models import CompanyAssets, Insolvency, InsolvencyLawyer, Lawyer
from .scheduler import shutdown_scheduler, start_scheduler
from .services.advokat import AdvokatService
from .services.cvr import CvrService
from .services.statstidende import StatstidendeService
from .utils import parse_date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Insolvency Aggregator", version="1.0.0")

statstidende_service = StatstidendeService()
advokat_service = AdvokatService()
cvr_service = CvrService()


class LawyerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: Optional[str]
    firm: Optional[str]
    address: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None


class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    cvr: Optional[str]
    tangible_assets: Optional[float] = None
    fixtures: Optional[float] = None
    inventories: Optional[float] = None
    vehicles: Optional[float] = None
    land_buildings: Optional[float] = None
    updated_at: Optional[datetime] = None


class InsolvencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cvr: Optional[str]
    company_name: Optional[str]
    court: Optional[str]
    date_declared: Optional[date]
    lawyer_name: Optional[str]
    lawyer_firm: Optional[str]
    created_at: Optional[datetime]
    lawyers: List[LawyerResponse] = Field(default_factory=list)
    assets: Optional[AssetResponse] = None


class LawyerCasesResponse(BaseModel):
    lawyer: LawyerResponse
    insolvencies: List[InsolvencyResponse]


class SummaryBucket(BaseModel):
    key: str
    count: int


class DashboardSummaryResponse(BaseModel):
    by_date: List[SummaryBucket]
    by_court: List[SummaryBucket]


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_or_create_lawyer(db: Session, name: Optional[str], firm: Optional[str]) -> Optional[Lawyer]:
    if not name:
        return None
    normalized_name = name.strip()
    if not normalized_name:
        return None
    lawyer = (
        db.query(Lawyer)
        .filter(func.lower(Lawyer.name) == normalized_name.lower())
        .first()
    )
    if not lawyer:
        lawyer = Lawyer(name=normalized_name, firm=firm)
        db.add(lawyer)
        db.flush()
    return lawyer


def _enrich_lawyer(db: Session, lawyer: Lawyer) -> None:
    if not lawyer or (lawyer.email and lawyer.phone and lawyer.address):
        return
    try:
        details = advokat_service.fetch_lawyer(lawyer.name or "")
    except Exception:  # pragma: no cover - network error
        logger.exception("Failed to enrich lawyer", extra={"name": lawyer.name})
        return
    if not details:
        return
    lawyer.firm = details.get("firm") or lawyer.firm
    lawyer.address = details.get("address") or lawyer.address
    lawyer.email = details.get("email") or lawyer.email
    lawyer.phone = details.get("phone") or lawyer.phone
    lawyer.website = details.get("website") or lawyer.website


def _link_lawyer(db: Session, insolvency: Insolvency, lawyer: Lawyer) -> None:
    if not lawyer:
        return
    exists = (
        db.query(InsolvencyLawyer)
        .filter(
            InsolvencyLawyer.insolvency_id == insolvency.id,
            InsolvencyLawyer.lawyer_id == lawyer.id,
        )
        .first()
    )
    if not exists:
        db.add(InsolvencyLawyer(insolvency_id=insolvency.id, lawyer_id=lawyer.id))


def _upsert_assets(db: Session, cvr: Optional[str]) -> None:
    if not cvr:
        return
    try:
        payload = cvr_service.fetch_company(cvr)
    except Exception:  # pragma: no cover - network error
        logger.exception("Failed to fetch company assets", extra={"cvr": cvr})
        return
    if not payload:
        return
    assets_data = cvr_service.extract_assets(payload)
    assets = db.query(CompanyAssets).filter_by(cvr=cvr).one_or_none()
    if not assets:
        assets = CompanyAssets(cvr=cvr, **assets_data)
        db.add(assets)
    else:
        for field, value in assets_data.items():
            setattr(assets, field, value)


def fetch_daily_insolvencies(target_date: Optional[str] = None) -> Dict[str, Any]:
    logger.info("Starting insolvency ingestion", extra={"date": target_date})
    try:
        records = statstidende_service.fetch_insolvencies(target_date)
    except Exception:  # pragma: no cover - network error
        logger.exception("Failed to fetch insolvencies from Statstidende")
        return {"fetched": 0, "created": 0, "updated": 0}
    created = 0
    updated = 0

    with session_scope() as db:
        for item in records:
            cvr = item.get("cvr")
            if not cvr:
                logger.warning("Skipping insolvency without CVR", extra={"payload": item})
                continue
            try:
                declared = parse_date(item.get("date_declared"))
            except ValueError:
                logger.warning(
                    "Skipping insolvency due to unparseable date",
                    extra={"cvr": cvr, "date": item.get("date_declared")},
                )
                continue
            insolvency = (
                db.query(Insolvency)
                .filter(Insolvency.cvr == cvr, Insolvency.date_declared == declared)
                .one_or_none()
            )
            if not insolvency:
                insolvency = Insolvency(
                    cvr=cvr,
                    company_name=item.get("company_name"),
                    court=item.get("court"),
                    date_declared=declared,
                    lawyer_name=item.get("lawyer_name"),
                    lawyer_firm=item.get("lawyer_firm"),
                )
                db.add(insolvency)
                db.flush()
                created += 1
            else:
                insolvency.company_name = item.get("company_name") or insolvency.company_name
                insolvency.court = item.get("court") or insolvency.court
                insolvency.lawyer_name = item.get("lawyer_name") or insolvency.lawyer_name
                insolvency.lawyer_firm = item.get("lawyer_firm") or insolvency.lawyer_firm
                updated += 1

            lawyer = _get_or_create_lawyer(db, insolvency.lawyer_name, insolvency.lawyer_firm)
            if lawyer:
                _enrich_lawyer(db, lawyer)
                _link_lawyer(db, insolvency, lawyer)

            _upsert_assets(db, cvr)

    logger.info("Completed insolvency ingestion", extra={"created": created, "updated": updated})
    return {"fetched": len(records), "created": created, "updated": updated}


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Creating database tables if they do not exist")
    Base.metadata.create_all(bind=engine)
    start_scheduler(fetch_daily_insolvencies)
    fetch_daily_insolvencies()


@app.on_event("shutdown")
def on_shutdown() -> None:
    shutdown_scheduler()
    statstidende_service.close()
    advokat_service.close()
    cvr_service.close()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/insolvencies/recent", response_model=List[InsolvencyResponse])
def recent_insolvencies(
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[InsolvencyResponse]:
    insolvencies = (
        db.query(Insolvency)
        .options(joinedload(Insolvency.lawyers), joinedload(Insolvency.assets))
        .order_by(Insolvency.date_declared.desc(), Insolvency.created_at.desc())
        .limit(limit)
        .all()
    )
    return [InsolvencyResponse.model_validate(insolvency) for insolvency in insolvencies]


@app.get("/api/lawyers/{name}", response_model=LawyerCasesResponse)
def get_lawyer_cases(name: str, db: Session = Depends(get_db)) -> LawyerCasesResponse:
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Name must not be empty")
    lawyer = (
        db.query(Lawyer)
        .filter(func.lower(Lawyer.name) == normalized_name.lower())
        .options(joinedload(Lawyer.insolvencies))
        .first()
    )
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer not found")

    insolvencies = (
        db.query(Insolvency)
        .join(InsolvencyLawyer, Insolvency.id == InsolvencyLawyer.insolvency_id)
        .filter(InsolvencyLawyer.lawyer_id == lawyer.id)
        .options(joinedload(Insolvency.lawyers), joinedload(Insolvency.assets))
        .order_by(Insolvency.date_declared.desc())
        .all()
    )
    return LawyerCasesResponse(
        lawyer=LawyerResponse.model_validate(lawyer),
        insolvencies=[InsolvencyResponse.model_validate(insolvency) for insolvency in insolvencies],
    )


@app.get("/api/dashboard/summary", response_model=DashboardSummaryResponse)
def get_summary(db: Session = Depends(get_db)) -> DashboardSummaryResponse:
    date_counts = (
        db.query(Insolvency.date_declared, func.count(Insolvency.id))
        .group_by(Insolvency.date_declared)
        .order_by(Insolvency.date_declared.desc())
        .all()
    )
    court_counts = (
        db.query(Insolvency.court, func.count(Insolvency.id))
        .group_by(Insolvency.court)
        .order_by(func.count(Insolvency.id).desc())
        .all()
    )

    by_date = [SummaryBucket(key=str(row[0]), count=row[1]) for row in date_counts if row[0]]
    by_court = [SummaryBucket(key=row[0] or "Unknown", count=row[1]) for row in court_counts]
    return DashboardSummaryResponse(by_date=by_date, by_court=by_court)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8002)
