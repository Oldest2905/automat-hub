"""
services/scan_service.py
Hourly OBD scan processing, fault detection, and alert triggering.

SCAN FLOW:
1. Scheduler triggers scan every hour per vehicle
2. OBD data received (from hardware adapter or manufacturer API)
3. Data hashed and appended to vehicle's DCP
4. Fault codes analysed
5. Health score calculated
6. Alerts triggered if faults found
7. Nearest workshop found if critical
8. Owner/fleet manager notified
"""

import hashlib
import json
import uuid
import math
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from backend.models.fleet import (
    TrackedVehicle, HourlyScan, VehicleAlert, VehicleStatus
)
from backend.models.workshop import Workshop
from backend.services.notification_service import send_sms


# ── FAULT CODE SEVERITY MAPPING ──────────────────────────────
# P = Powertrain, B = Body, C = Chassis, U = Network
CRITICAL_FAULT_PREFIXES = [
    "P0300",  # Random misfire
    "P0301", "P0302", "P0303", "P0304",  # Cylinder misfires
    "P0016", "P0017",  # Camshaft/crankshaft correlation
    "P0562",  # Low system voltage
    "C0035", "C0040",  # Wheel speed sensors (ABS critical)
]

WARNING_FAULT_PREFIXES = [
    "P0420", "P0430",  # Catalyst efficiency
    "P0171", "P0174",  # System lean
    "P0401",  # EGR insufficient flow
    "P0442",  # Small evap leak
]


def classify_fault_severity(fault_codes: List[str]) -> str:
    """Classify overall severity from list of fault codes."""
    if not fault_codes:
        return "healthy"

    for code in fault_codes:
        for critical in CRITICAL_FAULT_PREFIXES:
            if code.startswith(critical[:4]):
                return "critical"

    for code in fault_codes:
        for warning in WARNING_FAULT_PREFIXES:
            if code.startswith(warning[:4]):
                return "warning"

    return "warning"  # Any fault = at least warning


def calculate_health_score(scan_data: dict) -> int:
    """
    Calculate health score 0-100 from OBD scan data.
    Starts at 100, deducts for each fault and sensor anomaly.
    """
    score = 100

    # Fault codes — biggest deduction
    fault_codes = scan_data.get("fault_codes", [])
    score -= len(fault_codes) * 8  # -8 per fault code

    # Critical fault codes get extra deduction
    for code in fault_codes:
        for critical in CRITICAL_FAULT_PREFIXES:
            if code.startswith(critical[:4]):
                score -= 15  # Additional -15 for critical codes
                break

    # Sensor anomalies
    coolant_temp = scan_data.get("coolant_temp_c", 90)
    if coolant_temp and coolant_temp > 110:
        score -= 20  # Overheating
    elif coolant_temp and coolant_temp > 100:
        score -= 10  # Running hot

    battery_voltage = scan_data.get("battery_voltage", 12.6)
    if battery_voltage and battery_voltage < 11.5:
        score -= 15  # Low battery
    elif battery_voltage and battery_voltage < 12.0:
        score -= 8

    fuel_level = scan_data.get("fuel_level_pct", 50)
    if fuel_level and fuel_level < 10:
        score -= 5  # Low fuel (minor deduction — not mechanical)

    return max(0, min(100, score))


def generate_scan_hash(scan_data: dict) -> str:
    """Hash scan data for integrity."""
    payload = json.dumps(scan_data, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in km between two GPS coordinates."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def find_nearest_workshop(
    latitude: float,
    longitude: float,
    fault_codes: List[str],
    db: AsyncSession
) -> Optional[dict]:
    """
    Find nearest available registered workshop.
    Filters by availability and capacity.
    Returns workshop with distance in km.
    """
    result = await db.execute(
        select(Workshop).where(
            and_(
                Workshop.status == "active",
                Workshop.is_available == True,
            )
        )
    )
    workshops = result.scalars().all()

    if not workshops:
        return None

    # Calculate distance to each workshop
    workshops_with_distance = []
    for ws in workshops:
        if ws.latitude and ws.longitude:
            distance = haversine_distance(
                latitude, longitude,
                ws.latitude, ws.longitude
            )
            workshops_with_distance.append({
                "workshop_id": ws.workshop_id,
                "name": ws.name,
                "address": ws.address,
                "phone": None,
                "latitude": ws.latitude,
                "longitude": ws.longitude,
                "distance_km": round(distance, 1),
                "current_jobs": ws.current_active_jobs,
                "capacity": ws.max_concurrent_jobs,
                "available_slots": ws.max_concurrent_jobs - ws.current_active_jobs
            })

    # Sort by distance, filter to available
    available = [w for w in workshops_with_distance if w["available_slots"] > 0]
    available.sort(key=lambda x: x["distance_km"])

    return available[0] if available else None


