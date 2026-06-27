"""Management CLI for deployment & maintenance.

    python manage.py init-db       # CREATE DATABASE (if absent) + create tables
    python manage.py seed          # default users, FX, terms, demo leads
    python manage.py import-excel  # migrate the Excel master sheets into the DB
    python manage.py parity        # engine-vs-Excel parity report
    python manage.py all           # init-db + seed + import-excel  (first-time setup)

Reads connection settings from environment / .env (EVAVO_DB_*). See .env.example.
"""

from __future__ import annotations

import argparse
import sys


def init_db() -> None:
    """Create the target database if it doesn't exist, then create all tables."""
    from sqlalchemy import create_engine, text
    from app.core.config import settings

    # 1) CREATE DATABASE on master (autocommit — DDL can't run in a transaction).
    if settings.sqlalchemy_url.startswith("mssql"):
        master = create_engine(settings.master_url, isolation_level="AUTOCOMMIT")
        with master.connect() as conn:
            exists = conn.execute(
                text("SELECT DB_ID(:n)"), {"n": settings.db_name}).scalar()
            if exists is None:
                conn.execute(text(f"CREATE DATABASE [{settings.db_name}]"))
                print(f"Created database [{settings.db_name}].")
            else:
                print(f"Database [{settings.db_name}] already exists.")
        master.dispose()

    # 2) Create tables on the target database.
    from app.db import create_all
    create_all()
    print("Tables created / verified.")


def seed() -> None:
    from app.db import get_session
    from app.seed import seed as _seed
    gen = get_session(); db = next(gen)
    try:
        _seed(db)
        print("Seeded users, FX rates, terms templates and demo leads.")
    finally:
        gen.close()


def import_excel() -> None:
    from app.main import run_import
    result = run_import()
    print(f"Imported {result['imported']} products "
          f"(inserted {result['inserted']}, updated {result['updated']}).")
    print("Categories:", ", ".join(result["categories"]))


def parity() -> None:
    from app.importer.parity_check import report
    from app.core.config import settings
    report(settings.sheets_dir or None)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Evavo Quotation Platform management CLI")
    p.add_argument("command",
                   choices=["init-db", "seed", "import-excel", "parity", "all"])
    args = p.parse_args(argv)

    if args.command == "init-db":
        init_db()
    elif args.command == "seed":
        seed()
    elif args.command == "import-excel":
        import_excel()
    elif args.command == "parity":
        parity()
    elif args.command == "all":
        init_db(); seed(); import_excel()
        print("\nFirst-time setup complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
