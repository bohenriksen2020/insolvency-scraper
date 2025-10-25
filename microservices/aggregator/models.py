"""SQLAlchemy models for the aggregator service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .db import Base


class Insolvency(Base):
    __tablename__ = "insolvencies"

    id = Column(Integer, primary_key=True)
    cvr = Column(String, index=True)
    company_name = Column(String)
    court = Column(String)
    date_declared = Column(Date)
    lawyer_name = Column(String)
    lawyer_firm = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    lawyers = relationship(
        "Lawyer",
        secondary="insolvency_lawyers",
        back_populates="insolvencies",
    )

    assets = relationship(
        "CompanyAssets",
        primaryjoin="Insolvency.cvr == foreign(CompanyAssets.cvr)",
        uselist=False,
        viewonly=True,
    )


class Lawyer(Base):
    __tablename__ = "lawyers"

    id = Column(Integer, primary_key=True)
    name = Column(String, index=True)
    firm = Column(String)
    address = Column(String)
    email = Column(String)
    phone = Column(String)
    website = Column(String)

    insolvencies = relationship(
        "Insolvency",
        secondary="insolvency_lawyers",
        back_populates="lawyers",
    )


class InsolvencyLawyer(Base):
    __tablename__ = "insolvency_lawyers"

    insolvency_id = Column(Integer, ForeignKey("insolvencies.id"), primary_key=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), primary_key=True)


class CompanyAssets(Base):
    __tablename__ = "company_assets"

    id = Column(Integer, primary_key=True)
    cvr = Column(String, index=True)
    tangible_assets = Column(Float)
    fixtures = Column(Float)
    inventories = Column(Float)
    vehicles = Column(Float)
    land_buildings = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
