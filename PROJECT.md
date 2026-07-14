# PROJECT.md — Evavo Quotation Platform (Live State)

This file tracks the *current* state of the project — what's built, what's in flight,
what's known-broken. Permanent conventions and architecture rules live in
[`CLAUDE.md`](CLAUDE.md); this file is expected to change every session.

## Project Overview

Cloud-based CPQ (quote configure-price-quote) system for Evavo (spa & salon equipment),
replacing a manual Excel quoting workflow with a role-gated pricing engine, quote
builder, and sales pipeline (leads → projects → quotes).

## Current Development Phase

Post-launch / live production. Original 6-phase build (scaffold → pricing engine →
API → frontend → masters/PDF/email → deploy) is complete; work is now incremental
features and fixes on top of the DigitalOcean production deployment.

## Completed Features

- Pricing engine (`pricing.py`) — cost → client → list price build-up, parity-tested
  against client Excel masters (169 products, 0.0 INR diff)
- Role-gated visibility (sales / manager / admin) enforced server-side in `serialize.py`
- JWT auth (OAuth2 password flow), bcrypt hashing
- Quote builder: product picker with persistent add/remove toggle, live preview,
  PDF generation (fpdf2), email send (SMTP), quote revisions (`/quotes/{id}/revise`)
- Quote lines snapshot price/cost at creation (historical quotes don't reprice)
- Masters restructured into Client → Project → Lead hierarchy (separate CRUD pages)
- Lead-based autofill in Quote Builder, with a per-Lead site address
- Sales pipeline dashboard: KPIs, recent quotes (click-to-reopen), pipeline bars, kanban
- Admin-only User Management page (users CRUD via `/api/users`)
- Manual live FX rate refresh (manager/admin only) via `api.frankfurter.dev`,
  ordered by newest insertion (not just rate date)
- Excel import + parity check (`importer/excel_import.py`, `parity_check.py`)
- GitHub Actions CI/CD: `test.yml` (pytest on push/PR to `main`), `deploy.yml`
  (SSH deploy to DigitalOcean Droplet on push to `main`)
- Product photo extraction from Excel masters, rendered in catalog
- Mobile/WhatsApp number capture: `clients.mobile` (default) with a per-Lead
  `whatsapp_number` override, autofilled into the Quote Builder and snapshotted
  per quote
- "Send by WhatsApp" — free `wa.me` click-to-chat link (no paid API), built
  server-side (`POST /quotes/{id}/whatsapp`) and opened client-side
- Public, unauthenticated, token-based quote PDF link (`GET /quotes/share/{token}/pdf`)
  for the WhatsApp/email messages to point at — client-safe only, no cost/margin
- Basic app-level logging (`logging.basicConfig` in `main.py`) — email/WhatsApp
  send attempts are logged (INFO on success/dry-run, ERROR on failure)

## Features In Progress

None currently tracked — repo working tree is clean, no open branches.

## Pending Features

- FX auto-repricing: decomposing stored cost from converted INR back to
  *source EUR/USD × supplier discount × procurement FX* so products auto-reprice
  on FX swings (`source_currency`/`fx_rate` columns are reserved for this, deferred
  by design decision — see Decision Log)

## Current Sprint

No active sprint tracked in-repo. Latest commit: `ed7085b` — "Fix FX rate ordering:
pick newest by insertion, not just date."

## Architecture Overview

```
Browser (vanilla HTML/JS SPA)
   │  fetch() via frontend/api.js
   ▼
FastAPI app (backend/app/main.py)
   ├── routers/  auth, users, products, masters, fx, quotes
   ├── core/     pricing.py (engine), security.py (JWT/roles), serialize.py (cost gating)
   ├── services/ email.py (SMTP), pdf.py (branded PDF)
   └── importer/ excel_import.py, parity_check.py
   ▼
SQLAlchemy ORM → PostgreSQL (prod) / MSSQL or SQLite (local dev only)
```

Single FastAPI process serves both the JSON API and the static frontend
(`main.py` mounts `frontend/` as static files) — one deployable unit, one port.

## Database Schema Summary

12 entities (`backend/app/models.py`): `User`, `FxRate`, `Category`, `Product`, `City`,
`Client`, `Project`, `Lead`, `TermsTemplate`, `EmailSetup`, `Quote`, `QuoteLine`.

Hierarchy: `Client` → `Project` → `Lead` → `Quote` → `QuoteLine`. `Product` belongs to
`Category`. Migrations are not tracked via Alembic — schema is created/kept in sync via
`manage.py init-db`, which now does two things: `Base.metadata.create_all()` (creates
missing *tables* only) followed by `db.py`'s `_add_missing_columns()` (idempotent
`ALTER TABLE ADD COLUMN`, so new columns reach already-deployed databases too), run on
every deploy.