async def process_hourly_scan(
    vehicle_id: str,
    scan_data: dict,
    db: AsyncSession
) -> dict:
    """
    Process an incoming hourly OBD scan.

    scan_data should contain:
    - obd2_status: str
    - fault_codes: list
    - engine_rpm: float
    - coolant_temp_c: float
    - battery_voltage: float
    - fuel_level_pct: float
    - odometer_km: int
    - speed_kmh: float
    - latitude: float
    - longitude: float
    - scan_method: str (obd_hardware | manufacturer_api | manual)
    """

    # Fetch vehicle
    result = await db.execute(
        select(TrackedVehicle).where(TrackedVehicle.vehicle_id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        return {"error": f"Vehicle {vehicle_id} not found"}

    fault_codes = scan_data.get("fault_codes", [])
    health_score = calculate_health_score(scan_data)
    severity = classify_fault_severity(fault_codes)

    # Determine new faults (not in previous scan)
    previous_faults = set(vehicle.active_fault_codes or [])
    current_faults = set(fault_codes)
    new_faults = list(current_faults - previous_faults)
    cleared_faults = list(previous_faults - current_faults)

    # Generate scan hash
    scan_payload = {
        "vehicle_id": vehicle_id,
        "vin": vehicle.vin,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health_score": health_score,
        **scan_data
    }
    scan_hash = generate_scan_hash(scan_payload)

    # Create scan record
    scan_id = f"SCN-{datetime.now(timezone.utc).year}-{str(uuid.uuid4())[:8].upper()}"

    scan = HourlyScan(
        scan_id=scan_id,
        vehicle_id=vehicle_id,
        vin=vehicle.vin,
        dcp_id=vehicle.latest_dcp_id,
        scan_method=scan_data.get("scan_method", "obd_hardware"),
        obd2_status=scan_data.get("obd2_status", "Unknown"),
        fault_codes=fault_codes,
        fault_codes_new=new_faults,
        fault_codes_cleared=cleared_faults,
        engine_rpm=scan_data.get("engine_rpm"),
        coolant_temp_c=scan_data.get("coolant_temp_c"),
        oil_temp_c=scan_data.get("oil_temp_c"),
        throttle_position_pct=scan_data.get("throttle_position_pct"),
        battery_voltage=scan_data.get("battery_voltage"),
        fuel_level_pct=scan_data.get("fuel_level_pct"),
        odometer_km=scan_data.get("odometer_km"),
        speed_kmh=scan_data.get("speed_kmh"),
        latitude=scan_data.get("latitude"),
        longitude=scan_data.get("longitude"),
        health_score=health_score,
        health_status=severity,
        scan_hash=scan_hash,
    )
    db.add(scan)

    # Update vehicle
    vehicle.latest_scan_at = datetime.now(timezone.utc)
    vehicle.latest_score = health_score
    vehicle.active_fault_codes = fault_codes
    vehicle.has_active_faults = bool(fault_codes)
    vehicle.odometer_current = scan_data.get("odometer_km", vehicle.odometer_current)
    vehicle.fuel_level_percent = scan_data.get("fuel_level_pct")
    vehicle.current_speed_kmh = scan_data.get("speed_kmh", 0)

    if scan_data.get("latitude"):
        vehicle.latest_location_lat = scan_data["latitude"]
        vehicle.latest_location_lng = scan_data["longitude"]
        vehicle.latest_location_at = datetime.now(timezone.utc)

    # Map severity to status
    status_map = {
        "healthy": VehicleStatus.HEALTHY,
        "warning": VehicleStatus.WARNING,
        "critical": VehicleStatus.CRITICAL
    }
    vehicle.status = status_map.get(severity, VehicleStatus.WARNING)

    alerts_triggered = []
    workshop_referral = None

    # ── TRIGGER ALERTS FOR NEW FAULTS ────────────────────────
    if new_faults:
        alert_id = f"ALT-{str(uuid.uuid4())[:8].upper()}"

        if severity == "critical":
            title = "⚠️ CRITICAL: Immediate attention required"
            message = (
                f"Your {vehicle.make} {vehicle.model} has {len(new_faults)} "
                f"critical fault code(s): {', '.join(new_faults[:3])}. "
                f"Do not drive until inspected."
            )
        else:
            title = "⚡ Vehicle fault detected"
            message = (
                f"Your {vehicle.make} {vehicle.model} has "
                f"{len(new_faults)} new fault code(s): {', '.join(new_faults[:3])}. "
                f"Schedule a service soon."
            )

        alert = VehicleAlert(
            alert_id=alert_id,
            vehicle_id=vehicle_id,
            user_id=vehicle.owner_id,
            alert_type="fault_detected",
            severity=severity,
            title=title,
            message=message,
            fault_codes=new_faults,
        )
        db.add(alert)
        alerts_triggered.append(alert_id)

        # Send SMS to owner
        # TODO: fetch owner phone from user table
        # await send_sms(owner_phone, message)

        # ── FIND NEAREST WORKSHOP FOR CRITICAL FAULTS ────────
        if severity == "critical" and scan_data.get("latitude"):
            workshop_referral = await find_nearest_workshop(
                latitude=scan_data["latitude"],
                longitude=scan_data["longitude"],
                fault_codes=new_faults,
                db=db
            )
            if workshop_referral:
                scan.workshop_referral_triggered = True
                scan.alerts_triggered = alerts_triggered

    await db.flush()

    return {
        "scan_id": scan_id,
        "vehicle_id": vehicle_id,
        "vin": vehicle.vin,
        "health_score": health_score,
        "health_status": severity,
        "fault_codes": fault_codes,
        "new_faults": new_faults,
        "cleared_faults": cleared_faults,
        "alerts_triggered": alerts_triggered,
        "workshop_referral": workshop_referral,
        "scan_hash": scan_hash,
        "scanned_at": scan.scanned_at.isoformat()
    }
