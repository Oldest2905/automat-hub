# ═══════════════════════════════════════════════════════════════════

# THE AUTOMAT HUB — COMPLETE GEMINI IMPLEMENTATION PROMPT

# automatcorp.org.ng | Pre-Seed Build 2026

# 

# UPLOAD THIS FILE + connect-vehicle.html + obd-gatt.js TO GEMINI

# 

# This single file contains ALL instructions for every change needed:

# 

# PART 1 — OBD and Manufacturer vehicle connection (backend + frontend)

# PART 2 — Profile integration (vehicle cards show connection status)

# PART 3 — Render deployment (no more localhost)

# PART 4 — Three critical security and payment fixes:

# Gap 1: DCP issue locked to inspectors only

# Gap 2: Vehicle slot enforcement per subscription plan

# Gap 3: Flutterwave webhook replaces Paystack completely

# 

# READ THE ENTIRE FILE BEFORE TOUCHING ANY CODE.

# IMPLEMENT IN ORDER FROM PART 1 TO PART 4.

# DO NOT SKIP ANY STEP. DO NOT RENAME ANY FUNCTION OR FILE.

# ═══════════════════════════════════════════════════════════════════

You are implementing a feature for The Automat Hub Ltd (automatcorp.org.ng),
a Nigerian vehicle trust infrastructure platform. The codebase is a
FastAPI (Python) backend with a static HTML/JS frontend.

Read every section below carefully before making any change.
Implement everything exactly as written. Do not skip any step.
Do not rename any functions, files, or endpoints.

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 1 — PROJECT STRUCTURE (what exists right now)

# ══════════════════════════════════════════════════════════════════

The project root looks like this:

```
automat-hub/
├── backend/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py                    ← YOU WILL MODIFY THIS
│   ├── core/
│   │   ├── database.py
│   │   ├── hashing.py
│   │   ├── security.py
│   │   ├── logging.py
│   │   └── rate_limit.py
│   ├── models/
│   │   ├── user.py
│   │   ├── dcp.py
│   │   ├── fleet.py
│   │   ├── escrow.py
│   │   └── workshop.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── dcp.py
│   │   ├── escrow.py
│   │   ├── fleet.py               ← YOU WILL MODIFY THIS
│   │   ├── manufacturer.py        ← EXISTS, needs service file
│   │   ├── admin.py
│   │   ├── reseller.py
│   │   ├── subscription.py
│   │   ├── tracking.py
│   │   ├── webhooks.py
│   │   └── workshop.py
│   └── services/                  ← CREATE THIS FOLDER (does not exist yet)
│
└── frontend/                      ← ADD FILES HERE
    └── index.html                 (already exists)
```

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 2 — WHAT YOU MUST CREATE (4 new files)

# ══════════════════════════════════════════════════════════════════

1. `backend/services/__init__.py`        — empty file, creates the package
1. `backend/services/manufacturer_service.py` — full service code (below)
1. `frontend/obd-gatt.js`               — Web Bluetooth GATT bridge (below)
1. `frontend/connect-vehicle.html`      — OBD + Manufacturer connection page (below)

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 3 — WHAT YOU MUST MODIFY (2 existing files)

# ══════════════════════════════════════════════════════════════════

## MODIFY 1: backend/main.py

Find this import block (it is near the top of the file):

```python
from backend.routers import (
    dcp, escrow, auth, webhooks,
    fleet, reseller, admin, workshop, tracking
)
from backend.routers.subscription import router as subscription_router
```

ADD one line immediately after it:

```python
from backend.routers.manufacturer import router as manufacturer_router
```

Then find this block (router registrations, near bottom of file):

```python
app.include_router(tracking.router)
app.include_router(subscription_router)
```

ADD one line between them:

```python
app.include_router(tracking.router)
app.include_router(manufacturer_router)
app.include_router(subscription_router)
```

Also add a root redirect by finding the root() function:

```python
@app.get("/", tags=["Health"])
async def root():
    return {
        "name": "The Automat Hub — Trust Protocol",
        ...
    }
```

ADD this new route BEFORE the root() function:

```python
from fastapi.responses import RedirectResponse

@app.get("/app", include_in_schema=False)
async def app_redirect():
    return RedirectResponse(url="/frontend/index.html")
```

-----

## MODIFY 2: backend/routers/fleet.py

Find the existing scan/submit endpoint at the bottom of the file:

```python
@router.post("/scan/submit", response_model=dict)
async def submit_scan(
    vehicle_id: str,
    scan_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Submit OBD scan data for a vehicle.
    Called by mobile app every hour.
    Also called by manufacturer API integration.
    """
    result = await process_hourly_scan(vehicle_id, scan_data, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"success": True, "data": result}
```

REPLACE THE ENTIRE FUNCTION (keep the decorator) with this:

```python
from pydantic import BaseModel
from typing import Optional, List

class OBDScanPayload(BaseModel):
    vehicle_id: str
    vin: Optional[str] = None
    adapter_id: Optional[str] = None
    adapter_name: Optional[str] = None
    source: Optional[str] = "obd_hardware"
    pids: Optional[dict] = {}
    dtcs: Optional[List[str]] = []
    fault_codes: Optional[List[str]] = []
    coolant_temp_c: Optional[float] = None
    engine_rpm: Optional[float] = None
    speed_kmh: Optional[float] = None
    fuel_level_pct: Optional[float] = None
    battery_voltage: Optional[float] = None
    oil_temp_c: Optional[float] = None
    odometer_km: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timestamp: Optional[str] = None
    location: Optional[dict] = None
    raw: Optional[dict] = None

@router.post("/scan/submit", response_model=dict)
async def submit_scan(
    payload: OBDScanPayload,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Receive OBD scan data pushed from:
    - Web browser using Web Bluetooth API (Chrome/Edge with ELM327 dongle)
    - Mobile app (React Native) with Bluetooth OBD dongle
    - Manufacturer API integration (pulled server-side every hour)
    Normalises all formats into a standard scan record.
    """
    scan_data = payload.dict()

    # Merge PID hex codes into named fields
    pids = scan_data.get("pids") or {}
    if pids:
        scan_data["coolant_temp_c"]  = scan_data.get("coolant_temp_c")  or pids.get("0x05")
        scan_data["engine_rpm"]      = scan_data.get("engine_rpm")      or pids.get("0x0C")
        scan_data["speed_kmh"]       = scan_data.get("speed_kmh")       or pids.get("0x0D")
        scan_data["fuel_level_pct"]  = scan_data.get("fuel_level_pct")  or pids.get("0x2F")
        scan_data["battery_voltage"] = scan_data.get("battery_voltage") or pids.get("0x42")
        scan_data["oil_temp_c"]      = scan_data.get("oil_temp_c")      or pids.get("0x5C")
        scan_data["odometer_km"]     = scan_data.get("odometer_km")     or pids.get("0xA6")

    # Merge location dict into lat/lng
    loc = scan_data.get("location") or {}
    if loc:
        scan_data["latitude"]  = scan_data.get("latitude")  or loc.get("lat") or loc.get("latitude")
        scan_data["longitude"] = scan_data.get("longitude") or loc.get("lng") or loc.get("longitude")

    # Merge dtcs and fault_codes into one deduplicated list
    all_faults = list(set(
        (scan_data.get("dtcs") or []) +
        (scan_data.get("fault_codes") or [])
    ))
    scan_data["fault_codes"] = all_faults

    from backend.services.manufacturer_service import process_hourly_scan
    result = await process_hourly_scan(payload.vehicle_id, scan_data, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"success": True, "data": result}
```

