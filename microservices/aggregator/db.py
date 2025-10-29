from __future__ import annotations

import os
from typing import Callable

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from models import Base

DEFAULT_DATABASE_URL = "postgresql://insolvency:password@postgres/insolvencydb"


def _normalize_database_url(raw_url: str) -> str:
    """Ensure SQLAlchemy receives a supported database URL."""

    if raw_url.startswith("postgres://"):
        return "postgresql://" + raw_url[len("postgres://") :]
    return raw_url


DATABASE_URL = _normalize_database_url(os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))

engine: Engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)

SessionLocal: Callable = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
