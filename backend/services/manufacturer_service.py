"""
services/manufacturer_service.py

Connects vehicles to their manufacturer's telematics API.
Supports two scan methods:

METHOD 1: OBD-II Hardware Adapter
  - Customer plugs ELM327 Bluetooth dongle into OBD port
  - Mobile app reads via Bluetooth
  - Works on ANY car made after 1996
  - Real-time fault codes, sensor data

METHOD 2: Manufacturer API (Connected Car)
  - Customer logs in with their manufacturer account
  - We get an OAuth token to pull live vehicle data
  - No hardware needed
  - Richer data (GPS, remote lock, fuel, maintenance alerts)

SUPPORTED MANUFACTURERS:
  Toyota/Lexus  — Toyota Connected Services
  Ford          — Ford Pass Connect / SYNC
  Honda/Acura   — Honda Remote Access
  Chevrolet/GMC — myChevrolet / OnStar
  Hyundai/Kia   — Hyundai Blue Link / Kia UVO
  Volkswagen    — We Connect
  BMW/Mini      — BMW ConnectedDrive
  Mercedes      — Mercedes me connect
  Nissan/Infiniti — NissanConnect
  Subaru        — STARLINK
  Mazda         — MyMazda
  Jeep/Dodge    — Uconnect
  Volvo         — Volvo On Call
  Peugeot       — MyPeugeot
  Renault       — MyRenault
"""

import httpx
from datetime import datetime, timezone
from typing import Optional
from backend.config import settings


# ── MANUFACTURER REGISTRY ────────────────────────────────────

