from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
import datetime

Base = declarative_base()


class Lawyer(Base):
    __tablename__ = "lawyers"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    firm = Column(String)
    city = Column(String)
    email = Column(String, nullable=True)
    cvr = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    cases = relationship("InsolvencyCase", back_populates="lawyer")
    companies = relationship("Company", back_populates="lawyer")


class Company(Base):
    __tablename__ = "companies"
    cvr = Column(String, primary_key=True)
    name = Column(String)
    status = Column(String)
    assets = Column(JSON)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    lawyer = relationship("Lawyer", back_populates="companies")
    cases = relationship("InsolvencyCase", back_populates="company")


class InsolvencyCase(Base):
    __tablename__ = "insolvency_cases"
    id = Column(Integer, primary_key=True)
    message_number = Column(String)
    publication_date = Column(String)
    company_name = Column(String)
    cvr = Column(String, ForeignKey("companies.cvr"))
    court = Column(String)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"))
    raw = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    company = relationship("Company", back_populates="cases")
    lawyer = relationship("Lawyer", back_populates="cases")