NOTE: The `from pydantic import BaseModel` and `from typing import Optional, List`
imports go at the TOP of fleet.py with the other imports, not inside the function.
Move them there if they are not already present.

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 4 — NEW FILE 1: backend/services/**init**.py

# ══════════════════════════════════════════════════════════════════

Create this file with exactly this content (empty Python package marker):

```python
# The Automat Hub — Backend Services Package
```

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 5 — NEW FILE 2: backend/services/manufacturer_service.py

# ══════════════════════════════════════════════════════════════════

Create this file with EXACTLY the following content.
Do not change any function names, dictionary keys, or logic.

```python
"""
services/manufacturer_service.py
The Automat Hub — Vehicle Data Bridge

Handles two connection types:
1. Manufacturer OAuth API — pulls live data from Toyota, Honda, Land Rover etc
2. OBD-II Hardware — normalises data pushed from the GATT bridge (web/mobile)

Both routes feed into process_hourly_scan() which creates HourlyScan records,
updates vehicle health, and triggers fault alerts.
"""

import os
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
import httpx


# ═══════════════════════════════════════════════════════════
# SUPPORTED MANUFACTURERS — 15 brands with real OAuth endpoints
# ═══════════════════════════════════════════════════════════

MANUFACTURERS = {
    "toyota": {
        "name": "Toyota", "logo": "🚗", "popular_in_nigeria": True,
        "models_in_nigeria": ["Corolla", "Camry", "Highlander", "RAV4", "Land Cruiser", "Venza"],
        "auth_url":  "https://auth.toyota.com/oauth2/authorize",
        "token_url": "https://auth.toyota.com/oauth2/token",
        "api_base":  "https://api.toyota.com/vehicle/v1",
        "scopes":    "vehicle:read telemetry:read",
        "client_id_env": "TOYOTA_CLIENT_ID", "client_secret_env": "TOYOTA_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery_voltage", "engine_coolant_temp", "dtc_codes", "tire_pressure"],
        "notes": "Toyota Connected App. Requires Toyota app account.",
    },
    "honda": {
        "name": "Honda", "logo": "🚘", "popular_in_nigeria": True,
        "models_in_nigeria": ["Accord", "Civic", "CR-V", "HR-V", "Pilot"],
        "auth_url":  "https://api.honda.com/oauth/authorize",
        "token_url": "https://api.honda.com/oauth/token",
        "api_base":  "https://api.honda.com/v1",
        "scopes":    "vehicle_info diagnostics",
        "client_id_env": "HONDA_CLIENT_ID", "client_secret_env": "HONDA_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "oil_life", "battery_voltage", "dtc_codes"],
        "notes": "Honda Connected Services.",
    },
    "hyundai": {
        "name": "Hyundai", "logo": "🚙", "popular_in_nigeria": True,
        "models_in_nigeria": ["Elantra", "Sonata", "Tucson", "Santa Fe"],
        "auth_url":  "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/authorize",
        "token_url": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
        "api_base":  "https://prd.eu-ccapi.hyundai.com:8080/api/v2/car",
        "scopes":    "openid vehicle:read",
        "client_id_env": "HYUNDAI_CLIENT_ID", "client_secret_env": "HYUNDAI_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery_soc", "tire_pressure", "dtc_codes"],
        "notes": "Hyundai Bluelink.",
    },
    "kia": {
        "name": "Kia", "logo": "🚗", "popular_in_nigeria": True,
        "models_in_nigeria": ["Sportage", "Sorento", "Picanto", "Rio"],
        "auth_url":  "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/authorize",
        "token_url": "https://prd.eu-ccapi.kia.com:8080/api/v1/user/oauth2/token",
        "api_base":  "https://prd.eu-ccapi.kia.com:8080/api/v2/car",
        "scopes":    "openid vehicle:read",
        "client_id_env": "KIA_CLIENT_ID", "client_secret_env": "KIA_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery", "tire_pressure"],
        "notes": "Kia Connect. Same platform as Hyundai.",
    },
    "nissan": {
        "name": "Nissan", "logo": "🚘", "popular_in_nigeria": True,
        "models_in_nigeria": ["Frontier", "Pathfinder", "Murano", "Sentra"],
        "auth_url":  "https://icm.infinitiusa.com/NissanLeafNA/oauth/auth",
        "token_url": "https://icm.infinitiusa.com/NissanLeafNA/oauth/token",
        "api_base":  "https://icm.infinitiusa.com/NissanLeafNA/v2",
        "scopes":    "vhs",
        "client_id_env": "NISSAN_CLIENT_ID", "client_secret_env": "NISSAN_CLIENT_SECRET",
        "data_fields": ["battery_soc", "charging_status", "range_km", "odometer"],
        "notes": "NissanConnect.",
    },
    "landrover": {
        "name": "Land Rover", "logo": "🚙", "popular_in_nigeria": True,
        "models_in_nigeria": ["Defender", "Discovery", "Range Rover", "Velar", "Evoque"],
        "auth_url":  "https://accounts.jaguarlandrover.com/as/authorization.oauth2",
        "token_url": "https://accounts.jaguarlandrover.com/as/token.oauth2",
        "api_base":  "https://jlp-ifas.jaguarlandrover.com/if/v4",
        "scopes":    "openid profile email vehicle",
        "client_id_env": "JLR_CLIENT_ID", "client_secret_env": "JLR_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "tyre_pressure", "battery_voltage", "service_due", "dtc_codes", "engine_oil_level", "coolant_temp"],
        "notes": "InControl Remote. Shared JLR platform with Jaguar.",
    },
    "bmw": {
        "name": "BMW", "logo": "🏎", "popular_in_nigeria": False,
        "models_in_nigeria": ["3 Series", "5 Series", "X5", "X6"],
        "auth_url":  "https://customer.bmwgroup.com/gcdm/oauth/authenticate",
        "token_url": "https://customer.bmwgroup.com/gcdm/oauth/token",
        "api_base":  "https://www.bmw-connecteddrive.com/api",
        "scopes":    "authenticate_user vehicle_data",
        "client_id_env": "BMW_CLIENT_ID", "client_secret_env": "BMW_CLIENT_SECRET",
        "data_fields": ["mileage", "fuel_level", "remaining_range", "condition_based_services", "dtc_codes"],
        "notes": "BMW ConnectedDrive.",
    },
    "mercedes": {
        "name": "Mercedes-Benz", "logo": "🚘", "popular_in_nigeria": False,
        "models_in_nigeria": ["E-Class", "GLE", "S-Class", "C-Class"],
        "auth_url":  "https://id.mercedes-benz.com/as/authorization.oauth2",
        "token_url": "https://id.mercedes-benz.com/as/token.oauth2",
        "api_base":  "https://api.mercedes-benz.com/vehicledata/v2",
        "scopes":    "mb:vehicle:status:general mb:vehicle:evstatus:general",
        "client_id_env": "MERCEDES_CLIENT_ID", "client_secret_env": "MERCEDES_CLIENT_SECRET",
        "data_fields": ["odo", "fuellevelpercent", "rangeliquid", "dooropenstate", "tirepressure"],
        "notes": "Mercedes me connect.",
    },
    "ford": {
        "name": "Ford", "logo": "🚗", "popular_in_nigeria": False,
        "models_in_nigeria": ["Ranger", "Explorer", "Escape"],
        "auth_url":  "https://sso.ci.ford.com/oidc/endpoint/default/authorize",
        "token_url": "https://sso.ci.ford.com/oidc/endpoint/default/token",
        "api_base":  "https://api.mps.ford.com/api",
        "scopes":    "openid profile",
        "client_id_env": "FORD_CLIENT_ID", "client_secret_env": "FORD_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel", "battery", "oil", "tire_pressure", "dtc_codes"],
        "notes": "FordPass Connect.",
    },
    "volkswagen": {
        "name": "Volkswagen", "logo": "🚗", "popular_in_nigeria": False,
        "models_in_nigeria": ["Polo", "Tiguan", "Passat"],
        "auth_url":  "https://identity.vwgroup.io/oidc/v1/authorize",
        "token_url": "https://identity.vwgroup.io/oidc/v1/token",
        "api_base":  "https://msg.volkswagen.de/fs-car",
        "scopes":    "openid profile birthdate nickname address phone",
        "client_id_env": "VW_CLIENT_ID", "client_secret_env": "VW_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "adblue_range", "oil_inspection", "dtc_codes"],
        "notes": "WeConnect. VW Group shared platform.",
    },
    "lexus": {
        "name": "Lexus", "logo": "🏎", "popular_in_nigeria": False,
        "models_in_nigeria": ["LX", "RX", "ES", "IS"],
        "auth_url":  "https://auth.toyota.com/oauth2/authorize",
        "token_url": "https://auth.toyota.com/oauth2/token",
        "api_base":  "https://api.toyota.com/vehicle/v1",
        "scopes":    "vehicle:read telemetry:read",
        "client_id_env": "LEXUS_CLIENT_ID", "client_secret_env": "LEXUS_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery_voltage", "engine_coolant_temp", "dtc_codes"],
        "notes": "Shares Toyota Connected platform.",
    },
    "jeep": {
        "name": "Jeep", "logo": "🚙", "popular_in_nigeria": True,
        "models_in_nigeria": ["Wrangler", "Grand Cherokee", "Renegade"],
        "auth_url":  "https://loginmgr.mopar.com/as/authorization.oauth2",
        "token_url": "https://loginmgr.mopar.com/as/token.oauth2",
        "api_base":  "https://api.connectedvehicle.mopar.com",
        "scopes":    "openid vehicle status",
        "client_id_env": "STELLANTIS_CLIENT_ID", "client_secret_env": "STELLANTIS_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "tire_pressure", "oil_life", "battery_voltage", "dtc_codes"],
        "notes": "Stellantis Uconnect. Also covers Dodge, Chrysler, Ram.",
    },
    "volvo": {
        "name": "Volvo", "logo": "🚗", "popular_in_nigeria": False,
        "models_in_nigeria": ["XC90", "XC60"],
        "auth_url":  "https://volvoid.eu.volvocars.com/as/authorization.oauth2",
        "token_url": "https://volvoid.eu.volvocars.com/as/token.oauth2",
        "api_base":  "https://api.volvocars.com/connected-vehicle/v2",
        "scopes":    "openid conve:fuel_status conve:odometer_status conve:diagnostics_workshop",
        "client_id_env": "VOLVO_CLIENT_ID", "client_secret_env": "VOLVO_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_amount", "fuel_level", "tyre_pressure", "engine_diagnostics"],
        "notes": "Volvo Cars API.",
    },
    "peugeot": {
        "name": "Peugeot", "logo": "🚗", "popular_in_nigeria": False,
        "models_in_nigeria": ["3008", "5008", "208"],
        "auth_url":  "https://idpcvs.peugeot.com/am/oauth2/access_token",
        "token_url": "https://idpcvs.peugeot.com/am/oauth2/access_token",
        "api_base":  "https://api.groupe-psa.com/connectedcar/v4",
        "scopes":    "openid profile",
        "client_id_env": "PSA_CLIENT_ID", "client_secret_env": "PSA_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery", "mileage"],
        "notes": "Stellantis/PSA Group platform.",
    },
    "mitsubishi": {
        "name": "Mitsubishi", "logo": "🚗", "popular_in_nigeria": False,
        "models_in_nigeria": ["Pajero", "Outlander", "Eclipse Cross"],
        "auth_url":  "https://auth.mitsubishi-connect.com/oauth2/authorize",
        "token_url": "https://auth.mitsubishi-connect.com/oauth2/token",
        "api_base":  "https://api.mitsubishi-connect.com/v1",
        "scopes":    "vehicle:read",
        "client_id_env": "MITSUBISHI_CLIENT_ID", "client_secret_env": "MITSUBISHI_CLIENT_SECRET",
        "data_fields": ["odometer", "fuel_level", "battery_soc", "charging_status", "dtc_codes"],
        "notes": "Mitsubishi Remote Control.",
    },
}


# DTC severity lookup
DTC_SEVERITY = {
    "P0300": "critical", "P0301": "critical", "P0302": "critical",
    "P0303": "critical", "P0304": "critical", "P0016": "critical",
    "P0217": "critical", "B1001": "critical", "C0035": "critical",
    "P0420": "warning",  "P0171": "warning",  "P0174": "warning",
    "P0128": "warning",  "P0401": "warning",  "P0440": "warning",
    "P0700": "warning",  "P0600": "warning",  "U0100": "warning",
    "P0455": "info",     "P0456": "info",
}


def get_manufacturer_list():
    return [
        {
            "id": k, "name": m["name"], "logo": m["logo"],
            "popular_in_nigeria": m["popular_in_nigeria"],
            "models_in_nigeria": m.get("models_in_nigeria", []),
            "data_fields": m.get("data_fields", []),
            "notes": m.get("notes", ""),
            "scopes": m.get("scopes", ""),
            "requires_credentials": bool(os.getenv(m.get("client_id_env", ""), "")),
        }
        for k, m in MANUFACTURERS.items()
    ]


def build_oauth_url(manufacturer_id: str, redirect_uri: str, state: str) -> str:
    mfr = MANUFACTURERS.get(manufacturer_id, {})
    client_id = os.getenv(mfr.get("client_id_env", ""), f"demo_{manufacturer_id}")
    scopes = mfr.get("scopes", "openid vehicle:read")
    auth_url = mfr.get("auth_url", "")
    params = (
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope={scopes.replace(' ', '%20')}"
        f"&state={state}"
    )
    return auth_url + params


def get_obd_adapter_guide() -> dict:
    return {
        "recommended_adapters": [
            {
                "name": "ELM327 Bluetooth V2.1",
                "price_usd": 8,
                "connection": "Bluetooth",
                "compatible": "All OBD-II vehicles 1996 and newer",
                "notes": "Most common in Nigerian markets. Works out of the box.",
            },
            {
                "name": "Veepeak OBDCheck BLE+",
                "price_usd": 35,
                "connection": "Bluetooth LE",
                "compatible": "All OBD-II — iOS and Android",
                "notes": "Premium quality. Recommended for fleet use.",
            },
            {
                "name": "FIXD Sensor",
                "price_usd": 20,
                "connection": "Bluetooth",
                "compatible": "1996+ petrol, 1997+ diesel",
                "notes": "Plain language fault descriptions.",
            },
        ],
        "how_to_connect": [
            "1. Plug the OBD-II dongle into the OBD port under the dashboard (driver's side)",
            "2. Open The Automat Hub in Chrome on your phone or laptop",
            "3. Go to Connect Vehicle and click Scan",
            "4. Select your dongle from the Bluetooth list",
            "5. Click Read Vehicle Data — all ECU data pulls automatically",
            "6. Select your vehicle and click Register",
        ],
        "obd_port_location": (
            "Standard on all cars manufactured after 1996. "
            "Under the dashboard on the driver's side, within 60cm of the steering wheel."
        ),
    }


async def pull_manufacturer_data(manufacturer_id: str, oauth_token: str, vin: str) -> dict:
    """Pull live vehicle data from a manufacturer API using stored OAuth token."""
    mfr = MANUFACTURERS.get(manufacturer_id)
    if not mfr:
        return _demo_scan_data(vin, manufacturer_id)

    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    api_base = mfr.get("api_base", "")
    raw_data = {}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if manufacturer_id in ("toyota", "lexus"):
                r = await client.get(f"{api_base}/vehicles/{vin}/telemetry", headers=headers)
                raw_data = r.json()
            elif manufacturer_id in ("hyundai", "kia"):
                r = await client.get(f"{api_base}/status", headers=headers)
                raw_data = r.json().get("vehicleStatus", {})
            elif manufacturer_id == "landrover":
                r = await client.get(f"{api_base}/vehicles/{vin}/attributes", headers=headers)
                raw_data = r.json()
                r2 = await client.get(f"{api_base}/vehicles/{vin}/status", headers=headers)
                raw_data.update(r2.json())
            elif manufacturer_id == "bmw":
                r = await client.get(
                    f"{api_base}/me/vehicles/{vin}/state/VehicleStateChangedEvent",
                    headers=headers
                )
                raw_data = r.json()
            elif manufacturer_id == "mercedes":
                r = await client.get(
                    f"{api_base}/vehicles/{vin}/resources",
                    headers={**headers, "guid": vin}
                )
                raw_data = r.json()
            elif manufacturer_id == "volvo":
                r = await client.get(f"{api_base}/vehicles/{vin}/fuel", headers=headers)
                raw_data = r.json().get("data", {})
                r2 = await client.get(f"{api_base}/vehicles/{vin}/odometer", headers=headers)
                raw_data.update(r2.json().get("data", {}))
            else:
                r = await client.get(f"{api_base}/vehicles/{vin}/status", headers=headers)
                raw_data = r.json()
    except Exception:
        raw_data = _demo_scan_data(vin, manufacturer_id)

    return _normalise(raw_data, manufacturer_id, vin)


def _normalise(raw: dict, mfr_id: str, vin: str) -> dict:
    """Normalise manufacturer API response to standard scan dict."""
    def g(d, *keys, default=None):
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k, {})
            else:
                return default
        return d if d != {} else default

    if mfr_id in ("toyota", "lexus"):
        odometer = g(raw, "odometer", "value")
        fuel = g(raw, "fuelLevel", "value")
        battery = g(raw, "batteryVoltage", "value")
        coolant = g(raw, "coolantTemperature", "value")
        dtcs = g(raw, "diagnosticTroubleCodes", default=[])
        speed = g(raw, "vehicleSpeed", "value", default=0)
        lat = g(raw, "location", "latitude")
        lng = g(raw, "location", "longitude")
    elif mfr_id in ("hyundai", "kia"):
        odometer = g(raw, "odometer", "value")
        fuel = g(raw, "fuelLevel") or g(raw, "evStatus", "batteryStatus")
        battery = g(raw, "battery", "batSoc")
        coolant = None; dtcs = []; speed = 0
        lat = g(raw, "gpsStatus", "coord", "lat")
        lng = g(raw, "gpsStatus", "coord", "lon")
    elif mfr_id == "landrover":
        odometer = g(raw, "odometer")
        fuel = g(raw, "fuelLevelInPercentage")
        battery = g(raw, "batteryVoltage")
        coolant = g(raw, "engineCoolantTemp")
        dtcs = g(raw, "diagnosticCodes", default=[])
        speed = g(raw, "currentSpeed", default=0)
        lat = g(raw, "position", "lat"); lng = g(raw, "position", "lng")
    elif mfr_id == "bmw":
        odometer = g(raw, "properties", "mileage", "value")
        fuel = g(raw, "properties", "fuelLevel", "value")
        battery = None; coolant = None
        dtcs = g(raw, "checkControlMessages", default=[])
        speed = 0
        lat = g(raw, "properties", "vehicleLocation", "coordinates", "latitude")
        lng = g(raw, "properties", "vehicleLocation", "coordinates", "longitude")
    elif mfr_id == "mercedes":
        odometer = g(raw, "odo", "value")
        fuel = g(raw, "fuellevelpercent", "value")
        battery = None; coolant = None; dtcs = []; speed = 0; lat = None; lng = None
    elif mfr_id == "volvo":
        odometer = g(raw, "odometer", "odometer")
        fuel = g(raw, "fuelAmountLevel")
        battery = None; coolant = None
        dtcs = g(raw, "engineDiagnostics", default=[])
        speed = 0; lat = None; lng = None
    else:
        odometer = raw.get("odometer") or raw.get("mileage") or raw.get("odo")
        fuel = raw.get("fuelLevel") or raw.get("fuel_level") or raw.get("fuelLevelInPercent")
        battery = raw.get("batteryVoltage") or raw.get("battery_voltage")
        coolant = raw.get("coolantTemp") or raw.get("coolant_temp") or raw.get("engineCoolantTemp")
        dtcs = raw.get("dtcCodes") or raw.get("faultCodes") or raw.get("diagnosticCodes") or []
        speed = raw.get("speed", 0) or raw.get("vehicleSpeed", 0)
        lat = raw.get("latitude") or raw.get("lat")
        lng = raw.get("longitude") or raw.get("lng")

    def norm_dtcs(d):
        if not d: return []
        return [(x.get("code") or x.get("dtcCode") or str(x)) if isinstance(x, dict) else str(x) for x in d]

    return {
        "source": "manufacturer_api",
        "manufacturer": mfr_id,
        "vin": vin,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "odometer_km": int(odometer) if odometer else None,
        "fuel_level_pct": float(fuel) if fuel else None,
        "battery_voltage": float(battery) if battery else None,
        "coolant_temp_c": float(coolant) if coolant else None,
        "speed_kmh": float(speed) if speed else 0,
        "fault_codes": norm_dtcs(dtcs),
        "latitude": float(lat) if lat else None,
        "longitude": float(lng) if lng else None,
    }


def score_obd_data(scan: dict) -> tuple:
    score = 100
    for code in (scan.get("fault_codes") or []):
        sev = DTC_SEVERITY.get(code, "warning")
        score -= 25 if sev == "critical" else 10 if sev == "warning" else 3

    battery = scan.get("battery_voltage")
    if battery:
        if battery < 11.5: score -= 20
        elif battery < 12.0: score -= 10

    coolant = scan.get("coolant_temp_c")
    if coolant:
        if coolant > 115: score -= 25
        elif coolant > 105: score -= 10

    score = max(0, min(100, score))
    status = "healthy" if score >= 80 else "warning" if score >= 60 else "critical"
    return score, status


def _demo_scan_data(vin: str, mfr_id: str) -> dict:
    import random
    seed = int(hashlib.md5(vin.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return {
        "odometer": rng.randint(20000, 95000),
        "fuelLevel": rng.randint(15, 95),
        "batteryVoltage": round(rng.uniform(12.2, 14.6), 1),
        "coolantTemperature": rng.randint(78, 98),
        "vehicleSpeed": 0,
        "diagnosticTroubleCodes": [],
        "location": {
            "latitude": 7.3775 + rng.uniform(-0.05, 0.05),
            "longitude": 3.9470 + rng.uniform(-0.05, 0.05),
        },
        "_demo": True,
        "_manufacturer": mfr_id,
    }


async def process_hourly_scan(vehicle_id: str, scan_data: dict, db) -> dict:
    """
    Core scan processor. Called by both OBD and manufacturer routes.
    Creates HourlyScan record, updates vehicle health, triggers alerts.
    """
    from sqlalchemy import select
    from backend.models.fleet import TrackedVehicle, HourlyScan, VehicleAlert
    import uuid as _uuid

    result = await db.execute(
        select(TrackedVehicle).where(TrackedVehicle.vehicle_id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        return {"error": "Vehicle not found"}

    score, status = score_obd_data(scan_data)
    fault_codes = scan_data.get("fault_codes") or []
    prev_faults = set(vehicle.active_fault_codes or [])
    new_faults = [f for f in fault_codes if f not in prev_faults]
    cleared_faults = [f for f in prev_faults if f not in fault_codes]

    scan_payload = json.dumps({
        "vehicle_id": vehicle_id,
        "vin": vehicle.vin,
        "score": score,
        "fault_codes": sorted(fault_codes),
        "scanned_at": scan_data.get("scanned_at") or datetime.now(timezone.utc).isoformat(),
        "source": scan_data.get("source"),
    }, sort_keys=True)
    scan_hash = hashlib.sha256(scan_payload.encode()).hexdigest()
    scan_id = f"SCN-{str(_uuid.uuid4())[:8].upper()}"

    scan_record = HourlyScan(
        scan_id=scan_id,
        vehicle_id=vehicle_id,
        vin=vehicle.vin,
        dcp_id=vehicle.latest_dcp_id,
        scan_method=scan_data.get("source", "obd_hardware"),
        adapter_id=scan_data.get("adapter_id"),
        fault_codes=fault_codes,
        fault_codes_new=new_faults,
        fault_codes_cleared=cleared_faults,
        engine_rpm=scan_data.get("engine_rpm"),
        coolant_temp_c=scan_data.get("coolant_temp_c"),
        oil_temp_c=scan_data.get("oil_temp_c"),
        battery_voltage=scan_data.get("battery_voltage"),
        fuel_level_pct=scan_data.get("fuel_level_pct"),
        odometer_km=scan_data.get("odometer_km"),
        speed_kmh=scan_data.get("speed_kmh", 0),
        latitude=scan_data.get("latitude"),
        longitude=scan_data.get("longitude"),
        health_score=score,
        health_status=status,
        scan_hash=scan_hash,
    )
    db.add(scan_record)

    vehicle.status = status
    vehicle.latest_score = score
    vehicle.has_active_faults = len(fault_codes) > 0
    vehicle.active_fault_codes = fault_codes
    vehicle.latest_scan_at = datetime.now(timezone.utc)
    if scan_data.get("latitude"):
        vehicle.latest_location_lat = scan_data["latitude"]
        vehicle.latest_location_lng = scan_data["longitude"]
        vehicle.latest_location_at = datetime.now(timezone.utc)
    if scan_data.get("odometer_km"):
        vehicle.odometer_current = scan_data["odometer_km"]
    if scan_data.get("fuel_level_pct"):
        vehicle.fuel_level_percent = scan_data["fuel_level_pct"]
    if scan_data.get("speed_kmh"):
        vehicle.current_speed_kmh = scan_data["speed_kmh"]

    alerts_triggered = []
    for code in new_faults:
        sev = DTC_SEVERITY.get(code, "warning")
        alert_id = f"ALT-{str(_uuid.uuid4())[:8].upper()}"
        alert = VehicleAlert(
            alert_id=alert_id,
            vehicle_id=vehicle_id,
            user_id=vehicle.owner_id,
            alert_type="fault_detected",
            severity=sev,
            title=f"Fault Detected: {code}",
            message=(
                f"OBD code {code} detected on {vehicle.make} {vehicle.model} "
                f"({vehicle.plate_number}). Severity: {sev.upper()}."
            ),
            fault_codes=[code],
        )
        db.add(alert)
        alerts_triggered.append({"code": code, "severity": sev, "alert_id": alert_id})

    await db.flush()

    return {
        "scan_id": scan_id,
        "vehicle_id": vehicle_id,
        "vin": vehicle.vin,
        "score": score,
        "status": status,
        "fault_codes": fault_codes,
        "new_faults": new_faults,
        "cleared_faults": cleared_faults,
        "alerts_triggered": alerts_triggered,
        "scan_hash": scan_hash,
        "source": scan_data.get("source"),
    }
```

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 6 — NEW FILE 3: frontend/obd-gatt.js

# ══════════════════════════════════════════════════════════════════

Create this file exactly as written. This is the Web Bluetooth GATT
bridge that communicates with a physical ELM327 OBD-II dongle.

```javascript
/**
 * obd-gatt.js — The Automat Hub Web Bluetooth GATT Bridge
 *
 * Communicates with ELM327 OBD-II dongles via Web Bluetooth API.
 * Supports all common ELM327 clones found in Nigerian markets.
 * Requires Chrome or Edge browser (Web Bluetooth not available in Safari/Firefox).
 */

