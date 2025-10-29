from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    JSON,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()


class Lawyer(Base):
    __tablename__ = "lawyers"
    __table_args__ = (UniqueConstraint("name", "firm", name="uq_lawyer_name_firm"),)

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    firm = Column(String, nullable=True)
    city = Column(String, nullable=True)
    email = Column(String, nullable=True)
    cvr = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    cases = relationship("InsolvencyCase", back_populates="lawyer", lazy="selectin")
    companies = relationship("Company", back_populates="lawyer", lazy="selectin")


class Company(Base):
    __tablename__ = "companies"

    cvr = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(String, nullable=True)
    assets = Column(JSON, nullable=True)
    address = Column(String, nullable=True)
    zip_city = Column(String, nullable=True)
    municipality = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    industry_code = Column(String, nullable=True)
    industry_text = Column(String, nullable=True)
    fiscal_year_end = Column(String, nullable=True)
    fiscal_year_start = Column(String, nullable=True)
    capital = Column(Float, nullable=True)
    purpose = Column(String, nullable=True)
    latest_regnskab_period = Column(String, nullable=True)
    employees_latest = Column(String, nullable=True)
    raw_cvr = Column(JSON, nullable=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    lawyer = relationship("Lawyer", back_populates="companies", lazy="joined")
    cases = relationship("InsolvencyCase", back_populates="company", lazy="selectin")


class InsolvencyCase(Base):
    __tablename__ = "insolvency_cases"

    id = Column(Integer, primary_key=True)
    message_number = Column(String, unique=True, index=True)
    publication_date = Column(String, index=True)
    company_name = Column(String, index=True)
    cvr = Column(String, ForeignKey("companies.cvr"))
    court = Column(String, nullable=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    company = relationship("Company", back_populates="cases", lazy="joined")
    lawyer = relationship("Lawyer", back_populates="cases", lazy="joined")
