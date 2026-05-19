# THE AUTOMAT HUB — DEPLOYMENT AND ARCHITECTURE GUIDE
## automatcorp.org.ng — Production Setup

---

## 1. HOSTING ON automatcorp.org.ng

### Stack Recommendation
```
Domain:      automatcorp.org.ng (Namecheap/CloudFlare DNS)
Server:      Ubuntu 22.04 VPS (DigitalOcean $24/mo or Hetzner €14/mo)
Backend:     FastAPI (Python) running on port 8000
Frontend:    Static HTML served by FastAPI /frontend route (already wired)
Database:    PostgreSQL 15 (same server or managed)
Cache/Queue: Redis (Celery background tasks)
SSL:         Certbot (Let's Encrypt — free)
Reverse Proxy: Nginx (handles SSL, routes to FastAPI)
```

### Nginx Config — /etc/nginx/sites-available/automatcorp
```nginx
server {
    listen 80;
    server_name automatcorp.org.ng www.automatcorp.org.ng;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name automatcorp.org.ng www.automatcorp.org.ng;

    ssl_certificate     /etc/letsencrypt/live/automatcorp.org.ng/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/automatcorp.org.ng/privkey.pem;

    # WebSocket support (Live Tracking)
    location /ws/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host $host;
        proxy_read_timeout 86400;
    }

    # API and frontend
    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```

### Systemd Service — /etc/systemd/system/automat.service
```ini
[Unit]
Description=The Automat Hub API
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/automat
ExecStart=/home/ubuntu/automat/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 4
Restart=always
RestartSec=3
Environment=PYTHONPATH=/home/ubuntu/automat

[Install]
WantedBy=multi-user.target
```

### Deploy Commands
```bash
# On server (first time)
git clone https://github.com/yourrepo/automat-hub.git /home/ubuntu/automat
cd /home/ubuntu/automat
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy frontend
mkdir -p frontend
cp index.html frontend/

# Set up database
psql -U postgres -c "CREATE DATABASE automat_prod;"
alembic upgrade head

# SSL
certbot --nginx -d automatcorp.org.ng -d www.automatcorp.org.ng

# Start services
systemctl enable automat && systemctl start automat
systemctl reload nginx

# Frontend now live at:
# https://automatcorp.org.ng/frontend/index.html
# OR redirect root to frontend via nginx location /
```

---

## 2. VEHICLE LINKING ARCHITECTURE — COMPLETE PICTURE

### How a VIN Links to Everything
```
VIN (Global Unique ID — the anchor)
├── TrackedVehicle record (fleet.py model)
│   ├── owner_id → User (private owner OR fleet owner)
│   ├── fleet_id → Fleet (if fleet-owned)
│   ├── latest_dcp_id → DCPRecord (most recent passport)
│   ├── obd_adapter_id → hardware device serial
│   └── manufacturer_api_token → Tesla/connected car API
│
├── DCPRecord (dcp.py model)
│   ├── auditor_id → inspector User who issued it
│   ├── hash_record → DCPHashLedger (SHA-256, immutable)
│   ├── inspection → InspectionDetail (150-point data)
│   └── verifications[] → VerificationLog (every QR/NFC scan)
│
├── EscrowDeal (escrow.py model)
│   ├── dcp_id → must match active DCP
│   ├── buyer_name / seller_name
│   └── events[] → EscrowEvent (immutable audit trail)
│
├── HourlyScan[] → health history appended to DCP
├── VehicleAlert[] → fault notifications to owner
└── LocationHistory[] → GPS trail (90-day retention)
```

### Ownership Transfer on Sale
When a vehicle is sold via escrow and status reaches COMPLETED:
1. EscrowDeal.status → COMPLETED
2. TrackedVehicle.owner_id → new buyer's user_id
3. New DCP issued on new owner's subscription
4. Old DCP history preserved in hash ledger (immutable)
5. VerificationLog records the transfer event

**This must be implemented as a post-escrow hook** — add to escrow_service.py:
```python
async def transfer_vehicle_ownership(
    vehicle_id: str, new_owner_id: str, db: AsyncSession
):
    vehicle = await db.get(TrackedVehicle, vehicle_id)
    vehicle.owner_id = new_owner_id
    vehicle.fleet_id = None  # Detaches from old fleet
    # Create ownership transfer event
    await db.flush()
```

---

## 3. ARCHITECTURE LOOPHOLES — IDENTIFIED AND SOLUTIONS

### LOOPHOLE 1: Anyone can register any VIN
**Problem:** POST /fleet/vehicle/add has no VIN validation against real-world records.
**Solution:** Integrate EpicVIN API on registration — validate VIN exists and is not flagged as stolen/salvage before accepting.

### LOOPHOLE 2: Escrow with no DCP validation
**Problem:** create_escrow endpoint accepts any DCP ID — doesn't verify the DCP is ACTIVE and matches the VIN.
**Fix in escrow_service.py:**
```python
dcp = await db.execute(select(DCPRecord).where(
    DCPRecord.dcp_id == request.dcp_id,
    DCPRecord.vin == request.vin,
    DCPRecord.status == DCPStatus.VERIFIED
))
if not dcp.scalar_one_or_none():
    return {"error": "No active DCP found for this VIN"}
```

