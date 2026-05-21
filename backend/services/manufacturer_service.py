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