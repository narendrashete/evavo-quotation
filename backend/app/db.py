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
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _add_missing_columns(engine)


# Columns added after the initial deploy — create_all() only creates missing
# *tables*, so already-deployed databases need these applied by hand here.
# Safe to re-run: Postgres uses IF NOT EXISTS; other backends ignore duplicates.
_NEW_COLUMNS = [
    ("clients", "mobile", "VARCHAR(40)"),
    ("leads", "whatsapp_number", "VARCHAR(40)"),
    ("quotes", "customer_mobile", "VARCHAR(40)"),
    ("quotes", "share_token", "VARCHAR(48)"),
    # GST / freight / settings feature
    ("products", "hsn_code", "VARCHAR(20)"),
    ("products", "gst_pct", "DOUBLE PRECISION"),
    ("quotes", "install_amount", "DOUBLE PRECISION"),
    ("quotes", "local_freight", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "intl_freight", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "import_charge", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "place_of_supply", "VARCHAR(4)"),
    ("quotes", "home_state", "VARCHAR(4)"),
    ("quotes", "gst_default_pct", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "taxable_amount", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "gst_total", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "cgst", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "sgst", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "igst", "DOUBLE PRECISION DEFAULT 0"),
    ("quotes", "final_payable", "DOUBLE PRECISION DEFAULT 0"),
    ("quote_lines", "hsn_code", "VARCHAR(20)"),
    ("quote_lines", "gst_pct", "DOUBLE PRECISION DEFAULT 0"),
    ("quote_lines", "gst_amount", "DOUBLE PRECISION DEFAULT 0"),
    # Explicit approval workflow
    ("quotes", "approved", "BOOLEAN DEFAULT FALSE"),
    ("quotes", "approved_by", "VARCHAR(120)"),
    ("quotes", "approved_at", "TIMESTAMP"),
]


def _add_missing_columns(engine: Engine) -> None:
    from sqlalchemy import text
    is_postgres = engine.url.get_backend_name() == "postgresql"
    with engine.connect() as conn:
        for table, column, coltype in _NEW_COLUMNS:
            if is_postgres:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}"))
            else:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
                except Exception:
                    pass  # column already exists
        conn.commit()
