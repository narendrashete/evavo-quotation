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
  models.py    SQLAlchemy ORM (13 entities)
  schemas.py   Pydantic request/response models
  main.py      FastAPI app + router mounting + static file serving
  seed.py      default users, FX rates, demo data
backend/manage.py     CLI: init-db, seed, import-excel, parity, all
backend/dev_server.py single-port SQLite dev mode
backend/tests/        conftest.py, test_pricing.py, test_parity.py, test_api_roles.py, test_fx_refresh.py
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

**Quote lines snapshot price/cost at creation time** so historical quotes don't reprice when FX rates or product pricing change later. Quotes also snapshot `customer_name/email/address/mobile` from the Client/Lead at save time, plus a `share_token` — never re-derive customer contact info from the live Client row for an existing quote.

**No Alembic** — schema sync is `Base.metadata.create_all()` (`db.py: create_all()`), which only creates *missing tables*, not missing columns on already-deployed tables. Since production has live data, any new column added to `models.py` must also get an entry in `db.py`'s `_add_missing_columns()` (idempotent `ALTER TABLE ADD COLUMN`, Postgres uses `IF NOT EXISTS`) — otherwise it silently never appears in production even though `manage.py init-db` runs on every deploy.

**WhatsApp/Email send** (`routers/quotes.py`): "Send by WhatsApp" is a free `wa.me` click-to-chat link built server-side (`POST /quotes/{id}/whatsapp`, no paid API) and opened client-side via `window.open()`. Email reuses the existing DB-driven Email Setup (Masters > Email Setup — Gmail SMTP + App Password works as-is, no `.env` SMTP config). Both share one message-builder (`_quote_message`) and a public, unauthenticated, token-based PDF link (`GET /quotes/share/{token}/pdf`, looked up by `Quote.share_token` — never by id) so a customer can view/download without logging in; that PDF is always built from `client_preview_out`, so cost/margin are structurally excluded, same guarantee as the authed `/pdf` route.

**GST / tax** (client-safe, never confidential): each `Product` carries an `hsn_code` + `gst_pct`; a line without its own rate falls back to the quote's default GST% (which defaults from `AppSettings.gst_default_pct`, 18%). The **taxable amount is composite** — goods net (after discount) + installation + packaging + freight/import — and GST is charged on the whole. Place of supply (a state code on the quote) vs Evavo's `home_state` (default 27, Maharashtra, in `AppSettings`) decides the split: equal → intra-state → CGST+SGST (each half); different → inter-state → IGST (full). `grand_total` stays **pre-tax**; the new `final_payable` = taxable + GST. All of this lives in `compute_quote` (`pricing.py`) as add-ons layered on top of the parity-gated `compute_unit` — never touch `compute_unit` or its inputs, and keep new totals fields defaulting to 0/off so `test_pricing.py` and the parity gate stay green. GST/HSN fields are **client-safe** (emitted for every role), unlike cost/margin.

**Discount cap** (`AppSettings.max_discount_pct`, default 12%, admin-editable only): a **hard** per-line cap enforced server-side in `create_quote` (422 for sales exceeding it) and client-side (clamp + toast). Manager/admin (`can_see_cost(role)`) may exceed it. This is separate from the softer `needs_approval` thresholds, which are unchanged. `GET /api/masters/settings` is readable by any authenticated user (the builder needs the defaults for sales too); `PUT` is admin-only.

**Editing a saved quote:** quotes remain immutable after creation (only `PATCH /status` and `revise`, which clones a new draft). Product prices are read-only in the builder for all roles; only manager/admin edit them via the Product master. Editing only HSN/GST/name on a product does **not** reset its parity-migrated pricing override — only editing a pricing field (`_PRICING_FIELDS` in `masters.py`) does.

## Database Entities

`users`, `fx_rates`, `categories`, `products`, `clients`, `projects`, `leads`, `terms_templates`, `email_setup`, `app_settings`, `quotes`, `quote_lines`, `cities`

Contact fields: `clients.phone` (landline/office) + `clients.mobile` (WhatsApp default) · `leads.whatsapp_number` (per-lead override, same pattern as `leads.address`) · `quotes.customer_mobile` + `quotes.share_token` (snapshotted per quote).

GST/tax fields: `products.hsn_code` + `products.gst_pct` · `quote_lines.hsn_code`/`gst_pct`/`gst_amount` (snapshots) · `quotes.place_of_supply`/`home_state`/`gst_default_pct` + snapshot totals `taxable_amount`/`gst_total`/`cgst`/`sgst`/`igst`/`final_payable`/`install_amount`/`local_freight`/`intl_freight`/`import_charge`. `app_settings` is a single-row config table (max_discount_pct, gst_default_pct, install_pct, local/intl/import freight defaults, home_state).

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