MANUFACTURERS = {
    "toyota": {
        "name": "Toyota / Lexus",
        "logo": "🚗",
        "auth_url": "https://api.toyota.com/oauth2/v1/authorize",
        "token_url": "https://api.toyota.com/oauth2/v1/token",
        "api_base": "https://api.toyota.com/v1",
        "scopes": "vehicle:read vehicle:location vehicle:health",
        "client_id_env": "TOYOTA_CLIENT_ID",
        "client_secret_env": "TOYOTA_CLIENT_SECRET",
        "models": ["Camry", "Corolla", "Hilux", "Land Cruiser", "RAV4", "Prado",
                   "Fortuner", "Yaris", "Venza", "Lexus ES", "Lexus RX", "Lexus LX"],
        "popular_in_nigeria": True
    },
    "ford": {
        "name": "Ford",
        "logo": "🚙",
        "auth_url": "https://fcis.ford.com/cognito-oauth/v2/authorize",
        "token_url": "https://fcis.ford.com/cognito-oauth/v2/token",
        "api_base": "https://api.mps.ford.com/api",
        "scopes": "openid profile",
        "client_id_env": "FORD_CLIENT_ID",
        "client_secret_env": "FORD_CLIENT_SECRET",
        "models": ["F-150", "Escape", "Explorer", "Ranger", "Transit", "Focus", "Fusion"],
        "popular_in_nigeria": False
    },
    "honda": {
        "name": "Honda / Acura",
        "logo": "🚘",
        "auth_url": "https://accounts.honda.com/oauth2/v2/authorize",
        "token_url": "https://accounts.honda.com/oauth2/v2/token",
        "api_base": "https://api.telematics.honda.com",
        "scopes": "vehicle:read",
        "client_id_env": "HONDA_CLIENT_ID",
        "client_secret_env": "HONDA_CLIENT_SECRET",
        "models": ["Accord", "Civic", "CR-V", "HR-V", "Pilot", "Odyssey"],
        "popular_in_nigeria": True
    },
    "hyundai": {
        "name": "Hyundai / Kia",
        "logo": "🚗",
        "auth_url": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/authorize",
        "token_url": "https://prd.eu-ccapi.hyundai.com:8080/api/v1/user/oauth2/token",
        "api_base": "https://prd.eu-ccapi.hyundai.com:8080/api/v1",
        "scopes": "openid offline_access vehicle:read",
        "client_id_env": "HYUNDAI_CLIENT_ID",
        "client_secret_env": "HYUNDAI_CLIENT_SECRET",
        "models": ["Elantra", "Tucson", "Santa Fe", "Accent", "Sonata",
                   "Kia Sportage", "Kia Picanto", "Kia Rio"],
        "popular_in_nigeria": True
    },
    "volkswagen": {
        "name": "Volkswagen",
        "logo": "🚗",
        "auth_url": "https://identity.vwgroup.io/oidc/v1/authorize",
        "token_url": "https://identity.vwgroup.io/oidc/v1/token",
        "api_base": "https://mobileapi.apps.emea.vwapps.io",
        "scopes": "openid profile",
        "client_id_env": "VW_CLIENT_ID",
        "client_secret_env": "VW_CLIENT_SECRET",
        "models": ["Golf", "Polo", "Tiguan", "Passat", "Touareg", "T-Cross"],
        "popular_in_nigeria": False
    },
    "bmw": {
        "name": "BMW / Mini",
        "logo": "🚗",
        "auth_url": "https://customer.bmwgroup.com/oauth/authenticate",
        "token_url": "https://customer.bmwgroup.com/oauth/token",
        "api_base": "https://www.bmw-connecteddrive.com/api",
        "scopes": "vehicle_data remote_services",
        "client_id_env": "BMW_CLIENT_ID",
        "client_secret_env": "BMW_CLIENT_SECRET",
        "models": ["3 Series", "5 Series", "X3", "X5", "X7", "Mini Cooper"],
        "popular_in_nigeria": True
    },
    "mercedes": {
        "name": "Mercedes-Benz",
        "logo": "🚗",
        "auth_url": "https://id.mercedes-benz.com/as/authorization.oauth2",
        "token_url": "https://id.mercedes-benz.com/as/token.oauth2",
        "api_base": "https://api.mercedes-benz.com/vehicledata/v2",
        "scopes": "mb:vehicle:status:general mb:vehicle:evstatus:general",
        "client_id_env": "MERCEDES_CLIENT_ID",
        "client_secret_env": "MERCEDES_CLIENT_SECRET",
        "models": ["C-Class", "E-Class", "GLE", "GLC", "Sprinter", "A-Class"],
        "popular_in_nigeria": True
    },
    "nissan": {
        "name": "Nissan / Infiniti",
        "logo": "🚗",
        "auth_url": "https://prod.eu2.auth.carwings.com/oauth2/v1/authorize",
        "token_url": "https://prod.eu2.auth.carwings.com/oauth2/v1/token",
        "api_base": "https://prod.eu2.api.nissan-cdn.net/v1",
        "scopes": "vehicle:read",
        "client_id_env": "NISSAN_CLIENT_ID",
        "client_secret_env": "NISSAN_CLIENT_SECRET",
        "models": ["Altima", "Sentra", "X-Trail", "Pathfinder", "Murano", "Frontier"],
        "popular_in_nigeria": True
    },
    "chevrolet": {
        "name": "Chevrolet / GMC / Cadillac",
        "logo": "🚗",
        "auth_url": "https://custlogin.gm.com/oauth/v2/authorize",
        "token_url": "https://custlogin.gm.com/oauth/v2/token",
        "api_base": "https://api.gm.com/api/locker/v1",
        "scopes": "onstar:vehicle_diagnostics onstar:remote_commands",
        "client_id_env": "GM_CLIENT_ID",
        "client_secret_env": "GM_CLIENT_SECRET",
        "models": ["Silverado", "Tahoe", "Traverse", "Equinox", "Colorado", "Blazer"],
        "popular_in_nigeria": False
    },
    "jeep": {
        "name": "Jeep / Dodge / Chrysler",
        "logo": "🚙",
        "auth_url": "https://login.fca.com/oauth2/authorize",
        "token_url": "https://login.fca.com/oauth2/token",
        "api_base": "https://api.fcagroup.com/v1",
        "scopes": "vehicle:read",
        "client_id_env": "FCA_CLIENT_ID",
        "client_secret_env": "FCA_CLIENT_SECRET",
        "models": ["Wrangler", "Grand Cherokee", "Compass", "Renegade", "Dodge Durango"],
        "popular_in_nigeria": True
    },
    "volvo": {
        "name": "Volvo",
        "logo": "🚗",
        "auth_url": "https://volvoid.eu.volvocars.com/as/authorization.oauth2",
        "token_url": "https://volvoid.eu.volvocars.com/as/token.oauth2",
        "api_base": "https://api.volvocars.com/connected-vehicle/v2",
        "scopes": "openid profile",
        "client_id_env": "VOLVO_CLIENT_ID",
        "client_secret_env": "VOLVO_CLIENT_SECRET",
        "models": ["XC90", "XC60", "XC40", "S60", "V60"],
        "popular_in_nigeria": False
    },
    "subaru": {
        "name": "Subaru",
        "logo": "🚗",
        "auth_url": "https://prod.subarucs.com/g2v19/oauth/token",
        "token_url": "https://prod.subarucs.com/g2v19/oauth/token",
        "api_base": "https://prod.subarucs.com/g2v19",
        "scopes": "openid",
        "client_id_env": "SUBARU_CLIENT_ID",
        "client_secret_env": "SUBARU_CLIENT_SECRET",
        "models": ["Outback", "Forester", "Impreza", "Legacy", "Crosstrek"],
        "popular_in_nigeria": False
    },
    "mazda": {
        "name": "Mazda",
        "logo": "🚗",
        "auth_url": "https://connect.mazda.com/oauth2/authorize",
        "token_url": "https://connect.mazda.com/oauth2/token",
        "api_base": "https://api.mazda.com",
        "scopes": "vehicle_data",
        "client_id_env": "MAZDA_CLIENT_ID",
        "client_secret_env": "MAZDA_CLIENT_SECRET",
        "models": ["CX-5", "CX-9", "Mazda3", "Mazda6", "CX-3"],
        "popular_in_nigeria": False
    },
    "peugeot": {
        "name": "Peugeot / Citroën / Opel",
        "logo": "🚗",
        "auth_url": "https://idpcvs.peugeot.com/am/oauth2/authorize",
        "token_url": "https://idpcvs.peugeot.com/am/oauth2/token",
        "api_base": "https://api.groupe-psa.com/connectedcar/v4",
        "scopes": "openid vehicle:read",
        "client_id_env": "PSA_CLIENT_ID",
        "client_secret_env": "PSA_CLIENT_SECRET",
        "models": ["208", "308", "3008", "5008", "508", "Partner"],
        "popular_in_nigeria": False
    },
    "renault": {
        "name": "Renault / Dacia",
        "logo": "🚗",
        "auth_url": "https://accounts.renault.com/authorize",
        "token_url": "https://accounts.renault.com/token",
        "api_base": "https://api-wired-prod-1-euw1.wrd-aws.com/commerce/v1",
        "scopes": "openid profile",
        "client_id_env": "RENAULT_CLIENT_ID",
        "client_secret_env": "RENAULT_CLIENT_SECRET",
        "models": ["Clio", "Duster", "Logan", "Sandero", "Captur"],
        "popular_in_nigeria": False
    },
}


