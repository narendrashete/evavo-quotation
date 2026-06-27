"""Application settings, loaded from environment / .env.

Cloud-agnostic by design: the DB connection and secrets come from the
environment so the same image runs against a local SQL Server container or a
managed cloud SQL Server (Azure SQL / AWS RDS / etc.) without code changes.
"""

from __future__ import annotations

import os
import urllib.parse

try:
    from pydantic import Field
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _HAVE_PYDANTIC_SETTINGS = True
except ImportError:  # lightweight fallback so the engine/parity tooling runs anywhere
    _HAVE_PYDANTIC_SETTINGS = False

    def Field(default=None, **_kw):  # type: ignore
        return default


class _SettingsBase:
    """Minimal env-backed settings used only when pydantic-settings is absent."""

    def __init__(self):
        for name, default in type(self).__annotations__.items():
            env = os.environ.get("EVAVO_" + name.upper())
            val = getattr(type(self), name, None)
            if env is not None:
                if isinstance(val, bool):
                    val = env.lower() in ("1", "true", "yes")
                elif isinstance(val, int):
                    val = int(env)
                else:
                    val = env
            setattr(self, name, val)


_Base = BaseSettings if _HAVE_PYDANTIC_SETTINGS else _SettingsBase


class Settings(_Base):
    if _HAVE_PYDANTIC_SETTINGS:
        model_config = SettingsConfigDict(env_file=".env", env_prefix="EVAVO_", extra="ignore")

    # --- Database ---
    # Supports both MSSQL (via pyodbc) and PostgreSQL (via psycopg2).
    # For PostgreSQL, set DATABASE_URL env var (preferred) or use pg_* vars below.
    # For MSSQL, set db_* env vars or DATABASE_URL.
    db_host: str = "localhost"
    db_port: int = 1433  # 1433 for MSSQL, 5432 for PostgreSQL
    db_name: str = "evavo"
    db_user: str = "sa"
    db_password: str = "Your_strong_Pass123"
    db_driver: str = "ODBC Driver 18 for SQL Server"  # MSSQL only
    db_trust_cert: bool = True            # local/dev self-signed certs (MSSQL only)
    db_echo: bool = False
    # PostgreSQL-specific settings
    pg_host: str = ""  # If set, build PostgreSQL URL instead of MSSQL
    pg_port: int = 5432
    pg_name: str = ""
    pg_user: str = ""
    pg_password: str = ""

    # --- Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # --- Web ---
    # Comma-separated allowed CORS origins. The SPA is served same-origin so this
    # only matters if a separate front-end host calls the API. "*" is fine for an
    # internal LAN tool; lock it down for anything internet-facing.
    cors_origins: str = "*"

    # --- Misc ---
    sheets_dir: str = Field(default="", description="Override path to client workbooks")
    # Full SQLAlchemy URL override (e.g. sqlite:///./evavo_dev.db) for lightweight
    # local/demo runs without a SQL Server. Takes precedence over db_* when set.
    database_url: str = ""

    def _odbc(self, database: str) -> str:
        return urllib.parse.quote_plus(
            f"DRIVER={{{self.db_driver}}};"
            f"SERVER={self.db_host},{self.db_port};"
            f"DATABASE={database};"
            f"UID={self.db_user};PWD={self.db_password};"
            f"TrustServerCertificate={'yes' if self.db_trust_cert else 'no'};"
            f"Encrypt={'yes' if not self.db_trust_cert else 'optional'};"
        )

    def _postgresql_url(self, database: str = "") -> str:
        """Build PostgreSQL connection URL."""
        user = urllib.parse.quote(self.pg_user, safe="")
        password = urllib.parse.quote(self.pg_password, safe="")
        db = database or self.pg_name
        return f"postgresql://{user}:{password}@{self.pg_host}:{self.pg_port}/{db}"

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        # Auto-detect: if pg_host is set, use PostgreSQL; else use MSSQL
        if self.pg_host:
            return self._postgresql_url()
        return f"mssql+pyodbc:///?odbc_connect={self._odbc(self.db_name)}"

    @property
    def master_url(self) -> str:
        """Connection to the server's 'master' DB, for CREATE DATABASE."""
        if self.pg_host:
            # PostgreSQL doesn't have a 'master' db; use 'postgres' (default system DB)
            return self._postgresql_url("postgres")
        return f"mssql+pyodbc:///?odbc_connect={self._odbc('master')}"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
