from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

from models import Base

DATABASE_URL = os.getenv("DATABASE_URL", "postgres://insolvency:password@postgres/insolvencydb")
print("DATABASE_URL: ")
print(DATABASE_URL)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
