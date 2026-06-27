# Deploying Evavo Quotation Platform on DigitalOcean

Target: **DigitalOcean Managed PostgreSQL + Ubuntu Droplet + nginx + Let's Encrypt**.

This guide migrates the app from MSSQL to PostgreSQL and deploys it to the cloud.

---

## Quick Summary

| Item | Spec | Cost/mo |
|---|---|---|
| **Droplet** | Ubuntu 22.04 LTS, 1 vCPU, 1 GB RAM, 25 GB SSD | ~$6 |
| **Database** | Managed PostgreSQL, 1 GB RAM, 25 GB storage | ~$15 |
| **Networking** | Floating IP, Firewall | free + $3 |
| **Total** | | ~$24–25/mo |

**Time to deploy:** 1–2 hours (after code migration to PostgreSQL).

---

## Prerequisites

1. **DigitalOcean account** — created and billing set up.
2. **Git repository** (optional, makes deployment cleaner) or a way to copy files to the Droplet.
3. **SSH key** — stored locally; you'll add it to the Droplet during creation.
4. **Domain name** — optional but recommended (e.g., `quotation.evavo.in`); pointed to the Droplet's Floating IP.

---

## Phase 1: SQLAlchemy Migration (MSSQL → PostgreSQL)

**Status:** ✅ Already done in `requirements.txt`, `config.py`, and `db.py`.

The app now detects your database type automatically:
- If `EVAVO_PG_HOST` is set, uses PostgreSQL.
- If `EVAVO_DATABASE_URL` starts with `postgresql://`, uses PostgreSQL.
- Otherwise, defaults to MSSQL.

### Local verification (5 mins)

Test PostgreSQL locally before cloud deployment:

```bash
cd backend

# Start a local PostgreSQL container
docker run --name test-pg -e POSTGRES_PASSWORD=testpass -p 5432:5432 -d postgres:16

# Create .env pointing at it
cat > .env <<'EOF'
EVAVO_DATABASE_URL=postgresql://postgres:testpass@localhost:5432/postgres
EVAVO_JWT_SECRET=test-secret
EVAVO_SHEETS_DIR=../../../working\ excel\ sheet\ from\ clients
EOF

# Create tables
source .venv/bin/activate
python manage.py init-db

# Seed and import
python manage.py seed
python manage.py import-excel

# Run parity check (must pass)
python manage.py parity
# Expected: "Parity PASS", "Max diff: 0.000000 INR"

# Clean up
docker stop test-pg
docker rm test-pg
```

If parity passes, you're ready for cloud deployment. ✅

---

## Phase 2: DigitalOcean Infrastructure Setup

### Step 1: Create Managed PostgreSQL Cluster