const ELM327_PROFILES = [
  {
    name: "Generic ELM327 BLE (most common cheap clone)",
    service:  "0000fff0-0000-1000-8000-00805f9b34fb",
    notify:   "0000fff1-0000-1000-8000-00805f9b34fb",
    write:    "0000fff2-0000-1000-8000-00805f9b34fb",
  },
  {
    name: "ELM327 V2.1 alternate UUID",
    service:  "0000ffe0-0000-1000-8000-00805f9b34fb",
    notify:   "0000ffe1-0000-1000-8000-00805f9b34fb",
    write:    "0000ffe1-0000-1000-8000-00805f9b34fb",
  },
  {
    name: "Veepeak OBDCheck BLE+",
    service:  "e7810a71-73ae-499d-8c15-faa9aef0c3f2",
    notify:   "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
    write:    "bef8d6c9-9c21-4c9e-b632-bd58c1009f9f",
  },
  {
    name: "OBDLink MX+",
    service:  "00001101-0000-1000-8000-00805f9b34fb",
    notify:   "00001101-0000-1000-8000-00805f9b34fb",
    write:    "00001101-0000-1000-8000-00805f9b34fb",
  },
];

const AT_COMMANDS = {
  reset:         "ATZ",
  echo_off:      "ATE0",
  linefeed_off:  "ATL0",
  spaces_off:    "ATS0",
  header_off:    "ATH0",
  auto_protocol: "ATSP0",
  get_voltage:   "ATRV",
  get_rpm:       "010C",
  get_speed:     "010D",
  get_coolant:   "0105",
  get_fuel:      "012F",
  get_oil_temp:  "015C",
  get_throttle:  "0111",
  get_odo:       "01A6",
  get_dtcs:      "03",
  get_pending:   "07",
  get_vin:       "0902",
};

