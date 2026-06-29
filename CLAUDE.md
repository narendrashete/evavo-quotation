# Evavo Quotation Platform

A cloud-based quotation/CPQ system for Evavo (spa & salon equipment) that replaces a manual Excel-based quoting workflow with a role-gated pricing engine, quote builder, and sales pipeline.

## Tech Stack

- **Backend:** FastAPI 0.111 + Uvicorn (Python, async), SQLAlchemy 2.0 ORM, Pydantic schemas
- **Database:** MSSQL (pyodbc) or PostgreSQL (psycopg2) — cloud-agnostic, auto-detected from env vars. SQLite supported for local dev (`dev_server.py`)
- **Frontend:** Vanilla HTML/JS/CSS SPA — no build tool, no framework (`index.html`, `app.js`, `api.js`, `styles.css`)
- **Auth:** JWT (python-jose), OAuth2 password flow, bcrypt password hashing
- **Other:** openpyxl (Excel import), fpdf2 (PDF quote generation), pytest

## Directory Structure

```
backend/app/
  core/        config.py, pricing.py (pricing engine), security.py (JWT/roles), serialize.py (cost-field filtering)
  routers/     auth.py, products.py, quotes.py, masters.py, fx.py, users.py
  services/    email.py (SMTP), pdf.py (branded quote PDF)
  importer/    excel_import.py, parity_check.py (engine-vs-Excel parity gate)
  models.py    SQLAlchemy ORM (14 entities)
  schemas.py   Pydantic request/response models
  main.py      FastAPI app + router mounting + static file serving
  seed.py      default users, FX rates, demo data
backend/manage.py     CLI: init-db, seed, import-excel, parity, all
backend/dev_server.py single-port SQLite dev mode
backend/tests/        conftest.py, test_pricing.py, test_parity.py, test_api_roles.py
frontend/             index.html, app.js, api.js, styles.css
deploy/               DEPLOY-WINDOWS.md, DEPLOY-DIGITALOCEAN.md, create-sql-login.sql, setup.ps1
```

## Core Concepts

**Pricing engine** (`backend/app/core/pricing.py`) is the single source of truth for cost → client price → list price conversion (loading_factor, client_markup, list_uplift, installment %, packaging, freight, FX). It is parity-tested against the client's Excel masters (169 products, 0.0 INR diff) — any change here must keep `pytest backend/tests/test_parity.py` green.

**Role-based visibility** is enforced at the serialization layer (`serialize.py`), not just the UI:
- `sales` — sees product names + list prices only; cost/margin fields are stripped server-side
- `manager` — full visibility (cost, final_c2e, margins)
- `admin` — manager visibility + user management

When adding new fields to products/quotes that touch cost or margin, update `serialize.py`'s field allowlist — don't rely on the frontend to hide them.

**Quote lines snapshot price/cost at creation time** so historical quotes don't reprice when FX rates or product pricing change later.

## Database Entities

`users`, `fx_rates`, `categories`, `products`, `clients`, `projects`, `leads`, `terms_templates`, `email_setup`, `quotes`, `quote_lines`, `cities`

## Running Locally

```bash
# Quick demo (SQLite, no SQL Server needed)
cd backend && pip install -r requirements.txt
python dev_server.py                    # http://127.0.0.1:8013
curl -X POST localhost:8013/api/admin/seed
curl -X POST localhost:8013/api/import

# Full stack (Docker, MSSQL)
docker compose up --build               # FastAPI :8000 + MSSQL :1433

# Manual (custom SQL Server / Postgres via .env)
cd backend && python manage.py all      # init-db + seed + import + parity
uvicorn app.main:app --reload
```

Dev login defaults: `sales@evavo.test/sales123`, `manager@evavo.test/manager123`, `admin@evavo.test/admin123`.

## Testing

Run `pytest` from `backend/`. Always re-run `test_parity.py` after touching `pricing.py` — it's the regression gate against the client's Excel masters.

## Deployment

**This app runs exclusively on Linux + PostgreSQL.** Windows Server and MSSQL are not used at all — not even as a legacy/secondary path — despite docs/code (`deploy/DEPLOY-WINDOWS.md`, MSSQL support in `config.py`/`docker-compose.yml`) referencing them. Treat those as dead/unused for this project; don't default to them in suggestions.

**Live production path:** GitHub repo → DigitalOcean Ubuntu Droplet (`/opt/evavo-quotation`) → PostgreSQL → systemd (`evavo-quotation.service`) + nginx + Let's Encrypt. See `deploy/DEPLOY-DIGITALOCEAN.md`. Use `EVAVO_PG_*` env vars exclusively.

Docker compose (`docker-compose.yml`) is for local dev only, not how production is deployed.

## CI/CD (GitHub Actions)

- `.github/workflows/test.yml` — runs `pytest` on every push/PR to `main`.
- `.github/workflows/deploy.yml` — on push to `main`, SSHes into the Droplet, `git reset --hard origin/main`, `pip install -r requirements.txt`, `python manage.py init-db` (idempotent — creates any missing tables), then restarts `evavo-quotation.service` and verifies it's active.

Required GitHub repo secrets (Settings → Secrets and variables → Actions):
- `DO_HOST` — Droplet IP or floating IP
- `DO_USER` — SSH user (e.g. `root` or a deploy user with sudo)
- `DO_SSH_KEY` — private key for that user (matching public key must be in the Droplet's `~/.ssh/authorized_keys`)

If the deploy user is not `root`, it needs passwordless `sudo` for `systemctl restart evavo-quotation` (add a sudoers rule), since the workflow calls `sudo systemctl restart`.