Contact fields added this session: `clients.mobile` (WhatsApp default, separate from
the pre-existing `clients.phone`), `leads.whatsapp_number` (per-lead override),
`quotes.customer_mobile` + `quotes.share_token` (snapshotted per quote at save time).

## API Inventory

| Router | Endpoints |
|---|---|
| `auth` | `POST /login`, `GET /me` |
| `users` | `GET/POST ""`, `PUT/DELETE /{user_id}` (admin only) |
| `products` | `GET ""`, `GET /{product_id}` (role-gated cost fields) |
| `masters` | terms (`GET/POST/PUT`), email-setup (`GET/PUT`), products (`PUT`), clients/projects/leads (full CRUD), `PATCH /leads/{id}/stage` |
| `fx` | `GET ""`, `POST ""`, `POST /refresh` (live rate pull, manager/admin) |
| `quotes` | `POST/GET ""`, `GET/{id}`, `GET /{id}/preview` (client-safe), `PATCH /{id}/status`, `GET /{id}/pdf`, `POST /{id}/email`, `POST /{id}/whatsapp` (wa.me link), `GET /share/{token}/pdf` (**public, no auth**), `POST /{id}/revise` |
| top-level | `GET /health`, `GET /api/parity`, `POST /api/import`, `POST /api/admin/seed` |

Auth: JWT bearer, OAuth2 password flow. Role gating enforced in `serialize.py`, not
per-endpoint — sales-role responses have cost/margin keys stripped server-side.

## Frontend Pages

Single-page app (`frontend/index.html` + `app.js`, no build tool). Render functions
per view: Products/Catalog (`renderProducts`, `renderPicker`), Quote Builder
(`renderItems`, `renderPreview`), Masters — Clients/Projects/Leads/Terms/Email/Users
(`renderClientsMaster`, `renderProjectsMaster`, `renderLeadsMaster`, `renderTermsMaster`,
`renderEmailMaster`, `renderUsersMaster`), Dashboard (`renderKpis`, `renderRecentQuotes`,
`renderPipelineBars`, `renderKanban`), FX table (`renderFxRows`).

## Reusable Components

None as formal components (vanilla JS, no framework) — shared rendering helpers live
directly in `app.js`; shared styling in `styles.css`.

## Business Rules

- Sales role never sees cost/margin — enforced server-side, not just hidden in UI
- Quote lines snapshot price/cost at creation; later FX or pricing changes don't
  retroactively reprice existing quotes
- Sending a quote that's pending approval is blocked unless the actor is a manager
- Client-facing quote preview (`/quotes/{id}/preview`) never includes cost fields,
  verified by a recursive test asserting no confidential field leaks
- Quote WhatsApp/mobile number defaults from `Client.mobile`, overridable per Lead
  (`Lead.whatsapp_number`) and again per quote in the Quote Builder; the value used
  is snapshotted onto the Quote at save time, same as customer name/email/address
- The public share-link PDF (`GET /quotes/share/{token}/pdf`) is looked up only by
  the unguessable `share_token`, never by quote id, and is always built from the
  same client-safe payload as the authed PDF route

## Integrations

- **SMTP** (`services/email.py`) — sends quote PDFs to clients, configured via
  Masters > Email Setup (works with Gmail SMTP + an App Password as-is)
- **api.frankfurter.dev** — live FX rate source for manual refresh (`POST /fx/refresh`)
- **WhatsApp click-to-chat (`wa.me`)** — free, no API key/account needed; built
  server-side, opened client-side. Bare 10-digit numbers are assumed Indian
  (`+91` prefix) — see Known Limitations

## Environment Variables

