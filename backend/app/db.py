"""SQLAlchemy engine/session setup.

Supports both MSSQL (via pyodbc) and PostgreSQL (via psycopg2).
The engine is created lazily so the app (and the pricing/parity tooling) can run
and be tested without a database present — only code paths that actually touch
the DB will require a reachable database.
"""

from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


class Base(DeclarativeBase):
    pass


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = settings.sqlalchemy_url
        kwargs = dict(echo=settings.db_echo, pool_pre_ping=True)
        if url.startswith("mssql"):
            kwargs["fast_executemany"] = True  # MSSQL-only optimisation
        elif url.startswith("postgresql"):
            # PostgreSQL pool settings for managed cloud databases
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
        _engine = create_engine(url, **kwargs)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yields a session, always closed afterwards."""
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all() -> None:
    """Create tables. Phase 0 convenience; Alembic migrations come later."""
    from app import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=get_engine())