### LOOPHOLE 3: Hash ledger is append-only in code but not in database
**Problem:** Nothing prevents a rogue admin from running DELETE on dcp_hash_ledger.
**Fix:** PostgreSQL row-level security + revoke DELETE privilege:
```sql
REVOKE DELETE ON dcp_hash_ledger FROM automat_app;
REVOKE UPDATE ON dcp_hash_ledger FROM automat_app;
CREATE RULE no_delete_hash AS ON DELETE TO dcp_hash_ledger DO INSTEAD NOTHING;
```

### LOOPHOLE 4: Inspector field is self-reported
**Problem:** auditor_id on DCPRecord is just the JWT user — any logged-in user can call /dcp/issue.
**Fix:** Add role check in dcp.py endpoint:
```python
if current_user["role"] not in ["inspector", "admin"]:
    raise HTTPException(403, "Inspector role required to issue DCP")
```

### LOOPHOLE 5: Fleet owner can add unlimited vehicles beyond their subscription slot
**Problem:** No check against user.vehicle_slots when adding vehicles.
**Fix in fleet router:**
```python
vehicle_count = await db.scalar(select(func.count(TrackedVehicle.id))
    .where(TrackedVehicle.owner_id == current_user["user_id"]))
if vehicle_count >= user.vehicle_slots:
    raise HTTPException(402, f"Vehicle slot limit reached. Upgrade subscription.")
```

### LOOPHOLE 6: WebSocket has no fleet ownership verification
**Problem:** Any user with a valid JWT can connect to any fleet_id WebSocket.
**Fix:** Verify fleet_id belongs to the authenticated user before accepting the connection.

### LOOPHOLE 7: Odometer rollback window
**Problem:** There's a gap between DCP issuance and NFC scan at point of sale. Seller could swap OBD device.
**Fix:** Store obd_adapter_id in the DCP hash. If adapter changes, hash mismatch is immediate. Also require photo evidence stored in S3 at inspection.

### LOOPHOLE 8: Reseller API key in plaintext after generation
**Problem:** The full API key is returned ONCE but transmitted over the API response.
**Fix:** Already SHA-256 hashed in DB. Ensure HTTPS enforced on all endpoints (handled by Nginx above).

---

## 4. PRODUCTION ENVIRONMENT (.env)
```env
DATABASE_URL=postgresql://automat_user:STRONGPASSWORD@localhost:5432/automat_prod
SECRET_KEY=GENERATE_WITH_openssl_rand_hex_64
API_KEY=GENERATE_WITH_openssl_rand_hex_32
ENVIRONMENT=production
APP_URL=https://automatcorp.org.ng
CORS_ORIGINS=https://automatcorp.org.ng

# Paystack (replace with Flutterwave per config.py)
FLUTTERWAVE_SECRET_KEY=sk_live_XXXXXXXX
FLUTTERWAVE_PUBLIC_KEY=pk_live_XXXXXXXX

# AWS S3 (inspection photos)
AWS_ACCESS_KEY_ID=XXXXXX
AWS_SECRET_ACCESS_KEY=XXXXXX
AWS_BUCKET_NAME=automat-hub-production
AWS_REGION=eu-west-1

# Twilio (SMS alerts)
TWILIO_ACCOUNT_SID=XXXXXX
TWILIO_AUTH_TOKEN=XXXXXX
TWILIO_PHONE_NUMBER=+234XXXXXXXXXX

# Redis
REDIS_URL=redis://localhost:6379/0
```

---

## 5. WHAT TO BUILD NEXT (Priority Order)

### IMMEDIATE (before investor demo)
1. Fix Loophole 4 (inspector role check on DCP issue)
2. Fix Loophole 5 (vehicle slot enforcement)
3. Fix Loophole 2 (DCP-VIN validation in escrow)
4. Add ownership transfer hook to escrow_service.py
5. Deploy to VPS with SSL

### PHASE 2 (Month 1-2)
6. Mobile app (React Native) — OBD scan + NFC tap
7. EpicVIN integration for VIN validation
8. Paystack webhook handler (already scaffolded)
9. S3 photo upload for inspection photos
10. SMS alerts via Twilio on fault detection

### PHASE 3 (Month 3-6)
11. Dealer Reputation Graph scoring
12. Bank API access tier (per-scan $10 fee)
13. QR code generation on DCP issuance
14. Warranty management module
15. Automated DCP renewal on inspection

---

## 6. FRONTEND URL STRUCTURE

```
https://automatcorp.org.ng/                → Redirect to /frontend/index.html
https://automatcorp.org.ng/frontend/       → App shell (login)
https://automatcorp.org.ng/docs            → FastAPI Swagger docs
https://automatcorp.org.ng/health          → API health check
https://automatcorp.org.ng/api/...         → All API endpoints

# Public verification (no login needed — for QR codes on vehicles)
https://automatcorp.org.ng/dcp/verify/DCP-XXXXXXXX
```

**To make root redirect to frontend, add to main.py:**
```python
from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/frontend/index.html")
```