# Evavo Cloud Quotation Platform

Promotes the pricing logic hidden in Evavo's Excel master sheets into a secure,
server-side, multi-currency rate engine — with internal cost/margin walled off
from anyone in a sales role and from the client-facing documents entirely.

**Stack:** FastAPI + SQLAlchemy · MSSQL · vanilla HTML/JS/CSS · Docker (cloud-agnostic).

See [`../analyze-the-html-file-lucky-kitten.md`](.) for the full phased plan.

## Status

| Phase | What | State |
|------|------|-------|
| 0 | Scaffold + local DB | ✅ done |
| 1 | **Pricing engine + Excel import + parity** | ✅ done — parity PASSES (169 products, 0.0 INR diff) |
| 2 | API + role-gated quoting | ✅ done — JWT auth, cost gating, quote engine, approvals (20 tests pass) |
| 3 | Frontend wired to API | ✅ done — login, catalog, builder, preview, dashboard/pipeline (browser-verified) |
| 4 | Masters screens + PDF/email | ✅ done — Masters CRUD, branded PDF, email (SMTP), revisions (browser-verified) |
| 5 | Windows Server deploy | ✅ done — management CLI, NSSM service scripts, SQL-login setup, step-by-step guide |

## The pricing engine

`backend/app/core/pricing.py` is the single source of truth. The cost→price
build-up, reverse-engineered from the four client workbooks:

```
c2e_inr   = source_price * fx_rate * conversion_factor   # cost-to-Evavo, INR
final_c2e = c2e_inr * loading_factor                     # true unit cost (CONFIDENTIAL)
client    = (final_c2e | c2e_inr) * client_markup        # unit selling price
list      = client * (1 + list_uplift)                   # shown list price
```

Per-family constants live on the product/category (not hardcoded), and FX is a
dated table. Cost/margin fields are stripped for sales-role and client output.

**Deferred (by decision):** each product's cost basis is stored as the
already-converted INR cost-to-Evavo (gives exact parity). Decomposing it back to
*source EUR/USD × supplier discount × procurement FX* so FX swings auto-reprice
products is a later enhancement — `source_currency`/`fx_rate` columns are reserved
for it.

## Run the parity gate (no DB needed)

```bash
cd backend
pip install -r requirements.txt
python -m app.importer.parity_check     # prints the engine-vs-Excel report
pytest -q                               # 10 tests incl. the parity gate
```

Expected: 169 products imported, max cost/client diff `0.000000 INR`, 0 rows out
of tolerance, 18 non-standard rows flagged as manual overrides.

## Quick demo (no SQL Server — runs on SQLite)

```bash
cd backend
pip install -r requirements.txt
python dev_server.py                 # serves app + frontend on http://127.0.0.1:8013
# then in another shell:
curl -X POST localhost:8013/api/admin/seed     # users, FX, terms, demo leads
curl -X POST localhost:8013/api/import          # 169 products from the Excel masters
```

Open <http://127.0.0.1:8013/> and sign in (e.g. `manager@evavo.test / manager123`).
`dev_server.py` sets `EVAVO_DATABASE_URL=sqlite:///./evavo_dev.db` so no SQL Server
is required — ideal for local testing before the MSSQL/cloud deploy.

## Run the full stack locally (with DB)

```bash
docker compose up --build           # FastAPI on :8000, SQL Server on :1433
curl localhost:8000/health          # {"status":"ok","db_connected":true}
curl -X POST localhost:8000/api/import   # migrate the Excel masters into MSSQL
curl localhost:8000/api/parity      # parity report as JSON
```

Without Docker, set `backend/.env` (see `.env.example`), start a SQL Server, then
`uvicorn app.main:app --reload` from `backend/`.

### Seed & use the API

```bash
curl -X POST localhost:8000/api/admin/seed     # default users, FX, terms templates
# log in (form-encoded, OAuth2 password flow):
curl -X POST localhost:8000/api/auth/login -d "username=manager@evavo.test&password=manager123"
```

Default users (change in production): `sales@evavo.test / sales123`,
`manager@evavo.test / manager123`, `admin@evavo.test / admin123`.

| Endpoint | Notes |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me` | JWT login |
| `GET /api/products` | cost/margin only for manager/admin |
| `GET/POST /api/fx` | FX table; POST is manager/admin only |
| `POST /api/quotes` | engine computes totals + approval flag; lines snapshot prices |
| `GET /api/quotes/{id}` | role-gated (cost hidden for sales) |
| `GET /api/quotes/{id}/preview` | **client-safe** — cost never included |
| `PATCH /api/quotes/{id}/status` | blocks sending an approval-pending quote unless manager |
| `GET/POST/PUT/DELETE /api/masters/clients`, `/leads` | masters CRUD |

**Role gating is enforced server-side** — the serializers in
`app/core/serialize.py` omit cost keys entirely (a recursive test asserts no
confidential field appears in any sales or preview response).

## Layout

```
backend/app/core/pricing.py      # the engine (pure, unit-tested)
backend/app/importer/            # excel_import.py, parity_check.py
backend/app/models.py            # ORM: products, quotes, masters, fx, users
backend/app/main.py              # FastAPI: /health, /api/parity, /api/import
backend/tests/                   # pytest: engine unit tests + parity gate
frontend/                        # vanilla HTML/JS/CSS (Phase 3)
docker-compose.yml               # app + mssql
```

## Deploy to a Windows Server

Native Windows hosting (SQL login, existing SQL Server, app as a Windows Service on
a port) — full step-by-step in **[deploy/DEPLOY-WINDOWS.md](deploy/DEPLOY-WINDOWS.md)**.

Quick version on the server:

```powershell
# 1. create SQL login + db (edit password first)
#    run deploy\create-sql-login.sql in SSMS
# 2. venv + deps
deploy\setup.ps1 -BackendDir C:\Evavo\evavo-quotation\backend
# 3. configure  (copy deploy\.env.production.example -> backend\.env, edit)
# 4. create tables, seed, import the 169 products
backend\.venv\Scripts\python.exe backend\manage.py all
# 5. install as a Windows Service (auto-start, auto-restart)
deploy\install-service.ps1 -BackendDir ...backend -PythonExe ...python.exe -NssmExe ...nssm.exe -Port 8000
```

## Deploy to DigitalOcean (PostgreSQL)

Cloud deployment with managed PostgreSQL and Ubuntu Droplet — full step-by-step in
**[deploy/DEPLOY-DIGITALOCEAN.md](deploy/DEPLOY-DIGITALOCEAN.md)**.

**Specs:** $6/mo Droplet + $15/mo PostgreSQL = ~$25/mo total. Includes automated daily
backups, Let's Encrypt SSL, nginx reverse proxy, systemd auto-start.

Quick version:

```bash
# 1. Create DigitalOcean Managed PostgreSQL cluster ($15/mo)
# 2. Create Ubuntu 22.04 Droplet ($6/mo) with Floating IP
# 3. SSH into Droplet, git clone + pip install
# 4. Copy deploy/.env.production.postgres.example -> backend/.env.production (edit)
# 5. Run: python manage.py init-db && seed && import-excel && parity
# 6. Install systemd service + nginx + Let's Encrypt SSL
# 7. Access via https://quotation.evavo.in
```

The app automatically detects PostgreSQL via `DATABASE_URL` or `EVAVO_PG_*` env vars.
No code changes needed (SQLAlchemy migration already complete in `requirements.txt`,
`config.py`, and `db.py`).

## Management CLI

`backend/manage.py`: `init-db`, `seed`, `import-excel`, `parity`, `all`.
Works on both MSSQL and PostgreSQL (auto-detected from environment).
