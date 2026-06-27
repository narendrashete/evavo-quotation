"""Evavo Quotation Platform — FastAPI entrypoint (Phase 0/1 scaffold).

Runnable today:
  * GET /health        — app + DB connectivity status
  * GET /api/parity    — runs the engine-vs-Excel parity report (no DB needed)
  * POST /api/import    — migrate the Excel masters into the DB (needs SQL Server)

Phase 2 mounts the auth / products / quotes / masters routers here.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.importer.parity_check import report as parity_report
from app.importer.excel_import import import_all
from app.routers import auth, products, fx, quotes, masters

app = FastAPI(title="Evavo Quotation Platform", version="0.2.0")

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Force revalidation of the SPA assets so updates are picked up immediately.
    (API responses are dynamic anyway; this mainly matters for index/app/api/css.)"""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

for r in (auth.router, products.router, fx.router, quotes.router, masters.router):
    app.include_router(r)


@app.post("/api/admin/seed")
def admin_seed() -> dict:
    """Create tables and seed default users / FX / terms (idempotent)."""
    from app.db import get_session, create_all
    from app.seed import seed
    create_all()
    gen = get_session()
    db = next(gen)
    try:
        seed(db)
    finally:
        gen.close()
    return {"seeded": True,
            "users": ["sales@evavo.test", "manager@evavo.test", "admin@evavo.test"]}


@app.get("/health")
def health() -> dict:
    db_ok, db_err = False, None
    try:
        from sqlalchemy import text
        from app.db import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - depends on environment
        db_err = str(exc)[:200]
    return {"status": "ok", "db_connected": db_ok, "db_error": db_err}


@app.get("/api/parity")
def parity() -> dict:
    """Run the engine-vs-spreadsheet parity report (the Phase 1 gate)."""
    sheets_dir = settings.sheets_dir or None
    try:
        return parity_report(sheets_dir) if sheets_dir else parity_report()
    except Exception as exc:
        raise HTTPException(500, f"parity failed: {exc}")


@app.post("/api/import")
def run_import() -> dict:
    """Migrate the Excel master sheets into the DB (idempotent upsert by model+name)."""
    from sqlalchemy import select
    from app.db import get_session, create_all
    from app.models import Product, Category

    records = import_all(settings.sheets_dir) if settings.sheets_dir else import_all()
    create_all()
    inserted = updated = 0
    cats: dict[str, dict] = {}

    gen = get_session()
    db = next(gen)
    try:
        for rec in records:
            cats.setdefault(rec.category, {
                "loading_factor": rec.loading_factor,
                "client_markup": rec.client_markup,
                "list_uplift": rec.list_uplift,
                "markup_base": rec.markup_base.value,
            })
            key = (rec.model_no or "", rec.name)
            existing = db.execute(
                select(Product).where(Product.name == rec.name,
                                      Product.model_no == (rec.model_no or None))
            ).scalar_one_or_none()
            data = dict(
                name=rec.name, model_no=rec.model_no or None, category=rec.category,
                description=rec.description or None, product_link=rec.product_link or None,
                image=rec.image or None,
                source_price_inr=rec.source_price_inr, loading_factor=rec.loading_factor,
                client_markup=rec.client_markup, list_uplift=rec.list_uplift,
                markup_base=rec.markup_base.value,
                migrated_final_c2e=rec.migrated_final_c2e,
                migrated_client_unit=rec.migrated_client_unit,
                is_manual_override=rec.is_manual_override, source_file=rec.source_file,
            )
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                db.add(Product(**data))
                inserted += 1

        for name, c in cats.items():
            if not db.execute(select(Category).where(Category.name == name)).scalar_one_or_none():
                db.add(Category(name=name, **c))
        db.commit()
    finally:
        gen.close()

    return {"imported": len(records), "inserted": inserted, "updated": updated,
            "categories": list(cats)}


# Extracted product photos (from the Excel imports) — must be mounted before
# the frontend catch-all below.
_static = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(_static, "product_images"), exist_ok=True)
app.mount("/static", StaticFiles(directory=_static), name="static")

# Serve the vanilla HTML/JS/CSS frontend if present (Phase 3 fills this in).
_frontend = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
if os.path.isdir(_frontend):
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