All `EVAVO_`-prefixed (see `.env.example`):
- DB: `EVAVO_DB_*` (MSSQL) or `EVAVO_PG_*` (PostgreSQL) or `EVAVO_DATABASE_URL` (direct)
- Auth: `EVAVO_JWT_SECRET`, `EVAVO_JWT_EXPIRE_MINUTES`
- Import: `EVAVO_SHEETS_DIR` (optional, defaults to the client Excel workbook location)
- Sharing: `EVAVO_APP_PUBLIC_URL` (optional — forces the domain used in WhatsApp/email
  share links; falls back to the incoming request's own host if unset)
- Production uses `EVAVO_PG_*` exclusively (see Deployment Status)
- Gmail SMTP credentials are **not** an env var — configured in-app under
  Masters > Email Setup (DB-driven, not `.env`)

## Configuration

`backend/app/core/config.py` auto-detects DB backend from which env vars are set
(MSSQL vs PostgreSQL vs direct URL). `dev_server.py` forces SQLite for zero-setup
local runs.

## Deployment Status

**Live in production** on DigitalOcean: Ubuntu Droplet (`/opt/evavo-quotation`) +
Managed PostgreSQL, systemd (`evavo-quotation.service`) + nginx + Let's Encrypt,
~$25/mo. Deploys automatically via `.github/workflows/deploy.yml` on push to `main`
(SSH in, `git reset --hard origin/main`, reinstall deps, `manage.py init-db`, restart
service). See `deploy/DEPLOY-DIGITALOCEAN.md`.

Windows Server + MSSQL deploy path (`deploy/DEPLOY-WINDOWS.md`) exists in the repo but
is **dead/unused** — not a supported or maintained path (per [`CLAUDE.md`](CLAUDE.md)).

## Known Bugs

None currently tracked open.

## Known Limitations

- No Alembic/formal migration tool — new *columns* now propagate to production via
  `db.py`'s `_add_missing_columns()` on every deploy, but destructive changes (drop/
  rename a column, change a type) still require manual intervention
- FX rates don't auto-reprice existing product cost basis (see Pending Features)
- WhatsApp number normalization is a heuristic: bare 10-digit numbers are assumed
  Indian and get a `+91` prefix; numbers already including a country code, or from
  outside India, may need to be entered with the country code typed in manually
- No validity/expiry date is tracked on a Quote, so the WhatsApp/email message omits
  it rather than inventing a field for it

## Technical Debt

- `deploy/DEPLOY-WINDOWS.md` and MSSQL support in `config.py`/`docker-compose.yml` are
  unused dead paths kept in the repo — candidates for removal if they start causing
  confusion, but currently harmless
- README.md's endpoint table and phase-status table predate the Client→Project→Lead
  masters redesign, user management, and FX refresh features — kept as historical
  onboarding narrative, not a live API reference (this file and `CLAUDE.md` are the
  live references)

## Recent Refactoring

- Masters redesigned from a flat structure into Client → Project → Lead hierarchy with
  separate CRUD pages (`c516adb`)
- Product picker rewritten as a persistent add/remove toggle after two prior overflow/
  sizing bugs (`46d9e50`, `82c37a5`, `3fc238a`)

## Upcoming Tasks

None currently tracked in-repo.

## Future Ideas

- FX-driven auto-repricing (decompose stored cost to source currency × FX), reserved
  via `source_currency`/`fx_rate` columns but not implemented

## Decision Log

**2026 (build phase) — Store cost as pre-converted INR, not source currency**
- **Decision:** Each product's cost basis is stored as the already-converted INR
  cost-to-Evavo rather than decomposed into source EUR/USD × supplier discount ×
  procurement FX.
- **Reason:** Gives exact parity (0.0 INR diff) against the client's existing Excel
  masters, which was the acceptance bar for the pricing engine.
- **Alternatives considered:** Store source currency + FX rate and compute cost live.
- **Trade-off:** Products don't auto-reprice when FX rates move; `source_currency`/
  `fx_rate` columns are reserved on the model for a future migration to the live
  computation.
- **Impact:** Manual FX refresh (`POST /fx/refresh`) updates the FX table for new
  quotes/imports, but existing product cost basis is unaffected until re-imported.

**2026-06 — Linux + PostgreSQL only for production, Windows/MSSQL abandoned**
- **Decision:** Production runs exclusively on a DigitalOcean Ubuntu Droplet +
  PostgreSQL.
- **Reason:** Simpler, cheaper managed hosting than a Windows Server + MSSQL license.
- **Alternatives considered:** Windows Server deploy (fully built in Phase 5 — NSSM
  service, SQL-login setup, step-by-step guide).
- **Trade-off:** The Windows/MSSQL path (`deploy/DEPLOY-WINDOWS.md`, MSSQL branch in
  `config.py`/`docker-compose.yml`) is now dead code left in the repo.
- **Impact:** Do not suggest or extend the Windows/MSSQL path; treat `EVAVO_PG_*` +
  the DigitalOcean guide as the only real deployment target.