1. Log into [DigitalOcean console](https://cloud.digitalocean.com/).
2. **Databases** → **Create Database Cluster**.
3. Choose:
   - **Database engine:** PostgreSQL
   - **Version:** 16 (latest)
   - **Plan:** $15/mo (1 GB RAM, 25 GB storage, suitable for < 10 concurrent users)
   - **Region:** closest to your users (e.g., `blr1` for India, `fra1` for Europe)
   - **Cluster name:** `evavo-postgres` (or any name)
4. **Enable backups:** Yes (default: daily, 7-day retention)
5. Click **Create Cluster**.

**Wait ~2–3 mins for provisioning.** Then:

6. On the cluster details page, copy the **Connection String**:
   ```
   postgresql://dbaas_user:PASSWORD@[host].[region].mdb.digitalocean.com:25060/defaultdb
   ```
   Change `defaultdb` → `evavo` in the connection string (we'll create the DB later).
   
7. **Note down:**
   - Host: `[host].[region].mdb.digitalocean.com`
   - Port: `25060`
   - Username: `dbaas_user`
   - Password: (shown on this page)

### Step 2: Create Droplet (App Server)

1. **Droplets** → **Create Droplet**.
2. Choose:
   - **Image:** Ubuntu 22.04 LTS
   - **Plan:** Basic, $6/mo (1 vCPU, 1 GB RAM, 25 GB SSD)
   - **Backups:** Enable (auto daily snapshots)
   - **Region:** same as database (e.g., `blr1`)
   - **SSH key:** select or create new
3. Click **Create Droplet**.

**Wait ~30 sec for Droplet to boot.**

4. On the Droplet page, assign a **Floating IP** (or create one):
   - Click **Networking** → **Floating IPs** → **Assign Floating IP**.
   - Assign to your new Droplet.
   - Note the Floating IP (e.g., `192.168.1.100`).

### Step 3: Configure DNS (Optional but Recommended)

1. In your domain registrar (GoDaddy, Namecheap, etc.):
   - Create an **A record** → `quotation.evavo.in` → Floating IP.
2. Wait for DNS propagation (~5–30 min).
3. Verify: `nslookup quotation.evavo.in` should resolve to the Floating IP.

---

## Phase 3: Deploy App to Droplet

### Step 4: SSH & Set Up the System

```bash
# SSH into Droplet
ssh -i /path/to/your-key.pem root@<floating-ip>

# Update packages
apt update && apt upgrade -y

# Install Python, git, build tools
apt install -y python3.11 python3-pip python3-venv git curl build-essential

# Clone or copy the project
# Option A: Git clone (if you have a repo)
git clone https://github.com/your-org/evavo-quotation.git /opt/evavo-quotation

# Option B: SCP from your laptop
# (on your laptop, in a new terminal):
scp -r /path/to/evavo-quotation root@<floating-ip>:/opt/

cd /opt/evavo-quotation/backend
```

### Step 5: Create virtualenv & Install Dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Confirm psycopg2 installed
pip list | grep psycopg2
# Should show: psycopg2-binary   2.9.9
```

### Step 6: Create `.env.production`

```bash
cat > .env.production <<'EOF'
EVAVO_DATABASE_URL=postgresql://dbaas_user:YOUR_PASSWORD@host.region.mdb.digitalocean.com:25060/evavo
EVAVO_JWT_SECRET=CHANGE_ME_use_output_from_below
EVAVO_CORS_ORIGINS=quotation.evavo.in,localhost
EVAVO_SHEETS_DIR=/opt/evavo-quotation/working\ excel\ sheet\ from\ clients
EVAVO_DB_ECHO=false
EOF

# Generate a strong JWT secret (replace CHANGE_ME_... with the output)
python -c "import secrets; print(secrets.token_urlsafe(48))"
# Copy the output and paste it into the file above

chmod 600 .env.production
```

### Step 7: Initialize the Database (One-Time)

```bash
cd /opt/evavo-quotation/backend
source .venv/bin/activate
export $(cat .env.production | xargs)

# Create tables in PostgreSQL
python manage.py init-db

# Seed default users, FX, terms, demo leads
python manage.py seed

# Import the 169 products from Excel
python manage.py import-excel

# Verify parity on PostgreSQL (critical!)
python manage.py parity
# Expected: "Parity PASS", "Max diff: 0.000000 INR"
```

### Step 8: Manual Smoke Test

```bash
# Test the app on localhost:8000 before installing as a service
source .venv/bin/activate
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In another terminal (or browser):
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","db_connected":true}
```

Open `http://<floating-ip>:8000/` in a browser:
- Sign in as `manager@evavo.test` / `manager123`
- Verify: products load, cost/margin visible
- Build a test quote, export PDF
- Check cost/margin are in the PDF

Then stop the test server: `Ctrl+C`.

### Step 9: Install as systemd Service (Auto-Start on Reboot)

Create the service file:
```bash
cat > /etc/systemd/system/evavo-quotation.service <<'EOF'
[Unit]
Description=Evavo Quotation Platform
After=network.target
Documentation=file:///opt/evavo-quotation/README.md

[Service]
Type=notify
User=www-data
WorkingDirectory=/opt/evavo-quotation/backend
Environment="PATH=/opt/evavo-quotation/backend/.venv/bin"
EnvironmentFile=/opt/evavo-quotation/backend/.env.production
ExecStart=/opt/evavo-quotation/backend/.venv/bin/uvicorn \
  app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable evavo-quotation
systemctl start evavo-quotation
systemctl status evavo-quotation

# Check logs
journalctl -u evavo-quotation -f
```

Press `Ctrl+C` to exit logs. Service is now running.

### Step 10: Configure Firewall

```bash
# Allow SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

### Step 11: Install nginx (Reverse Proxy) & Let's Encrypt SSL

```bash
# Install nginx and certbot
apt install -y nginx certbot python3-certbot-nginx

# Create nginx config
cat > /etc/nginx/sites-available/evavo <<'EOF'
server {
    listen 80;
    server_name quotation.evavo.in;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# Enable the site
ln -s /etc/nginx/sites-available/evavo /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test nginx config
nginx -t

# Reload nginx
systemctl reload nginx

# Get SSL certificate from Let's Encrypt
certbot --nginx -d quotation.evavo.in --agree-tos -m your-email@example.com
# Certbot will prompt; accept and provide your email.
# It automatically updates nginx to use HTTPS and sets up auto-renewal.

# Verify SSL
systemctl reload nginx
```

Verify HTTPS works:
```bash
curl https://quotation.evavo.in/health
# Expected: {"status":"ok","db_connected":true}
```

---

## Phase 4: Verification

### Test 1: Database Connectivity

```bash
psql -h [host].region.mdb.digitalocean.com -U dbaas_user -d evavo \
  -c "SELECT COUNT(*) FROM products;"
# Expected: 169
```

### Test 2: Parity on Cloud

```bash
cd /opt/evavo-quotation/backend
source .venv/bin/activate
export $(cat .env.production | xargs)
python manage.py parity
# Expected: "Parity PASS", "Max diff: 0.000000 INR"
```

### Test 3: API Health

```bash
curl https://quotation.evavo.in/health
# Expected: {"status":"ok","db_connected":true}
```

### Test 4: Full Workflow

1. Open `https://quotation.evavo.in` in a browser.
2. Sign in as `manager@evavo.test` / `manager123`.
3. Verify:
   - Dashboard loads with real data (leads, quotes).
   - Products visible, cost/margin columns present.
4. Build a test quote:
   - Add 1–2 products from the catalog.
   - Set quantities, apply a discount.
   - Review totals (should match Excel prices).
5. Export to PDF:
   - Open Client Preview, export PDF.
   - Verify PDF loads, no cost/margin fields visible.
6. Test sales user (no cost visibility):
   - Change password for `sales@evavo.test` (via Admin panel).
   - Log out, sign in as sales user.
   - Verify cost/margin columns ABSENT from product list and quote builder.

### Test 5: Check Backups

In DigitalOcean console:
- **Databases** → cluster → **Backups** → latest backup < 24 hrs old.
- **Droplet** → **Backups** → latest snapshot < 24 hrs old.

---

## Ongoing Operations

### Weekly Check
- Log into DigitalOcean console, verify no alerts.
- Check app logs: `journalctl -u evavo-quotation -f` (should show requests, no errors).

### Monthly Maintenance
```bash
# Review logs for errors
journalctl -u evavo-quotation --since="1 month ago" | grep -i error

# Update app (if new code pushed to repo)
cd /opt/evavo-quotation
git pull
pip install -r backend/requirements.txt  # if deps changed
systemctl restart evavo-quotation

# Verify after restart
curl https://quotation.evavo.in/health
```

### Backup Strategy
- **PostgreSQL:** automatic daily snapshots (7-day retention, managed by DigitalOcean).
- **Droplet:** automatic daily snapshots (manage in console; keep 4 most recent).
- **App code:** already in Git.
- **Excel sheets:** included in `/opt/evavo-quotation/working excel sheet from clients`; backed up with Droplet snapshots.

### Monitoring
DigitalOcean Monitoring (free):
- Shows CPU, memory, disk, network graphs on the console.
- Set uptime alerts: Monitor → Uptime → `quotation.evavo.in/health` endpoint.

### Scaling (if needed later)
1. **More users:** Upgrade Droplet (click droplet → Resize → choose larger plan).
2. **More connections:** Upgrade Managed Database (same cluster page → resize).
3. **Better performance:** Add a second Droplet, use a Load Balancer (future enhancement).

---

## Troubleshooting

### "Connection refused" to PostgreSQL
- Verify `EVAVO_DATABASE_URL` is correct (copy from DigitalOcean console).
- Confirm Droplet can reach the Managed Database (should be in the same region).
- Check firewall rules in DigitalOcean console (Managed Database should allow Droplet).

### "Table does not exist"
- Run `python manage.py init-db` again (it re-creates missing tables).
- Verify `EVAVO_DATABASE_URL` points to the correct database (not `defaultdb`).

### "Permission denied" on .env.production
- Ensure file is readable by www-data: `sudo chown www-data:www-data .env.production`.

### HTTPS not working
- Run `certbot --nginx -d quotation.evavo.in` again.
- Check `/etc/nginx/sites-enabled/evavo` was auto-updated by certbot.
- Reload nginx: `systemctl reload nginx`.

### App logs show errors
```bash
journalctl -u evavo-quotation -n 50  # last 50 lines
journalctl -u evavo-quotation -f     # live follow
```

---

## Next Steps

1. **Change default passwords** (Admin → Users):
   - `sales@evavo.test`, `manager@evavo.test`, `admin@evavo.test`
   - Delete or deactivate demo users if needed.

2. **Configure SMTP email** (Masters → Email Setup):
   - If you want quote-by-email to work, add your SMTP credentials.
   - Test with a quote email.

3. **Customize Masters** (Masters screens):
   - Add real clients, cities, terms templates, leads.
   - Adjust FX rates as needed.

4. **Domain SSL certificate** (optional but recommended):
   - If using a custom domain (not just floating IP), certbot handles it automatically.
   - Renewal is automatic; no manual action needed.

---

## Comparison: Windows Server vs. DigitalOcean

| Aspect | Windows Server | DigitalOcean |
|---|---|---|
| **DB** | Local SQL Server | Managed PostgreSQL (cloud) |
| **Setup** | PowerShell, NSSM, IIS | bash, systemd, nginx |
| **Code changes** | None (MSSQL) | SQLAlchemy → PostgreSQL (done) |
| **Costs** | Your hardware | ~$25/mo |
| **Ops** | Manual backups, updates | Automatic backups, managed DB |
| **HTTPS** | IIS + certificate | nginx + Let's Encrypt (auto-renew) |
| **Scaling** | Replace hardware | Upgrade Droplet/DB on console |
| **Uptime monitoring** | Manual health checks | Built-in DigitalOcean monitoring |

---

## Support & Questions

Refer to the main [README.md](../README.md) for API endpoints and architecture overview.
