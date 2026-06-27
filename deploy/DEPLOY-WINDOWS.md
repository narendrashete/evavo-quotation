# Deploying Evavo Quotation Platform on a Windows Server

Target: your own Windows Server with **SQL Server already installed**, using a
**SQL login**, running the app **as a Windows Service on a port** (HTTP over LAN).
No Docker, no cloud.

The app serves both the API and the web UI from one process, so a single service
on one port is all you need.

---

## 0. Prerequisites (one-time)

On the server install:

1. **Python 3.11+** — <https://www.python.org/downloads/windows/> (tick "Add to PATH").
2. **ODBC Driver 18 for SQL Server** — <https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server>.
   (Check: `Get-OdbcDriver -Name "ODBC Driver 18 for SQL Server"`.)
3. **NSSM** — download `nssm.exe` from <https://nssm.cc/download> and put it e.g. in `C:\Tools\nssm\`.

---

## 1. Copy the project to the server

Put the project somewhere stable, e.g. `C:\Evavo\evavo-quotation\`, including the
`backend\` folder and the `working excel sheet from clients\` folder (for the
initial product import). Example layout:

```
C:\Evavo\evavo-quotation\backend\
C:\Evavo\working excel sheet from clients\
```

---

## 2. Create the SQL login and database

Edit `deploy\create-sql-login.sql` — set a strong password — then run it in SSMS
as `sa`/sysadmin. It creates the `evavo_app` login, the `evavo` database, and
grants ownership.

> If SQL logins fail later with *"Login failed for user"*, enable **Mixed Mode**
> authentication (SSMS → server → Properties → Security) and restart SQL Server.

Find the instance's TCP port (SQL Server Configuration Manager → Network Config →
TCP/IP → IP Addresses → IPAll → TCP Port; default `1433`). You'll need it for `.env`.

---

## 3. Create the virtualenv and install dependencies

```powershell
cd C:\Evavo\evavo-quotation\deploy
.\setup.ps1 -BackendDir C:\Evavo\evavo-quotation\backend
```

This creates `backend\.venv` and installs `requirements.txt`. Note the printed
python path: `C:\Evavo\evavo-quotation\backend\.venv\Scripts\python.exe`.

---

## 4. Configure the environment

Copy the template and edit it:

```powershell
Copy-Item C:\Evavo\evavo-quotation\deploy\.env.production.example `
          C:\Evavo\evavo-quotation\backend\.env
notepad C:\Evavo\evavo-quotation\backend\.env
```

Set at minimum: `EVAVO_DB_PORT`, `EVAVO_DB_USER`, `EVAVO_DB_PASSWORD`,
`EVAVO_JWT_SECRET` (generate one — command is in the file), and `EVAVO_SHEETS_DIR`
(absolute path to the Excel folder).

---

## 5. Initialise the database (create tables, seed, import products)

```powershell
cd C:\Evavo\evavo-quotation\backend
.\.venv\Scripts\python.exe manage.py all
```

Expected: tables created, defaults seeded, **169 products imported**. You can also
run the parity check to confirm the engine matches the spreadsheets on this server:

```powershell
.\.venv\Scripts\python.exe manage.py parity
```

---

## 6. Smoke-test before installing the service

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another window: `curl http://localhost:8000/health` → `{"status":"ok","db_connected":true}`.
Open `http://localhost:8000/` and sign in as `manager@evavo.test / manager123`.
Stop the test server with `Ctrl+C`.

---

## 7. Install as a Windows Service

```powershell
cd C:\Evavo\evavo-quotation\deploy
.\install-service.ps1 `
  -BackendDir C:\Evavo\evavo-quotation\backend `
  -PythonExe  C:\Evavo\evavo-quotation\backend\.venv\Scripts\python.exe `
  -NssmExe    C:\Tools\nssm\nssm.exe `
  -Port 8000 -Workers 2
```

The service `EvavoQuotation` starts automatically on boot, restarts on failure,
and logs to `backend\logs\`. Manage it with `nssm start|stop|restart EvavoQuotation`
or `services.msc`.

---

## 8. Open the firewall + access from the LAN

```powershell
New-NetFirewallRule -DisplayName "Evavo 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

Users reach it at `http://<server-name-or-ip>:8000/`.

---

## 9. Lock it down (do this before real use)

- **Change the default passwords.** Sign in as admin and replace the seeded
  `sales/manager/admin@evavo.test` accounts (or delete them and add real users).
- **`backend\.env`** holds the DB password and JWT secret — restrict it to the
  service account / admins (right-click → Properties → Security).
- Keep `EVAVO_JWT_SECRET` secret and unique to this server.
- HTTPS is optional for an internal LAN tool; see "Adding HTTPS later" below.

---

## 10. Updating the app later

```powershell
nssm stop EvavoQuotation
# copy in the new code (git pull or file copy)
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # if deps changed
.\.venv\Scripts\python.exe manage.py init-db                    # if models changed (creates new tables)
nssm start EvavoQuotation
```

> Schema note: `manage.py init-db` uses SQLAlchemy `create_all`, which creates
> missing tables but does **not** alter existing ones. If you later change a
> column, introduce Alembic migrations (a small follow-up) rather than dropping
> tables.

---

## 11. Backups & monitoring

- **Database:** schedule SQL Server backups of the `evavo` database (SSMS
  Maintenance Plan or `BACKUP DATABASE [evavo] TO DISK=...`). This is the system
  of record — quotes, products, masters all live here.
- **App logs:** `backend\logs\service.out.log` / `service.err.log` (auto-rotated at 10 MB).
- **Health:** `http://localhost:8000/health` for an uptime check.

---

## Adding HTTPS later (optional)

Put **IIS** in front as a reverse proxy: install the *URL Rewrite* and
*Application Request Routing (ARR)* modules, bind an SSL certificate to an IIS
site on 443, and add a reverse-proxy rule to `http://localhost:8000/`. The app
needs no changes. (Ask and this can be scripted with a ready-made `web.config`.)