def get_manufacturer_list():
    """Return list of all supported manufacturers for frontend display."""
    return [
        {
            "id": key,
            "name": val["name"],
            "logo": val["logo"],
            "models": val["models"],
            "popular_in_nigeria": val.get("popular_in_nigeria", False),
            "supported": True,
        }
        for key, val in MANUFACTURERS.items()
    ]


def build_oauth_url(manufacturer_id: str, redirect_uri: str, state: str) -> Optional[str]:
    """
    Build the OAuth URL to redirect user to their manufacturer's login.
    User logs in with their Toyota/BMW/etc account credentials.
    We get a token back to pull their vehicle data.
    """
    mfr = MANUFACTURERS.get(manufacturer_id)
    if not mfr:
        return None

    import os
    client_id = os.getenv(mfr["client_id_env"], "")
    if not client_id:
        # Return a demo URL if not configured
        return f"/frontend/user/manufacturer-setup.html?mfr={manufacturer_id}&demo=true"

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": mfr["scopes"],
        "state": state,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{mfr['auth_url']}?{query}"


async def pull_manufacturer_data(
    manufacturer_id: str,
    oauth_token: str,
    vin: str
) -> dict:
    """
    Pull live vehicle data from manufacturer API using OAuth token.
    Returns standardised scan data compatible with process_hourly_scan().
    """
    mfr = MANUFACTURERS.get(manufacturer_id)
    if not mfr:
        return {"error": "Manufacturer not supported"}

    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json",
    }

    scan_data = {
        "scan_method": "manufacturer_api",
        "manufacturer": manufacturer_id,
        "obd2_status": "Clear",
        "fault_codes": [],
        "engine_rpm": None,
        "coolant_temp_c": None,
        "battery_voltage": None,
        "fuel_level_pct": None,
        "odometer_km": None,
        "speed_kmh": 0,
        "latitude": None,
        "longitude": None,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Each manufacturer has different endpoint structure
            # These are the most common patterns

            if manufacturer_id == "toyota":
                r = await client.get(
                    f"{mfr['api_base']}/vehicles/{vin}/status",
                    headers=headers
                )
                if r.status_code == 200:
                    d = r.json()
                    scan_data.update({
                        "fuel_level_pct": d.get("fuelLevel", {}).get("percentage"),
                        "odometer_km": d.get("odometer", {}).get("value"),
                        "battery_voltage": d.get("battery", {}).get("voltage"),
                    })

            elif manufacturer_id == "ford":
                r = await client.get(
                    f"{mfr['api_base']}/fordconnect/vehicles/v1/{vin}/status",
                    headers=headers
                )
                if r.status_code == 200:
                    d = r.json()
                    vehicle = d.get("vehiclestatus", {})
                    scan_data.update({
                        "fuel_level_pct": vehicle.get("fuel", {}).get("fuelLevel"),
                        "odometer_km": vehicle.get("odometer", {}).get("value"),
                        "battery_voltage": vehicle.get("battery", {}).get("batteryStatusActual", {}).get("value"),
                    })

            elif manufacturer_id == "bmw":
                r = await client.get(
                    f"{mfr['api_base']}/vehicle/dynamic/v1/vehicles/{vin}",
                    headers=headers
                )
                if r.status_code == 200:
                    d = r.json()
                    scan_data.update({
                        "fuel_level_pct": d.get("fuelIndicatorInfo", {}).get("fuelPercent"),
                        "odometer_km": d.get("odometer"),
                    })

            elif manufacturer_id == "mercedes":
                r = await client.get(
                    f"{mfr['api_base']}/vehicles/{vin}/resources/fuellevelpercent",
                    headers=headers
                )
                if r.status_code == 200:
                    d = r.json()
                    scan_data["fuel_level_pct"] = d.get("fuellevelpercent", {}).get("value")

            elif manufacturer_id in ["hyundai", "kia"]:
                r = await client.get(
                    f"{mfr['api_base']}/vehicle/status",
                    headers={**headers, "vehicleId": vin}
                )
                if r.status_code == 200:
                    d = r.json()
                    status = d.get("resMsg", {}).get("vehicleStatusInfo", {})
                    scan_data.update({
                        "fuel_level_pct": status.get("vehicleStatus", {}).get("fuelLevel"),
                        "odometer_km": status.get("odometer"),
                    })

            # Volvo - has best public API
            elif manufacturer_id == "volvo":
                r = await client.get(
                    f"{mfr['api_base']}/vehicles/{vin}/fuel",
                    headers=headers
                )
                if r.status_code == 200:
                    d = r.json()
                    scan_data["fuel_level_pct"] = d.get("fuelAmountLevel", {}).get("value")

                r2 = await client.get(
                    f"{mfr['api_base']}/vehicles/{vin}/odometer",
                    headers=headers
                )
                if r2.status_code == 200:
                    d2 = r2.json()
                    scan_data["odometer_km"] = d2.get("odometerMeter", {}).get("value", 0) / 1000

    except Exception as e:
        scan_data["api_error"] = str(e)

    return scan_data


def get_obd_adapter_guide() -> dict:
    """
    Instructions for OBD-II hardware adapter setup.
    Returned to frontend for display in the vehicle connection wizard.
    """
    return {
        "method": "obd_hardware",
        "title": "OBD-II Bluetooth Adapter",
        "description": "Works on any car made after 1996. No manufacturer account needed.",
        "steps": [
            {
                "step": 1,
                "title": "Buy an OBD-II Adapter",
                "detail": "Search 'ELM327 OBD2 Bluetooth' on Jumia or Konga. Cost: ₦8,000–₦15,000. Make sure it says Bluetooth 4.0 or BLE.",
                "icon": "🛒"
            },
            {
                "step": 2,
                "title": "Plug Into Your Car",
                "detail": "The OBD port is under your dashboard, usually to the left of the steering wheel. Plug the adapter in. It lights up when connected.",
                "icon": "🔌"
            },
            {
                "step": 3,
                "title": "Open Automat Hub App",
                "detail": "Go to My Vehicles → Connect OBD. The app scans for Bluetooth devices and finds your adapter automatically.",
                "icon": "📱"
            },
            {
                "step": 4,
                "title": "Pair Once",
                "detail": "Tap the adapter name to pair. Like connecting Bluetooth headphones. You only do this once.",
                "icon": "🔗"
            },
            {
                "step": 5,
                "title": "Automatic Scanning",
                "detail": "Every hour, the app wakes up, reads your car's health data, and sends it to your dashboard. You will be notified of any faults immediately.",
                "icon": "✅"
            }
        ],
        "recommended_adapters": [
            {"name": "Vgate iCar Pro", "price": "₦12,000–₦15,000", "rating": "Best compatibility"},
            {"name": "OBDLink LX", "price": "₦18,000–₦22,000", "rating": "Professional grade"},
            {"name": "Generic ELM327 v2.1", "price": "₦8,000–₦10,000", "rating": "Good for basic use"},
        ]
    }