**2026-07-14 — WhatsApp click-to-chat + public share link, not a paid API or a new SMTP config path**
- **Decision:** WhatsApp send uses a free `wa.me` link (no Meta/WhatsApp Business API);
  email keeps using the existing DB-driven Email Setup page rather than adding
  `.env`-based Gmail credentials; both messages link to a new public, token-based
  PDF endpoint rather than requiring the customer to log in.
- **Reason:** Lowest cost/complexity that's still reliable for business use; avoids
  duplicating SMTP config in two places; a real clickable link was worth one small,
  narrowly-scoped unauthenticated endpoint since the PDF it serves is already
  guaranteed cost/margin-free.
- **Alternatives considered:** WhatsApp Business Platform/Cloud API (paid, needs Meta
  Business verification and message templates); `.env`-based `GMAIL_SMTP_*` vars as
  originally suggested; no share link at all (text/PDF-attachment only).
- **Trade-off:** `share_token` grants access to that one quote's PDF to anyone with
  the link (mitigated: unguessable 24-byte token, client-safe data only, no cost/
  margin ever); bare 10-digit WhatsApp numbers assume India (+91).
- **Impact:** Don't add a second Gmail config path; don't build a paid WhatsApp
  integration unless the user explicitly asks after hitting a real limitation of
  the free click-to-chat flow (e.g. needing automated/programmatic sends).

## Session Summary

### 2026-07-14 — Documentation baseline established
- **Files changed:** `CLAUDE.md` (minor: added `test_fx_refresh.py` to test file
  list), `PROJECT.md` (created)
- **New features:** none (documentation-only session)
- **Bug fixes:** none
- **Refactoring:** none
- **Database changes:** none
- **API changes:** none
- **Breaking changes:** none
- **Documentation updated:** Created `PROJECT.md` as the live-state companion to
  `CLAUDE.md`, reconstructed from current codebase state (models, routers, frontend
  render functions, git log, env vars) since no PROJECT.md previously existed.

### 2026-07-14 — Mobile number capture + WhatsApp/Gmail send
- **Files changed:** `backend/app/models.py`, `backend/app/db.py`,
  `backend/app/schemas.py`, `backend/app/routers/masters.py`,
  `backend/app/routers/quotes.py`, `backend/app/core/config.py`,
  `backend/app/core/serialize.py`, `backend/app/services/email.py`,
  `backend/app/main.py`, `frontend/index.html`, `frontend/app.js`,
  `frontend/api.js`, `frontend/styles.css`, `.env.example`, `CLAUDE.md`,
  `PROJECT.md`
- **New features:** Client `mobile` field + per-Lead `whatsapp_number` override,
  autofilled into the Quote Builder (Lead override → Client default) and
  snapshotted per quote; "Send by WhatsApp" (free `wa.me` click-to-chat, no paid
  API) and an enhanced "Send by Email" on the quote preview page; public
  token-based share-link PDF endpoint; basic app-level logging
- **Bug fixes:** none
- **Refactoring:** `quote_email`'s hardcoded message body replaced with a shared
  `_quote_message()` helper reused by the new WhatsApp endpoint
- **Database changes:** added `clients.mobile`, `leads.whatsapp_number`,
  `quotes.customer_mobile`, `quotes.share_token`; added `db.py`'s
  `_add_missing_columns()` idempotent column-migration step (see Decision Log —
  needed because `create_all()` alone doesn't reach already-deployed tables)
- **API changes:** new `POST /api/quotes/{id}/whatsapp`, new public
  `GET /api/quotes/share/{token}/pdf` (no auth); `quote_out`/`ClientIn`/`LeadIn`/
  `QuoteCreate` gained the new fields; `list_clients`/`list_leads` include them
- **Breaking changes:** none (all additive)
- **Documentation updated:** `CLAUDE.md` (schema-migration pattern, WhatsApp/
  email architecture, new columns) and this file (Completed Features, DB schema,
  API inventory, Business Rules, Integrations, env vars, Known Limitations,
  Decision Log)
- **Verified:** `pytest -q` (28 passed) both before and after the `main.py`
  logging change; full browser walkthrough on the dev server — client/lead
  mobile fields save and reload, builder autofill (Lead override → Client
  fallback) confirmed both ways, quote save snapshots `customer_mobile`,
  WhatsApp button produces a correct `wa.me` link and 422s with no phone, email
  dry-run unaffected, public share PDF returns 200 with no auth and contains no
  cost/margin text, and both INFO/WARNING log lines appear in the server console