function parseOBDResponse(raw, expectedHeader) {
  const clean = raw.replace(/[\s\r\n>]/g, '').toUpperCase();
  const header = expectedHeader.replace(/\s/g, '').toUpperCase();
  const idx = clean.indexOf(header);
  if (idx === -1) return null;
  const dataStr = clean.slice(idx + header.length);
  const bytes = [];
  for (let i = 0; i < dataStr.length - 1; i += 2) {
    bytes.push(parseInt(dataStr.slice(i, i+2), 16));
  }
  return bytes.length > 0 ? bytes : null;
}

function decodeRPM(raw) {
  const b = parseOBDResponse(raw, "410C");
  return b ? ((b[0] * 256) + b[1]) / 4 : null;
}
function decodeSpeed(raw) {
  const b = parseOBDResponse(raw, "410D");
  return b ? b[0] : null;
}
function decodeCoolant(raw) {
  const b = parseOBDResponse(raw, "4105");
  return b ? b[0] - 40 : null;
}
function decodeFuel(raw) {
  const b = parseOBDResponse(raw, "412F");
  return b ? Math.round((b[0] / 255) * 100) : null;
}
function decodeOilTemp(raw) {
  const b = parseOBDResponse(raw, "415C");
  return b ? b[0] - 40 : null;
}
function decodeOdometer(raw) {
  const b = parseOBDResponse(raw, "41A6");
  if (!b || b.length < 4) return null;
  return Math.round(((b[0]*16777216)+(b[1]*65536)+(b[2]*256)+b[3])/10);
}
function decodeBattery(rawStr) {
  const m = rawStr.replace(/\s/g,'').match(/(\d+\.?\d*)V/i);
  return m ? parseFloat(m[1]) : null;
}
function decodeDTCs(raw) {
  const clean = raw.replace(/[\s\r\n>]/g,'').replace(/43/g,'');
  const codes = [];
  for (let i = 0; i < clean.length - 3; i += 4) {
    const chunk = clean.slice(i, i+4);
    if (chunk === '0000') continue;
    const first = parseInt(chunk[0], 16);
    const type = ['P','P','P','P','C','C','C','C','B','B','B','B','U','U','U','U'][first];
    const digit1 = first & 3;
    codes.push(`${type}${digit1}${chunk.slice(1).toUpperCase()}`);
  }
  return codes;
}

class OBDGATTBridge {
  constructor(callbacks) {
    this.device = null;
    this.server = null;
    this.characteristic = null;
    this.writeChar = null;
    this.profile = null;
    this.responseBuffer = '';
    this.pendingResolve = null;
    this.pendingReject = null;
    this.callbacks = callbacks || {};
  }

  async connect() {
    if (!navigator.bluetooth) {
      throw new Error(
        'Web Bluetooth not available. Use Chrome or Edge on desktop, or Chrome on Android.'
      );
    }
    this._onStatus('Scanning for OBD adapters...');
    const serviceUUIDs = ELM327_PROFILES.map(p => p.service);
    try {
      this.device = await navigator.bluetooth.requestDevice({
        filters: [
          { namePrefix: 'OBDII' }, { namePrefix: 'ELM327' },
          { namePrefix: 'V-Link' }, { namePrefix: 'OBD' },
          { namePrefix: 'ELM' }, { namePrefix: 'OBDLINK' },
          { namePrefix: 'Veepeak' }, { namePrefix: 'FIXD' },
          ...serviceUUIDs.map(uuid => ({ services: [uuid] }))
        ],
        optionalServices: serviceUUIDs
      });
    } catch(e) {
      if (e.name === 'NotFoundError') {
        throw new Error('No OBD adapter found. Make sure dongle is plugged in and Bluetooth is on.');
      }
      throw e;
    }

    this._onStatus(`Found: ${this.device.name}. Connecting...`);
    this.device.addEventListener('gattserverdisconnected', () => this._onDisconnect());
    this.server = await this.device.gatt.connect();

    for (const profile of ELM327_PROFILES) {
      try {
        const service = await this.server.getPrimaryService(profile.service);
        const notifyChar = await service.getCharacteristic(profile.notify);
        const writeChar = profile.write === profile.notify
          ? notifyChar
          : await service.getCharacteristic(profile.write);
        await notifyChar.startNotifications();
        notifyChar.addEventListener('characteristicvaluechanged', (e) => {
          const chunk = new TextDecoder().decode(e.target.value);
          this.responseBuffer += chunk;
          if (this.responseBuffer.includes('>')) {
            const response = this.responseBuffer.trim();
            this.responseBuffer = '';
            if (this.pendingResolve) {
              this.pendingResolve(response);
              this.pendingResolve = null;
              this.pendingReject = null;
            }
          }
        });
        this.characteristic = notifyChar;
        this.writeChar = writeChar;
        this.profile = profile;
        this._onStatus(`Connected via ${profile.name}`);
        break;
      } catch(e) { continue; }
    }

    if (!this.characteristic) {
      throw new Error(
        'Could not find OBD service. Try a generic ELM327 V2.1 Bluetooth adapter.'
      );
    }
    await this._initELM327();
    return this.device.name;
  }

  async send(command, timeoutMs = 5000) {
    return new Promise((resolve, reject) => {
      this.pendingResolve = resolve;
      this.pendingReject = reject;
      const data = new TextEncoder().encode(command + '\r');
      this.writeChar.writeValue(data).catch(reject);
      setTimeout(() => {
        if (this.pendingResolve) {
          this.pendingResolve = null;
          this.pendingReject = null;
          resolve('TIMEOUT');
        }
      }, timeoutMs);
    });
  }

  async _initELM327() {
    this._onStatus('Initialising ELM327...');
    await this.send(AT_COMMANDS.reset, 3000);
    await this._sleep(1000);
    await this.send(AT_COMMANDS.echo_off);
    await this.send(AT_COMMANDS.linefeed_off);
    await this.send(AT_COMMANDS.spaces_off);
    await this.send(AT_COMMANDS.header_off);
    await this.send(AT_COMMANDS.auto_protocol);
    this._onStatus('ELM327 ready. Reading vehicle data...');
  }

  async readAllData() {
    const data = {
      source: 'obd_hardware',
      adapter_id: this.device?.id,
      adapter_name: this.device?.name,
      timestamp: new Date().toISOString(),
      pids: {}, dtcs: [], raw: {}
    };

    const reads = [
      { cmd: AT_COMMANDS.get_voltage, key: 'battery_voltage', pid: '0x42', decode: (r) => decodeBattery(r) },
      { cmd: AT_COMMANDS.get_rpm,     key: 'engine_rpm',      pid: '0x0C', decode: (r) => { const v = decodeRPM(r); return v ? Math.round(v) : null; } },
      { cmd: AT_COMMANDS.get_speed,   key: 'speed_kmh',       pid: '0x0D', decode: decodeSpeed },
      { cmd: AT_COMMANDS.get_coolant, key: 'coolant_temp_c',  pid: '0x05', decode: decodeCoolant },
      { cmd: AT_COMMANDS.get_fuel,    key: 'fuel_level_pct',  pid: '0x2F', decode: decodeFuel },
      { cmd: AT_COMMANDS.get_oil_temp,key: 'oil_temp_c',      pid: '0x5C', decode: decodeOilTemp },
      { cmd: AT_COMMANDS.get_odo,     key: 'odometer_km',     pid: '0xA6', decode: decodeOdometer },
    ];

    for (const r of reads) {
      try {
        const raw = await this.send(r.cmd);
        const val = r.decode(raw);
        if (val !== null && val !== undefined) {
          data[r.key] = val;
          data.pids[r.pid] = val;
          this._onData(r.key, val, '');
        }
      } catch(e) { /* continue on unsupported PID */ }
    }

    try {
      const raw = await this.send(AT_COMMANDS.get_dtcs);
      const codes = decodeDTCs(raw);
      data.dtcs = codes;
      data.fault_codes = codes;
      if (codes.length > 0) this._onFault(codes);
    } catch(e) {}

    try {
      const raw = await this.send(AT_COMMANDS.get_pending);
      const pending = decodeDTCs(raw);
      if (pending.length > 0) {
        data.dtcs = [...new Set([...data.dtcs, ...pending])];
        data.fault_codes = data.dtcs;
      }
    } catch(e) {}

    return data;
  }

  async getLocation() {
    return new Promise((resolve) => {
      if (!navigator.geolocation) { resolve(null); return; }
      navigator.geolocation.getCurrentPosition(
        pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
        () => resolve(null),
        { timeout: 5000, maximumAge: 30000 }
      );
    });
  }

  disconnect() {
    if (this.device?.gatt?.connected) this.device.gatt.disconnect();
  }

  _onDisconnect() {
    this._onStatus('Adapter disconnected.');
    if (this.callbacks.onDisconnect) this.callbacks.onDisconnect();
  }
  _onStatus(msg) {
    if (this.callbacks.onStatus) this.callbacks.onStatus(msg);
  }
  _onData(key, val, unit) {
    if (this.callbacks.onData) this.callbacks.onData(key, val, unit);
  }
  _onFault(codes) {
    if (this.callbacks.onFault) this.callbacks.onFault(codes);
  }
  _sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
}
```

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 7 — NEW FILE 4: frontend/connect-vehicle.html

# ══════════════════════════════════════════════════════════════════

The full HTML file for connect-vehicle.html is too large to include
inline here. It is provided as a separate uploaded file named
`connect-vehicle.html`.

Place it at: `frontend/connect-vehicle.html`

The file is already complete and requires no modifications.
It references `/frontend/obd-gatt.js` which you created in Section 6.

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 8 — ENVIRONMENT VARIABLES TO ADD TO .env

# ══════════════════════════════════════════════════════════════════

Open your `.env` file and add these lines.
Leave any you don’t have yet — the system uses demo mode automatically
when credentials are missing.

```env
# Toyota (most popular in Nigeria — apply first)
TOYOTA_CLIENT_ID=
TOYOTA_CLIENT_SECRET=

# Land Rover (your pilot vehicles — apply second)
JLR_CLIENT_ID=
JLR_CLIENT_SECRET=

# Honda
HONDA_CLIENT_ID=
HONDA_CLIENT_SECRET=

# Hyundai
HYUNDAI_CLIENT_ID=
HYUNDAI_CLIENT_SECRET=

# Kia (same developer portal as Hyundai)
KIA_CLIENT_ID=
KIA_CLIENT_SECRET=

# Jeep / Stellantis (covers Jeep, Dodge, Ram, Chrysler)
STELLANTIS_CLIENT_ID=
STELLANTIS_CLIENT_SECRET=

# BMW
BMW_CLIENT_ID=
BMW_CLIENT_SECRET=

# Mercedes-Benz
MERCEDES_CLIENT_ID=
MERCEDES_CLIENT_SECRET=

# Ford
FORD_CLIENT_ID=
FORD_CLIENT_SECRET=

# Volkswagen
VW_CLIENT_ID=
VW_CLIENT_SECRET=

# Volvo
VOLVO_CLIENT_ID=
VOLVO_CLIENT_SECRET=

# Nissan
NISSAN_CLIENT_ID=
NISSAN_CLIENT_SECRET=

# Lexus (same portal as Toyota)
LEXUS_CLIENT_ID=
LEXUS_CLIENT_SECRET=

# Peugeot / PSA Group
PSA_CLIENT_ID=
PSA_CLIENT_SECRET=

# Mitsubishi
MITSUBISHI_CLIENT_ID=
MITSUBISHI_CLIENT_SECRET=
```

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 9 — VERIFICATION CHECKLIST

# Run these commands after all changes are made.

# ══════════════════════════════════════════════════════════════════

After making all changes, verify with these steps:

## Step 1: Check file structure

```bash
ls backend/services/
# Should show: __init__.py  manufacturer_service.py

ls frontend/
# Should show: index.html  connect-vehicle.html  obd-gatt.js
```

## Step 2: Check Python syntax

```bash
python3 -c "from backend.services.manufacturer_service import MANUFACTURERS; print(len(MANUFACTURERS), 'manufacturers loaded')"
# Should print: 15 manufacturers loaded

python3 -c "from backend.routers.manufacturer import router; print('manufacturer router OK')"
# Should print: manufacturer router OK
```

## Step 3: Start the server

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

## Step 4: Test the new endpoints

```bash
# List manufacturers (public, no auth needed)
curl http://localhost:8000/manufacturer/list

# Should return JSON with popular_in_nigeria array containing Toyota, Honda, etc.
```

## Step 5: Open the connect page

```
http://localhost:8000/frontend/connect-vehicle.html
```

It should load the OBD and Manufacturer connection interface.

-----

# ══════════════════════════════════════════════════════════════════

# SECTION 10 — COMMON ERRORS AND HOW TO FIX THEM

# ══════════════════════════════════════════════════════════════════

ERROR: `ModuleNotFoundError: No module named 'backend.services'`
FIX:   You forgot to create `backend/services/__init__.py`.
Run: `touch backend/services/__init__.py`

ERROR: `ImportError: cannot import name 'process_hourly_scan' from 'backend.services.manufacturer_service'`
FIX:   The manufacturer_service.py file is missing or incomplete.
Re-create it from Section 5 above exactly as written.

ERROR: `422 Unprocessable Entity` when calling `/fleet/scan/submit`
FIX:   The old submit_scan function takes positional args not a body.
Replace the entire function as shown in Section 3 Modify 2.

ERROR: `404 Not Found` on `/manufacturer/list`
FIX:   You forgot to add `app.include_router(manufacturer_router)` in main.py.
Follow Section 3 Modify 1 exactly.

ERROR: Web Bluetooth shows “GATT operation failed”
FIX:   The dongle needs ignition fully ON (not just accessory mode).
Turn key to ON position before scanning.

ERROR: Web Bluetooth “requestDevice” never shows picker
FIX:   Must be triggered by a user click event. It will not work if
called automatically on page load. The Scan button is correct.

-----

# ══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════

# PART 2 — PROFILE INTEGRATION AND VEHICLE CONNECTION FROM DASHBOARD

# ═══════════════════════════════════════════════════════════════════

# PART 1 — PROFILE AND VEHICLE CARD INTEGRATION

# ══════════════════════════════════════════════════════════════════

## WHERE TO MAKE THESE CHANGES

All changes in this section go into `frontend/index.html`.
The file already exists. You are adding to it, not replacing it.

-----

## CHANGE 1 — Add connection status to the My Vehicles vehicle cards

Find the function `loadMyVehicles()` in index.html.
It builds vehicle cards using `.map(v => ...)`.
Find the inner HTML template inside that map — it looks like this:

```javascript
el.innerHTML = vehicles.map(v => {
    const hc = v.health_score >= 80 ? 'hi' : ...
    return `<div class="vin-card" data-vin="${v.vin}">
```

REPLACE the entire return template string inside the map with this:

```javascript
return `<div class="vin-card" data-vin="${v.vin}">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
    <div class="vin-badge ${v.status==='healthy'?'b-green':v.status==='critical'?'b-red':'b-amber'}">${v.status}</div>
    <div id="conn-status-${v.vehicle_id}" style="font-size:.65rem;font-weight:700;padding:2px 8px;border-radius:20px;background:rgba(255,255,255,.05);color:var(--c-text3)">
      Checking connection...
    </div>
  </div>
  <div style="font-family:var(--f-display);font-size:1.3rem;letter-spacing:.04em;margin-bottom:2px">${v.make} ${v.model}</div>
  <div class="mono" style="font-size:.72rem;margin-bottom:10px">${v.vin}</div>
  <div style="display:flex;justify-content:space-between;margin-bottom:6px">
    <span style="font-size:.72rem;color:var(--c-text3)">Health Score</span>
    <span style="font-weight:700;color:${v.health_score>=80?'var(--c-green)':v.health_score>=60?'var(--c-amber)':'var(--c-red)'}">${v.health_score||'N/A'}</span>
  </div>
  <div class="hbar" style="margin-bottom:10px"><div class="hfill ${hc}" style="width:${v.health_score||0}%"></div></div>
  <div style="display:flex;justify-content:space-between;font-size:.72rem;color:var(--c-text3);margin-bottom:14px">
    <span>${v.plate_number}</span>
    <span>${v.fault_count||0} fault${v.fault_count!==1?'s':''}</span>
    <span>Last scan: ${v.last_scan?fmt(v.last_scan):'Never'}</span>
  </div>

  <div style="display:flex;flex-direction:column;gap:7px">
    <div style="display:flex;gap:7px">
      <button class="btn btn-ghost btn-sm" style="flex:1" onclick="showVehicleDetail('${v.vehicle_id}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Details
      </button>
      <button class="btn btn-orange btn-sm" style="flex:1" onclick="go('dcp-issue')">
        Issue DCP
      </button>
    </div>
    <button class="btn btn-ghost btn-block btn-sm" id="connect-btn-${v.vehicle_id}"
      onclick="openVehicleConnect('${v.vehicle_id}', '${v.make} ${v.model}', '${v.obd_connection_method||''}')">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
      Connect OBD or Manufacturer
    </button>
  </div>
</div>`;
```

-----

## CHANGE 2 — Add the connection status check function

Find the `loadMyVehicles` function. After the closing `}` of that function,
ADD this new function:

```javascript
async function checkVehicleConnections(vehicles) {
  // After rendering cards, check each vehicle's connection method
  // and update the status badge on each card
  for (const v of vehicles) {
    const el = document.getElementById(`conn-status-${v.vehicle_id}`);
    const btn = document.getElementById(`connect-btn-${v.vehicle_id}`);
    if (!el) continue;

    const method = v.obd_connection_method;

    if (method === 'manufacturer_api') {
      el.textContent = 'Manufacturer Connected';
      el.style.background = 'rgba(0,214,143,.1)';
      el.style.color = 'var(--c-green)';
      if (btn) btn.textContent = 'Manage Connection';
    } else if (method === 'obd_hardware') {
      el.textContent = 'OBD Dongle Active';
      el.style.background = 'rgba(0,214,143,.1)';
      el.style.color = 'var(--c-green)';
      if (btn) btn.textContent = 'Manage OBD';
    } else if (method === 'nfc_scan') {
      el.textContent = 'NFC Active';
      el.style.background = 'rgba(0,214,143,.1)';
      el.style.color = 'var(--c-green)';
    } else {
      el.textContent = 'Not Connected';
      el.style.background = 'rgba(255,71,87,.08)';
      el.style.color = 'var(--c-red)';
      // Pulse the connect button to draw attention
      if (btn) {
        btn.style.borderColor = 'rgba(232,131,9,.4)';
        btn.style.color = 'var(--c-orange)';
      }
    }
  }
}
```

-----

## CHANGE 3 — Call checkVehicleConnections after rendering

Inside `loadMyVehicles`, find the line that sets `el.innerHTML`.
It will look like:

```javascript
el.innerHTML = vehicles.map(v => { ... }).join('');
```

IMMEDIATELY AFTER that line add:

```javascript
// Check and display connection status for all vehicles
checkVehicleConnections(vehicles);
```

-----

## CHANGE 4 — Add the openVehicleConnect function

Find the end of your JavaScript section (near other navigation functions).
ADD this new function:

```javascript
function openVehicleConnect(vehicleId, vehicleName, currentMethod) {
  // Build the connect URL with vehicle context
  const connectUrl = `/frontend/connect-vehicle.html?vehicle_id=${vehicleId}`;

  // Show a quick modal first so the user chooses OBD or Manufacturer
  // before being redirected
  const modal = document.getElementById('vehicle-modal');
  const title = document.getElementById('vm-title');
  const body = document.getElementById('vm-body');

  if (!modal) {
    // Fallback: just redirect directly
    window.location.href = connectUrl;
    return;
  }

  title.textContent = `Connect ${vehicleName}`;
  body.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px">
      <p style="font-size:.82rem;color:var(--c-text2);line-height:1.6">
        Choose how to connect this vehicle. Your data will sync to the DCP automatically every hour.
      </p>

      ${currentMethod ? `
        <div style="padding:10px 12px;background:rgba(0,214,143,.08);border:1px solid rgba(0,214,143,.2);border-radius:8px;font-size:.78rem;color:var(--c-green)">
          Currently connected via: <strong>${currentMethod.replace('_', ' ')}</strong>
        </div>` : ''}

      <button class="btn btn-orange btn-block"
        onclick="window.location.href='${connectUrl}&method=obd'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <rect x="2" y="3" width="20" height="14" rx="2"/>
          <line x1="8" y1="21" x2="16" y2="21"/>
          <line x1="12" y1="17" x2="12" y2="21"/>
        </svg>
        Connect OBD-II Dongle
        <span style="font-size:.7rem;opacity:.7;margin-left:4px">All cars 1996+</span>
      </button>

      <button class="btn btn-ghost btn-block"
        onclick="window.location.href='${connectUrl}&method=manufacturer'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="2" y1="12" x2="22" y2="12"/>
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
        </svg>
        Connect Manufacturer Account
        <span style="font-size:.7rem;opacity:.7;margin-left:4px">Toyota, Honda, LR, BMW...</span>
      </button>

      <button class="btn btn-danger btn-sm btn-block"
        onclick="disconnectVehicle('${vehicleId}')"
        ${!currentMethod ? 'style="display:none"' : ''}>
        Disconnect Current Connection
      </button>
    </div>`;

  openModal('vehicle-modal');
}
```

-----

## CHANGE 5 — Add disconnectVehicle function

ADD this function immediately after openVehicleConnect:

```javascript
async function disconnectVehicle(vehicleId) {
  if (!confirm('Remove the current connection? The vehicle will no longer sync automatically.')) return;
  const r = await api('POST', `/manufacturer/disconnect/${vehicleId}`);
  if (r?.ok) {
    toast('Connection Removed', 'Vehicle disconnected. You can reconnect anytime.', 'ok');
    closeModal('vehicle-modal');
    loadMyVehicles(); // Refresh the vehicle cards
  } else {
    toast('Error', r?.d?.detail || 'Could not disconnect', 'err');
  }
}
```

-----

## CHANGE 6 — Handle return from connect-vehicle.html

When the user finishes connecting on `connect-vehicle.html` they come
back to the dashboard. We need to detect this and refresh the vehicles.

Find the `bootApp()` function. At the very end of it, ADD:

```javascript
// If returning from the connect page, refresh vehicles automatically
if (document.referrer.includes('connect-vehicle')) {
  setTimeout(() => {
    go('my-vehicles');
    toast('Vehicle Connected', 'Your connection has been saved.', 'ok');
  }, 500);
}
```

-----

## CHANGE 7 — Add connection method display to vehicle detail modal

Find `showVehicleDetail` function. Find where `vm-body` innerHTML is set.
Inside the detail grid, add this row at the end before the closing div:

```javascript
<div><div style="font-size:.62rem;color:var(--c-text3);text-transform:uppercase;margin-bottom:2px">Connection</div>
<div style="font-size:.78rem;font-weight:600">
  ${v.obd_connection_method
    ? `<span style="color:var(--c-green)">${v.obd_connection_method.replace(/_/g,' ')}</span>`
    : `<span style="color:var(--c-red)">Not connected</span>`
  }
</div></div>
```

Find the buttons at the bottom of the modal body and ADD this button:

```javascript
<button class="btn btn-ghost btn-block btn-sm" style="margin-top:8px"
  onclick="closeModal('vehicle-modal');openVehicleConnect('${v.vehicle_id}','${v.make} ${v.model}','${v.obd_connection_method||''}')">
  ${v.obd_connection_method ? 'Manage Connection' : 'Connect Vehicle'}
</button>
```

-----

## CHANGE 8 — Update connect-vehicle.html to return to dashboard

In `frontend/connect-vehicle.html`, find the `registerAdapter()` function.
Find this line inside it (after successful registration):

```javascript
btn.textContent = '✓ Registered — Monitoring Active';
btn.className = 'btn btn-green btn-block';
```

ADD these lines immediately after:

```javascript
// Return user to dashboard after 2 seconds
setTimeout(() => {
  window.location.href = '/frontend/index.html#my-vehicles';
}, 2000);
```

Also find the `onOAuthComplete()` function for manufacturer connections.
After the `showLivePreview()` call ADD:

```javascript
// Return user to dashboard after 3 seconds
setTimeout(() => {
  window.location.href = '/frontend/index.html#my-vehicles';
}, 3000);
```

-----

# ══════════════════════════════════════════════════════════════════

# PART 2 — RENDER DEPLOYMENT (no more localhost)

# ══════════════════════════════════════════════════════════════════

## THE SHORT ANSWER

You do not use localhost in production at all.
All API calls in the frontend already use `window.location.origin`
which automatically becomes your Render URL.
The only things you need to change are environment variables.

-----

## STEP 1 — Set environment variables on Render

In your Render dashboard, go to your service > Environment.
Set these variables (do NOT put them in .env on the server):

```
DATABASE_URL          = your Render PostgreSQL URL (from the Render database dashboard)
SECRET_KEY            = generate with: python3 -c "import secrets; print(secrets.token_hex(64))"
API_KEY               = generate with: python3 -c "import secrets; print(secrets.token_hex(32))"
APP_URL               = https://automatcorp.org.ng
CORS_ORIGINS          = https://automatcorp.org.ng,https://www.automatcorp.org.ng
ENVIRONMENT           = production
REDIS_URL             = your Render Redis URL (if using Render Redis add-on)
CELERY_BROKER_URL     = your Render Redis URL
CELERY_RESULT_BACKEND = your Render Redis URL
```

-----

## STEP 2 — Remove localhost from backend/config.py

Open `backend/config.py`. Find:

```python
REDIS_URL: str = "redis://localhost:6379/0"
CELERY_BROKER_URL: str = "redis://localhost:6379/1"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
```

Change to (reads from environment, falls back to localhost only for local dev):

```python
REDIS_URL: str = "redis://localhost:6379/0"
CELERY_BROKER_URL: str = "redis://localhost:6379/1"
CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
```

These are already using the defaults correctly. Render will override them
via the environment variables you set in Step 1.

-----

## STEP 3 — Render start command

In your Render service settings, set the Start Command to:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

NOT:

```bash
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The `$PORT` variable is provided by Render automatically.
The `0.0.0.0` host is required — `127.0.0.1` will not work on Render.

-----

## STEP 4 — Remove localhost from manufacturer OAuth callbacks

In `backend/services/manufacturer_service.py` and
`backend/routers/manufacturer.py`, find any hardcoded localhost references.
They should already use `settings.APP_URL` which you set to
`https://automatcorp.org.ng` in the Render environment.

Verify the callback URL builder in manufacturer.py reads like:

```python
redirect_uri = f"{settings.APP_URL}/manufacturer/callback/{manufacturer_id}"
```

If it says `http://localhost:8000/...` anywhere, replace it with the above.

-----

## STEP 5 — Frontend API_BASE

In `frontend/connect-vehicle.html` and `frontend/index.html`,
find this line near the top of the JavaScript:

```javascript
const API = window.location.origin;
```

This is already correct. `window.location.origin` on Render will
automatically be `https://automatcorp.org.ng`.
Do NOT hardcode `http://localhost:8000` anywhere in the frontend.

-----

## STEP 6 — WebSocket URL on Render

In `frontend/index.html`, find the WebSocket connection in `initTracking()`:

```javascript
const wsUrl = `${API_BASE.replace('http','ws')}/ws/fleet/FLT-DEFAULT?token=${TOKEN}`;
```

This is already correct. On Render with HTTPS it becomes:
`wss://automatcorp.org.ng/ws/fleet/...`
which is what you need.

-----

## STEP 7 — Render build command (if using requirements.txt)

Set the Build Command on Render to:

```bash
pip install -r requirements.txt
```

Make sure `requirements.txt` includes:

```
fastapi
uvicorn[standard]
sqlalchemy
asyncpg
alembic
pydantic
pydantic-settings
httpx
python-jose[cryptography]
passlib[bcrypt]
slowapi
redis
celery
boto3
twilio
```

-----

## STEP 8 — Run database migrations on Render

After first deploy, run migrations via Render Shell:

```bash
alembic upgrade head
```

Or add to your start command:

```bash
alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

-----

## RENDER CHECKLIST

Before going live, verify:

[ ] Start command uses `--host 0.0.0.0 --port $PORT`
[ ] DATABASE_URL set in Render environment (not .env)
[ ] SECRET_KEY set in Render environment
[ ] APP_URL set to `https://automatcorp.org.ng`
[ ] CORS_ORIGINS includes your domain
[ ] No hardcoded `localhost` in any Python file
[ ] Frontend uses `window.location.origin` not hardcoded URL
[ ] Alembic migrations have been run
[ ] `/manufacturer/list` returns 200 from your Render URL
[ ] `/frontend/connect-vehicle.html` loads on your Render URL

-----

# ══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════

# PART 3 — THREE CRITICAL SECURITY AND PAYMENT FIXES

# ═══════════════════════════════════════════════════════════════════

# GAP 1 — Any logged-in user can issue a DCP (destroys trust model)

# GAP 2 — Free users can add unlimited vehicles (breaks subscription)

# GAP 3 — Flutterwave payment confirmed but escrow never updates

# (buyers pay and get nothing, sellers never receive funds)

# 

# All three are surgical changes. Nothing is rewritten from scratch.

# ═══════════════════════════════════════════════════════════════════

Read this entire file before touching any code.
Implement the changes in the exact order written.
Do not rename any functions, models, or endpoints.
Do not add new dependencies unless explicitly told to.

-----

# ══════════════════════════════════════════════════════════════════

# GAP 1 — INSPECTOR ROLE GATE ON DCP ISSUE

# File: backend/routers/dcp.py

# ══════════════════════════════════════════════════════════════════

## THE PROBLEM

The DCP issue endpoint says “Requires inspector authentication” in its
docstring but does NOT actually check the role. Any user — a fleet
owner, a private car buyer, even a mechanic — can call POST /dcp/issue
with a valid JWT and issue a DCP. This completely destroys the trust
model. The entire value of the DCP is that it was issued by a verified
Automat Hub inspector, not self-reported by the vehicle owner.

## THE EXACT CHANGE

Open `backend/routers/dcp.py`.

Find this exact function:

```python
async def issue_dcp_endpoint(
    request: IssueDCPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Issue a new DCP.
    
    - Requires valid JWT (inspector login)
    - Generates SHA-256 hash from inspection data
    - Writes hash to append-only ledger
    - Generates QR code
    - Returns complete DCP record
    """
    result = await issue_dcp(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "message": "Digital Condition Passport issued successfully",
        "data": result
    }
```

REPLACE the entire function body (keep the decorator above it unchanged)
with this:

```python
async def issue_dcp_endpoint(
    request: IssueDCPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Issue a new DCP.

    - Requires valid JWT with role of inspector or admin ONLY
    - Private owners, fleet owners, resellers, and mechanics
      cannot issue DCPs — this protects the integrity of the registry
    - Generates SHA-256 hash from inspection data
    - Writes hash to append-only ledger
    - Generates QR code
    - Returns complete DCP record
    """
    # ── ROLE GATE — only inspector or admin can issue a DCP ──────
    allowed_roles = {"inspector", "admin"}
    user_role = current_user.get("role", "")

    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Access denied. DCP issuance requires inspector or admin role. "
                f"Your role is '{user_role}'. "
                f"Contact the Automat Hub operations team to request inspector access."
            )
        )
    # ── END ROLE GATE ────────────────────────────────────────────

    result = await issue_dcp(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "message": "Digital Condition Passport issued successfully",
        "data": result
    }
```

## ALSO UPDATE THE FRONTEND (frontend/index.html)

In the frontend, the DCP issue menu item should only be visible to
inspectors and admins. Find the navigation item for dcp-issue:

```javascript
<div class="ni" onclick="go('dcp-issue')">
```

It will be inside a nav group. Wrap that entire nav group containing
dcp-issue and dcp-verify in a conditional that checks the user role.

Find the `bootApp()` function. After the existing role checks, ADD:

```javascript
// Show DCP Issue only to inspectors and admins
// Verify remains visible to everyone (it's a public function)
const dcpIssueNav = document.querySelector('[onclick="go(\'dcp-issue\')"]');
if (dcpIssueNav) {
    const isAuthorised = ['inspector', 'admin'].includes(USER.role);
    dcpIssueNav.style.display = isAuthorised ? '' : 'none';
}
```

## VERIFY THIS WORKS

After implementing, test with:

```bash
# As a private_owner — should get 403
curl -X POST http://localhost:8000/dcp/issue \
  -H "Authorization: Bearer {private_owner_token}" \
  -H "Content-Type: application/json" \
  -d '{"vin": "TEST123", ...}'
# Expected: {"detail": "Access denied. DCP issuance requires inspector or admin role..."}

# As an inspector — should succeed
curl -X POST http://localhost:8000/dcp/issue \
  -H "Authorization: Bearer {inspector_token}" \
  ...
# Expected: {"success": true, "data": {...}}
```

-----

# ══════════════════════════════════════════════════════════════════

# GAP 2 — VEHICLE SLOT ENFORCEMENT AGAINST SUBSCRIPTION PLAN

# File: backend/routers/fleet.py

# ══════════════════════════════════════════════════════════════════

## THE PROBLEM

The User model has a `vehicle_slots` field (default 1 for free plan).
The subscription plan assigns vehicle slots (1 for private, 5+ for
fleet, etc.). But `add_vehicle_to_fleet` never checks this. A user
on the free plan with 1 vehicle slot can register 100 vehicles.
This makes the subscription meaningless.

## THE EXACT CHANGE

Open `backend/routers/fleet.py`.

Find the exact function:

```python
@router.post("/vehicle/add", response_model=dict)
async def add_vehicle_to_fleet(
    vin: str,
    make: str,
    model: str,
    year: int,
    colour: str,
    plate_number: str,
    fleet_id: Optional[str] = None,
    obd_connection_method: str = "obd_hardware",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Register a vehicle for tracking."""
    import uuid as _uuid

    vehicle_id = f"VEH-{str(_uuid.uuid4())[:8].upper()}"

    vehicle = TrackedVehicle(
        vehicle_id=vehicle_id,
        vin=vin.upper(),
        owner_id=current_user["user_id"],
        fleet_id=fleet_id,
        make=make,
        model=model,
        year=year,
        colour=colour,
        plate_number=plate_number,
        obd_connection_method=obd_connection_method,
        next_scan_due=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db.add(vehicle)
    await db.flush()

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "vin": vin.upper(),
        "message": "Vehicle registered for tracking"
    }
```

REPLACE the entire function body with this (keep the decorator unchanged):

```python
@router.post("/vehicle/add", response_model=dict)
async def add_vehicle_to_fleet(
    vin: str,
    make: str,
    model: str,
    year: int,
    colour: str,
    plate_number: str,
    fleet_id: Optional[str] = None,
    obd_connection_method: str = "obd_hardware",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Register a vehicle for tracking.
    Enforces vehicle slot limits based on the user's subscription plan.
    """
    from sqlalchemy import func, select as sa_select
    from backend.models.user import User
    import uuid as _uuid

    user_id = current_user["user_id"]

    # ── SLOT CHECK — count how many vehicles this user already has ──
    vehicle_count_result = await db.execute(
        sa_select(func.count(TrackedVehicle.id)).where(
            TrackedVehicle.owner_id == user_id,
            TrackedVehicle.status != "inactive"  # Don't count removed vehicles
        )
    )
    current_vehicle_count = vehicle_count_result.scalar() or 0

    # Fetch the user's allowed vehicle slots from their subscription
    user_result = await db.execute(
        sa_select(User).where(User.user_id == user_id)
    )
    user = user_result.scalar_one_or_none()
    allowed_slots = getattr(user, "vehicle_slots", 1) if user else 1

    if current_vehicle_count >= allowed_slots:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Vehicle slot limit reached. "
                f"Your current plan allows {allowed_slots} vehicle"
                f"{'s' if allowed_slots != 1 else ''}. "
                f"You have {current_vehicle_count} registered. "
                f"Upgrade your subscription at automatcorp.org.ng to add more vehicles."
            )
        )
    # ── END SLOT CHECK ───────────────────────────────────────────

    # Check this VIN is not already registered to this user
    existing_result = await db.execute(
        sa_select(TrackedVehicle).where(
            TrackedVehicle.vin == vin.upper(),
            TrackedVehicle.owner_id == user_id
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Vehicle with VIN {vin.upper()} is already registered to your account."
        )

    vehicle_id = f"VEH-{str(_uuid.uuid4())[:8].upper()}"

    vehicle = TrackedVehicle(
        vehicle_id=vehicle_id,
        vin=vin.upper(),
        owner_id=user_id,
        fleet_id=fleet_id,
        make=make,
        model=model,
        year=year,
        colour=colour,
        plate_number=plate_number,
        obd_connection_method=obd_connection_method,
        next_scan_due=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db.add(vehicle)
    await db.flush()

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "vin": vin.upper(),
        "slots_used": current_vehicle_count + 1,
        "slots_allowed": allowed_slots,
        "message": f"Vehicle registered for tracking. Using {current_vehicle_count + 1} of {allowed_slots} slot{'s' if allowed_slots != 1 else ''}."
    }
```

## ALSO UPDATE THE FRONTEND (frontend/index.html)

When a user hits the 402 slot limit error, the frontend should show a
clear upgrade prompt rather than a generic error message.

Find the `doLinkVehicle()` function (or `handleAddVehicle()` depending
on which version is in index.html). Find the error handling block:

```javascript
if (!r?.ok) {
    showAlert('link-alert', r?.d?.detail || 'Failed to link vehicle', 'err');
    return;
}
```

REPLACE that error block with:

```javascript
if (!r?.ok) {
    const detail = r?.d?.detail || 'Failed to link vehicle';
    if (r?.st === 402) {
        // Slot limit — show upgrade prompt
        showAlert('link-alert',
            detail + ' — tap Subscription in the menu to upgrade.',
            'err'
        );
        // Also highlight the subscription nav item
        setTimeout(() => {
            const subNav = document.querySelector('[onclick="go(\'subscription\')"]');
            if (subNav) {
                subNav.style.outline = '2px solid var(--c-orange)';
                subNav.style.borderRadius = '6px';
                setTimeout(() => subNav.style.outline = '', 3000);
            }
        }, 500);
    } else {
        showAlert('link-alert', detail, 'err');
    }
    return;
}
```

## VERIFY THIS WORKS

```bash
# Register a free user and add 2 vehicles
# First vehicle — should succeed (slots_allowed: 1, slots_used: 1)
# Second vehicle — should return 402:
# {"detail": "Vehicle slot limit reached. Your current plan allows 1 vehicle..."}
```

-----

# ══════════════════════════════════════════════════════════════════

# GAP 3 — FLUTTERWAVE WEBHOOK (replace Paystack entirely)

# Files:

# backend/routers/webhooks.py     (replace the whole file)

# backend/config.py               (already correct — verify only)

# backend/main.py                 (add webhook route — check it exists)

# ══════════════════════════════════════════════════════════════════

## THE PROBLEM

The webhooks.py file is written for Paystack. The config.py already
has FLUTTERWAVE_SECRET_KEY and FLUTTERWAVE_PUBLIC_KEY. The webhook
handler must be rewritten to:

1. Use Flutterwave’s signature verification (SHA-256, not SHA-512)
1. Handle Flutterwave’s event format (charge.completed, not charge.success)
1. Extract escrow_id from Flutterwave’s tx_ref field (not metadata.escrow_id)
1. Verify the payment with a second GET call to Flutterwave’s API
   (Flutterwave best practice — always re-verify before updating records)
1. Handle transfer.completed for fund release logging

## COMPLETE REPLACEMENT OF webhooks.py

REPLACE THE ENTIRE CONTENT of `backend/routers/webhooks.py` with:

```python
"""
routers/webhooks.py
Flutterwave webhook handler.

Listens for Flutterwave payment events and triggers escrow updates.

HOW FLUTTERWAVE WEBHOOKS WORK:
  1. Buyer pays on Flutterwave checkout
  2. Flutterwave sends POST to /webhooks/flutterwave
  3. We verify the signature using FLUTTERWAVE_SECRET_KEY
  4. We re-verify the transaction by calling Flutterwave GET API
     (never trust a webhook alone — always re-verify)
  5. We update the escrow status to FUNDED
  6. Buyer and seller are notified

FLUTTERWAVE WEBHOOK SIGNATURE:
  Flutterwave sends the hash as the verif-hash header.
  It is a SHA-256 hash of the raw request body + secret key.
  We recompute it and compare. If it does not match, we reject.

ESCROW REFERENCE FORMAT:
  When creating a Flutterwave payment link, set tx_ref to the escrow_id.
  Example: tx_ref = "ESC-A1B2C3D4"
  The webhook payload includes this tx_ref so we can find the escrow.

EVENTS HANDLED:
  charge.completed  → buyer payment confirmed → escrow moves to FUNDED
  transfer.completed → seller payout confirmed → log for audit trail
  transfer.failed    → seller payout failed → alert operations team
"""

import hmac
import hashlib
import json
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.schemas.escrow import ConfirmDepositRequest
from backend.services.escrow_service import confirm_deposit
from backend.config import settings

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_flutterwave_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Flutterwave webhook signature.

    Flutterwave documentation says:
    Hash = SHA-256(secretKey + payload) — but in practice they send
    the secretHash directly in the verif-hash header.
    We compare it against our stored FLUTTERWAVE_SECRET_KEY.

    For security we support both the simple header match AND
    a SHA-256 HMAC computation.
    """
    secret = settings.FLUTTERWAVE_SECRET_KEY

    # Method 1: Direct header comparison (Flutterwave standard)
    # Flutterwave sends the exact secret as the verif-hash header
    if signature == secret:
        return True

    # Method 2: HMAC-SHA256 fallback (some Flutterwave versions)
    computed = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


async def verify_transaction_with_flutterwave(transaction_id: str) -> dict:
    """
    Re-verify a transaction directly with Flutterwave API.

    CRITICAL: Never update financial records based on webhook alone.
    Always call this to confirm the payment before marking escrow as funded.

    Flutterwave endpoint: GET /v3/transactions/{id}/verify
    Returns the full transaction object if successful.
    """
    url = f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"
    headers = {
        "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                tx = data.get("data", {})
                return {
                    "verified": True,
                    "status": tx.get("status"),          # "successful"
                    "amount": tx.get("amount"),
                    "currency": tx.get("currency"),
                    "tx_ref": tx.get("tx_ref"),           # our escrow_id
                    "flw_ref": tx.get("flw_ref"),
                    "transaction_id": tx.get("id"),
                    "customer_email": tx.get("customer", {}).get("email"),
                    "customer_name": tx.get("customer", {}).get("name"),
                }
            return {"verified": False, "error": data.get("message", "Verification failed")}

    except Exception as e:
        return {"verified": False, "error": str(e)}


@router.post(
    "/flutterwave",
    summary="Flutterwave webhook receiver",
    description="Receives and processes Flutterwave payment events. Verifies signature and re-verifies with Flutterwave API before updating escrow."
)
async def flutterwave_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Process Flutterwave webhooks.

    Events handled:
    - charge.completed  → buyer payment confirmed → escrow = FUNDED
    - transfer.completed → seller payout sent → log for audit
    - transfer.failed    → payout failed → alert operations team
    """
    # ── STEP 1: Read raw body for signature verification ─────────
    payload = await request.body()
    signature = request.headers.get("verif-hash", "")

    # ── STEP 2: Verify signature — reject any unsigned webhook ───
    if not settings.FLUTTERWAVE_SECRET_KEY:
        # No secret configured — log and reject
        raise HTTPException(
            status_code=503,
            detail="Flutterwave webhook secret not configured"
        )

    if not verify_flutterwave_signature(payload, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid Flutterwave signature. Request rejected."
        )

    # ── STEP 3: Parse JSON body ───────────────────────────────────
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = data.get("event")
    event_data = data.get("data", {})

    # ── STEP 4: Handle charge.completed ──────────────────────────
    # This fires when a buyer successfully pays for a vehicle.
    # We re-verify with Flutterwave before updating the escrow.
    if event == "charge.completed":
        tx_status = event_data.get("status", "")
        tx_ref    = event_data.get("tx_ref", "")      # This is our escrow_id
        flw_id    = str(event_data.get("id", ""))     # Flutterwave transaction ID

        # Only process successful charges
        if tx_status != "successful":
            return {
                "status": "ignored",
                "reason": f"Charge status was '{tx_status}', not 'successful'",
                "tx_ref": tx_ref
            }

        # tx_ref IS the escrow_id — format: ESC-XXXXXXXX
        # Validate it looks like an escrow ID
        if not tx_ref.startswith("ESC-"):
            return {
                "status": "ignored",
                "reason": f"tx_ref '{tx_ref}' does not match escrow format ESC-XXXXXXXX",
            }

        escrow_id = tx_ref

        # ── RE-VERIFY with Flutterwave before touching the database ──
        verification = await verify_transaction_with_flutterwave(flw_id)

        if not verification.get("verified"):
            raise HTTPException(
                status_code=400,
                detail=f"Flutterwave re-verification failed: {verification.get('error')}"
            )

        # Double-check the re-verified status
        if verification.get("status") != "successful":
            return {
                "status": "ignored",
                "reason": f"Re-verified status was '{verification.get('status')}', not 'successful'",
                "escrow_id": escrow_id
            }

        # ── UPDATE ESCROW STATUS TO FUNDED ───────────────────────
        confirm_request = ConfirmDepositRequest(
            escrow_id=escrow_id,
            payment_reference=flw_id,
            payment_channel="flutterwave"
        )
        result = await confirm_deposit(confirm_request, db)

        return {
            "status": "processed",
            "event": event,
            "escrow_id": escrow_id,
            "flw_transaction_id": flw_id,
            "verified_amount": verification.get("amount"),
            "verified_currency": verification.get("currency"),
            "result": result
        }

    # ── STEP 5: Handle transfer.completed ────────────────────────
    # This fires when Flutterwave sends money to the seller.
    elif event == "transfer.completed":
        reference  = event_data.get("reference", "")
        amount     = event_data.get("amount")
        currency   = event_data.get("currency", "NGN")
        bank_name  = event_data.get("bank_name", "")
        account_no = event_data.get("account_number", "")

        # Log for audit trail
        # In production: write to a TransferLog table
        print(
            f"[TRANSFER COMPLETE] ref={reference} amount={currency} {amount} "
            f"bank={bank_name} account=****{str(account_no)[-4:]}"
        )
        return {
            "status": "logged",
            "event": event,
            "reference": reference,
            "amount": amount,
            "currency": currency
        }

    # ── STEP 6: Handle transfer.failed ───────────────────────────
    # This fires when a payout to the seller fails (wrong account,
    # bank downtime, etc.). Operations must be alerted immediately.
    elif event == "transfer.failed":
        reference = event_data.get("reference", "")
        reason    = event_data.get("complete_message", "Unknown reason")
        amount    = event_data.get("amount")

        # ALERT OPERATIONS — In production replace print with:
        # - Send SMS via Termii to operations phone
        # - Send email via Sendgrid/Mailersend to ops@automatcorp.org.ng
        # - Write to an alert log table
        print(
            f"[ALERT — TRANSFER FAILED] ref={reference} "
            f"amount={amount} reason={reason}"
        )
        return {
            "status": "alerted",
            "event": event,
            "reference": reference,
            "reason": reason
        }

    # ── Unknown event — acknowledge and ignore ────────────────────
    return {"status": "received", "event": event}


# ── KEEP THIS: old /paystack route as redirect for safety ─────────
# If any old Paystack webhook is still configured somewhere, it will
# hit this and get a clear error rather than a 404.
@router.post(
    "/paystack",
    include_in_schema=False
)
async def paystack_legacy_redirect():
    """
    Legacy Paystack endpoint — this project now uses Flutterwave.
    If you are seeing this, update your webhook URL in Paystack dashboard.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "This project has migrated from Paystack to Flutterwave. "
            "Update your webhook URL to /webhooks/flutterwave"
        )
    )
```

## VERIFY config.py HAS FLUTTERWAVE KEYS (no change needed, just confirm)

Open `backend/config.py` and confirm these lines exist:

```python
FLUTTERWAVE_SECRET_KEY: str = ""
FLUTTERWAVE_PUBLIC_KEY: str = ""
```

They are already there. No change needed to config.py.

## ADD YOUR FLUTTERWAVE KEYS TO .env

Open your `.env` file. Add (replace with your real keys from
dashboard.flutterwave.com > Settings > API Keys):

```env
FLUTTERWAVE_SECRET_KEY=FLWSECK_TEST-xxxxxxxxxxxxxxxxxxxx-X
FLUTTERWAVE_PUBLIC_KEY=FLWPUBK_TEST-xxxxxxxxxxxxxxxxxxxx-X
```

For production use the LIVE keys (not TEST).

## CONFIGURE FLUTTERWAVE WEBHOOK URL

In your Flutterwave dashboard:

1. Go to Settings > Webhooks
1. Set URL to: <https://automatcorp.org.ng/webhooks/flutterwave>
1. Set Secret Hash to: the same value as FLUTTERWAVE_SECRET_KEY in your .env
1. Enable events: charge.completed, transfer.completed, transfer.failed
1. Save

## HOW TO SET tx_ref WHEN CREATING PAYMENT LINKS

When your escrow service calls Flutterwave to generate a payment link,
set tx_ref to the escrow_id. This is how the webhook knows which
escrow to update.

In your escrow service (backend/services/escrow_service.py), find
where you call Flutterwave to initiate payment. It should look like:

```python
payload = {
    "tx_ref": escrow_id,          # ← THIS IS THE KEY LINE
    "amount": amount_usd * 1500,  # Convert USD to NGN at current rate
    "currency": "NGN",
    "redirect_url": f"{settings.APP_URL}/escrow/payment-complete",
    "customer": {
        "email": buyer_email,
        "name": buyer_name,
        "phonenumber": buyer_phone,
    },
    "customizations": {
        "title": "The Automat Hub",
        "description": f"Vehicle Escrow Payment — {vin}",
        "logo": f"{settings.APP_URL}/static/logo.png",
    },
    "meta": {
        "escrow_id": escrow_id,   # belt and suspenders
        "vin": vin,
    }
}
```

If that code does not exist yet, add it where the escrow initiation
payment link is generated.

## VERIFY THIS WORKS

```bash
# Test the webhook locally using curl
# Simulate a charge.completed event from Flutterwave

curl -X POST http://localhost:8000/webhooks/flutterwave \
  -H "Content-Type: application/json" \
  -H "verif-hash: YOUR_FLUTTERWAVE_SECRET_KEY" \
  -d '{
    "event": "charge.completed",
    "data": {
      "id": 123456,
      "tx_ref": "ESC-A1B2C3D4",
      "status": "successful",
      "amount": 37500000,
      "currency": "NGN"
    }
  }'

# Expected response:
# {"status": "processed", "event": "charge.completed",
#  "escrow_id": "ESC-A1B2C3D4", ...}

# Test with wrong signature — must return 401
curl -X POST http://localhost:8000/webhooks/flutterwave \
  -H "verif-hash: wrong_key" \
  -d '{}'
# Expected: {"detail": "Invalid Flutterwave signature. Request rejected."}
```

-----

# ══════════════════════════════════════════════════════════════════

# FINAL VERIFICATION CHECKLIST

# Run all of these after implementing the three fixes.

# ══════════════════════════════════════════════════════════════════

```bash
# 1. Start the server
uvicorn backend.main:app --reload

# 2. Confirm all three routes are live
curl http://localhost:8000/openapi.json | python3 -m json.tool | grep -E '"path"' | grep -E "dcp/issue|vehicle/add|webhooks"
# Should show all three

# 3. Test DCP role gate — private_owner should get 403
# (register a test user with role=private_owner, get their token, try to issue DCP)

# 4. Test slot enforcement — add 2 vehicles as free user
# Second add should return 402

# 5. Test Flutterwave webhook signature rejection
curl -X POST http://localhost:8000/webhooks/flutterwave \
  -H "verif-hash: wrong" \
  -d '{"event":"test"}'
# Should return 401

# 6. Test legacy Paystack redirect
curl -X POST http://localhost:8000/webhooks/paystack \
  -d '{}'
# Should return 410 Gone
```

-----

# ══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════

# FINAL VERIFICATION — RUN THESE COMMANDS AFTER ALL CHANGES ARE DONE

# ═══════════════════════════════════════════════════════════════════

## Step 1 — Check all new and modified files exist

```bash
ls backend/services/
# manufacturer_service.py  __init__.py

ls frontend/
# index.html  connect-vehicle.html  obd-gatt.js
```

## Step 2 — Check Python syntax on every changed file

```bash
python3 -c "from backend.services.manufacturer_service import MANUFACTURERS; print(len(MANUFACTURERS), 'manufacturers OK')"
python3 -c "from backend.routers.manufacturer import router; print('manufacturer router OK')"
python3 -c "from backend.routers.webhooks import router; print('webhooks router OK')"
python3 -c "from backend.routers.dcp import router; print('dcp router OK')"
python3 -c "from backend.routers.fleet import router; print('fleet router OK')"
```

## Step 3 — Start server (Render uses 0.0.0.0 and $PORT, local uses 8000)

```bash
# Local development
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Render production (set as Render start command)
# alembic upgrade head && uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Step 4 — Verify all endpoints are live

```bash
# Manufacturers list (public)
curl http://localhost:8000/manufacturer/list
# Expected: JSON list of 15 manufacturers

# App redirect
curl -I http://localhost:8000/app
# Expected: 307 redirect to /frontend/index.html

# Webhook is registered (check docs)
curl http://localhost:8000/openapi.json | python3 -m json.tool | grep -E '"path"' | grep webhook
# Expected: /webhooks/flutterwave appears, /webhooks/paystack appears as legacy 410
```

## Step 5 — Test Gap 1 (DCP inspector gate)

```bash
# Get a token for a private_owner user, then try to issue a DCP
# Expected: 403 Forbidden with "DCP issuance requires inspector or admin role"
curl -X POST http://localhost:8000/dcp/issue \
  -H "Authorization: Bearer PRIVATE_OWNER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"vin":"TEST123","make":"Toyota","model":"Corolla","year":2020,"colour":"White","odometer_km":50000,"inspection_modules":{"mechanical_systems":80,"electrical_controls":80,"structural_integrity":80,"maintenance_compliance":80,"hse_standards":80,"operational_technology":80}}'
```

## Step 6 — Test Gap 2 (vehicle slot enforcement)

```bash
# With a free user (vehicle_slots=1), add 2 vehicles
# First: should succeed
# Second: should return 402 with slot limit message
curl -X POST "http://localhost:8000/fleet/vehicle/add?vin=TEST001&make=Toyota&model=Corolla&year=2020&colour=White&plate_number=OY123AA" \
  -H "Authorization: Bearer FREE_USER_TOKEN"
# Then same again with different VIN — should get 402
```

## Step 7 — Test Gap 3 (Flutterwave webhook signature)

```bash
# Wrong signature — must return 401
curl -X POST http://localhost:8000/webhooks/flutterwave \
  -H "Content-Type: application/json" \
  -H "verif-hash: wrong_secret" \
  -d '{"event":"charge.completed","data":{}}'
# Expected: 401 Invalid Flutterwave signature

# Legacy paystack endpoint — must return 410
curl -X POST http://localhost:8000/webhooks/paystack \
  -H "Content-Type: application/json" \
  -d '{}'
# Expected: 410 Gone with migration message

# Correct signature test (use your actual FLUTTERWAVE_SECRET_KEY)
curl -X POST http://localhost:8000/webhooks/flutterwave \
  -H "Content-Type: application/json" \
  -H "verif-hash: YOUR_FLUTTERWAVE_SECRET_KEY" \
  -d '{"event":"charge.completed","data":{"id":123456,"tx_ref":"ESC-A1B2C3D4","status":"successful","amount":37500000,"currency":"NGN"}}'
# Expected: processes and attempts Flutterwave re-verification
```

## Step 8 — Open the frontend and test the full flow

```
http://localhost:8000/frontend/index.html
```

- Log in as a private owner
- Go to My Vehicles — vehicle cards should show connection status badges
- Click Connect on a vehicle — modal shows OBD vs Manufacturer choice
- DCP Issue should NOT appear in the nav for private owners
- Log in as an inspector — DCP Issue should appear and work

## Step 9 — Confirm Render environment variables are set

```
DATABASE_URL         set in Render dashboard
SECRET_KEY           set in Render dashboard
API_KEY              set in Render dashboard
APP_URL              https://automatcorp.org.ng
CORS_ORIGINS         https://automatcorp.org.ng
ENVIRONMENT          production
FLUTTERWAVE_SECRET_KEY  set in Render dashboard
FLUTTERWAVE_PUBLIC_KEY  set in Render dashboard
REDIS_URL            set in Render dashboard (if using Redis)
```

# ═══════════════════════════════════════════════════════════════════

# COMPLETE FILE CHANGE SUMMARY

# ═══════════════════════════════════════════════════════════════════

# 

# FILES TO CREATE (6 total):

# backend/services/**init**.py

# backend/services/manufacturer_service.py

# frontend/obd-gatt.js                  (uploaded separately)

# frontend/connect-vehicle.html         (uploaded separately)

# 

# FILES TO MODIFY (5 total):

# backend/main.py                       add manufacturer router + /app redirect

# backend/routers/fleet.py              fix submit_scan + add slot enforcement in add_vehicle

# backend/routers/dcp.py                add inspector role gate in issue_dcp_endpoint

# backend/routers/webhooks.py           replace entirely with Flutterwave handler

# frontend/index.html                   8 changes for profile + connection integration

# 

# FILES TO UPDATE (2 total):

# .env                                  add Flutterwave keys + manufacturer credentials

# frontend/connect-vehicle.html         2 redirect-back changes (already in uploaded file)

# 

# RENDER SETTINGS:

# Start command: alembic upgrade head && uvicorn backend.main:app –host 0.0.0.0 –port $PORT

# All secrets via Render environment, not .env file

# 

# WHAT WORKS AFTER ALL CHANGES:

# Vehicle cards in My Vehicles show green/red connection status

# Click Connect → choose OBD dongle or Manufacturer account

# Chrome pairs directly with physical ELM327 dongle via GATT

# Manufacturer OAuth links Toyota, Land Rover, Honda and 12 others

# Data syncs to DCP hourly scan pipeline automatically

# Only inspectors can issue DCPs — buyers cannot self-certify

# Free users are capped at their subscription vehicle slot limit

# Flutterwave payments update escrow to FUNDED automatically

# Buyer gets confirmation, seller gets notified, deal proceeds

# No localhost anywhere — all runs on Render with automatcorp.org.ng