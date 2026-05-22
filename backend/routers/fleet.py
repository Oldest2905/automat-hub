"""
routers/fleet.py
Fleet management API endpoints.

Fleet Owner can:
- Create and manage their fleet
- Add/remove vehicles
- View live fleet health dashboard
- See vehicle locations in real time
- View scan history per vehicle
- Export fleet health reports
- Receive and manage fault alerts
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_, update
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import csv
import io
import json

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.fleet import (
    Fleet, TrackedVehicle, HourlyScan,
    VehicleAlert, LocationHistory
)
from backend.models.workshop import RepairJob
from backend.services.manufacturer_service import process_hourly_scan

router = APIRouter(prefix="/fleet", tags=["Fleet Management"])


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


# ── FLEET MANAGEMENT ─────────────────────────────────────────

@router.post("/create", response_model=dict)
async def create_fleet(
    name: str,
    industry: str,
    description: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Create a new fleet group."""
    import uuid as _uuid
    fleet_id = f"FLT-{str(_uuid.uuid4())[:8].upper()}"

    fleet = Fleet(
        fleet_id=fleet_id,
        owner_id=current_user["user_id"],
        name=name,
        industry=industry,
        description=description
    )
    db.add(fleet)
    await db.flush()

    return {
        "success": True,
        "fleet_id": fleet_id,
        "name": name,
        "message": "Fleet created successfully"
    }


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
    
    if user and getattr(user, "role", "") == "admin":
        allowed_slots = 999999  # CEO Lifetime Admin Bypass
    else:
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

    # ── EXTERNAL VIN VALIDATION (Loophole 1 Fix) ─────────────────
    try:
        import httpx
        import os
        epicvin_key = os.getenv("EPICVIN_API_KEY")
        
        async with httpx.AsyncClient(timeout=10) as client:
            if epicvin_key:
                # EpicVIN Integration (Stolen/Salvage DB Check)
                res = await client.get(
                    f"https://api.epicvin.com/api/v1/vin/decode?vin={vin.upper()}",
                    headers={"Authorization": f"Bearer {epicvin_key}"}
                )
                if res.status_code == 200:
                    data = res.json()
                    # Reject if stolen or salvage
                    if data.get("stolen") or data.get("salvage"):
                        raise HTTPException(
                            status_code=400, 
                            detail="VIN rejected: Vehicle flagged as stolen or salvage by EpicVIN."
                        )
            else:
                # NHTSA Free Fallback (Validates VIN exists + exact Make/Model match)
                res = await client.get(f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin.upper()}?format=json")
                if res.status_code == 200:
                    data = res.json()
                    results = {r["Variable"]: r["Value"] for r in data.get("Results", [])}
                    error_code = results.get("Error Code", "")
                    
                    if error_code and not error_code.startswith("0") and not vin.upper().startswith("DEMO"):
                        raise HTTPException(
                            status_code=400, 
                            detail=f"Invalid VIN: {error_code.split('-')[-1].strip()}"
                        )
                        
                    # Auto-correct backend data to match federal registry
                    if results.get("Make") and results.get("Make") != "null": make = results.get("Make")
                    if results.get("Model") and results.get("Model") != "null": model = results.get("Model")
                    if results.get("Model Year") and results.get("Model Year") != "null":
                        try: year = int(results.get("Model Year"))
                        except ValueError: pass
    except HTTPException:
        raise
    except Exception as e:
        print(f"VIN validation service unavailable: {e}")
        # Proceed with registration if external APIs are down to prevent blocking users
    # ── END VIN VALIDATION ───────────────────────────────────────

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

@router.get("/vehicle/{vehicle_id}/export", response_class=Response)
async def export_single_vehicle(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Export all data for a single vehicle before deletion."""
    if current_user.get("role") == "admin":
        where_clause = TrackedVehicle.vehicle_id == vehicle_id
    else:
        where_clause = and_(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    result = await db.execute(select(TrackedVehicle).where(where_clause))
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    scan_result = await db.execute(
        select(HourlyScan).where(HourlyScan.vehicle_id == vehicle_id)
        .order_by(desc(HourlyScan.scanned_at)).limit(500)
    )
    scans = scan_result.scalars().all()

    export_data = {
        "vehicle": {
            "vehicle_id": vehicle.vehicle_id,
            "vin": vehicle.vin,
            "make": vehicle.make,
            "model": vehicle.model,
            "year": vehicle.year,
            "plate_number": vehicle.plate_number,
            "status": vehicle.status,
            "health_score": vehicle.latest_score,
            "obd_connection_method": vehicle.obd_connection_method,
        },
        "telemetry_history": [
            {
                "scan_id": s.scan_id,
                "scanned_at": s.scanned_at.isoformat() if s.scanned_at else None,
                "health_score": s.health_score,
                "fault_codes": s.fault_codes,
                "odometer_km": s.odometer_km,
                "speed_kmh": s.speed_kmh,
                "coolant_temp_c": s.coolant_temp_c,
                "battery_voltage": s.battery_voltage
            } for s in scans
        ]
    }
    
    json_str = json.dumps(export_data, indent=2)
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=vehicle_{vehicle.vin}_export.json"}
    )

@router.post("/vehicle/{vehicle_id}/remove", response_model=dict)
async def remove_vehicle(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Remove a vehicle globally and totally from the user's account and the platform.
    """
    from backend.models.dcp import DCPRecord, DCPHashLedger, InspectionDetail, VerificationLog
    from backend.models.fleet import HourlyScan, VehicleAlert, LocationHistory
    from backend.models.workshop import RepairJob

    if current_user.get("role") == "admin":
        where_clause = TrackedVehicle.vehicle_id == vehicle_id
    else:
        where_clause = and_(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    result = await db.execute(select(TrackedVehicle).where(where_clause))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    vin = vehicle.vin

    # ── ARCHIVE THE VEHICLE ──
    try:
        from backend.models.archive import DeletedVehicleArchive
        archive = DeletedVehicleArchive(
            original_vehicle_id=vehicle.vehicle_id,
            vin=vehicle.vin,
            owner_id=vehicle.owner_id,
            deleted_by=current_user["user_id"],
            vehicle_data={
                "make": vehicle.make,
                "model": vehicle.model,
                "year": vehicle.year,
                "plate_number": vehicle.plate_number
            },
            telemetry_snapshot={
                "last_score": vehicle.latest_score,
                "last_status": vehicle.status,
                "faults": vehicle.active_fault_codes,
                "odometer": vehicle.odometer_current
            }
        )
        db.add(archive)
    except Exception as e:
        print(f"Skipping archive creation: {e}")

    # Delete related fleet records
    await db.execute(HourlyScan.__table__.delete().where(HourlyScan.vehicle_id == vehicle_id))
    await db.execute(VehicleAlert.__table__.delete().where(VehicleAlert.vehicle_id == vehicle_id))
    await db.execute(LocationHistory.__table__.delete().where(LocationHistory.vehicle_id == vehicle_id))
    await db.execute(RepairJob.__table__.delete().where(RepairJob.vehicle_id == vehicle_id))
    
    # Delete related DCP records to totally purge the vehicle
    dcp_result = await db.execute(select(DCPRecord.dcp_id).where(DCPRecord.vin == vin))
    dcp_ids = dcp_result.scalars().all()
    
    if dcp_ids:
        from backend.models.escrow import EscrowDeal, EscrowEvent
        # Delete related escrows first to prevent foreign key orphaning
        await db.execute(EscrowEvent.__table__.delete().where(
            EscrowEvent.escrow_id.in_(select(EscrowDeal.escrow_id).where(EscrowDeal.dcp_id.in_(dcp_ids)))
        ))
        await db.execute(EscrowDeal.__table__.delete().where(EscrowDeal.dcp_id.in_(dcp_ids)))
        
        await db.execute(InspectionDetail.__table__.delete().where(InspectionDetail.dcp_id.in_(dcp_ids)))
        await db.execute(VerificationLog.__table__.delete().where(VerificationLog.dcp_id.in_(dcp_ids)))
        await db.execute(DCPHashLedger.__table__.delete().where(DCPHashLedger.vin == vin))
        await db.execute(DCPRecord.__table__.delete().where(DCPRecord.vin == vin))

    # Delete the vehicle itself
    await db.delete(vehicle)
    await db.flush()

    return {
        "success": True,
        "message": "Vehicle and all associated records permanently removed."
    }

# ── FLEET DASHBOARD ──────────────────────────────────────────

@router.get("/dashboard", response_model=dict)
async def fleet_dashboard(
    fleet_id: Optional[str] = None,
    global_view: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Fleet health dashboard.
    Returns overview of all vehicles with current status.
    This is the main view for fleet managers.
    """
    if global_view and current_user.get("role") == "admin":
        query = select(TrackedVehicle).where(TrackedVehicle.status != "inactive")
    else:
        query = select(TrackedVehicle).where(
            and_(
                TrackedVehicle.owner_id == current_user["user_id"],
                TrackedVehicle.status != "inactive"
            )
        )
    
    if fleet_id and not global_view:
        query = query.where(TrackedVehicle.fleet_id == fleet_id)

    result = await db.execute(query)
    vehicles = result.scalars().all()

    # Count by status
    healthy = sum(1 for v in vehicles if v.status == "healthy")
    warning = sum(1 for v in vehicles if v.status == "warning")
    critical = sum(1 for v in vehicles if v.status == "critical")
    in_workshop = sum(1 for v in vehicles if v.status == "in_workshop")

    # Build vehicle summaries
    vehicle_list = []
    for v in vehicles:
        vehicle_list.append({
            "vehicle_id": v.vehicle_id,
            "vin": v.vin,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "plate_number": v.plate_number,
            "status": v.status,
            "health_score": v.latest_score,
            "has_faults": v.has_active_faults,
            "latest_dcp_id": v.latest_dcp_id,
            "fault_count": len(v.active_fault_codes or []),
            "last_scan": v.latest_scan_at.isoformat() if v.latest_scan_at else None,
            "location": {
                "lat": v.latest_location_lat,
                "lng": v.latest_location_lng,
                "updated_at": v.latest_location_at.isoformat() if v.latest_location_at else None
            },
            "obd_connection_method": v.obd_connection_method,
            "fuel_level": v.fuel_level_percent,
            "speed_kmh": v.current_speed_kmh,
            "odometer_km": v.odometer_current
        })

    return {
        "success": True,
        "summary": {
            "total_vehicles": len(vehicles),
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "in_workshop": in_workshop,
            "fleet_health_score": round(
                sum(v.latest_score or 100 for v in vehicles) / max(len(vehicles), 1)
            )
        },
        "vehicles": vehicle_list
    }


@router.get("/vehicle/{vehicle_id}/live", response_model=dict)
async def vehicle_live_status(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Live status of a single vehicle including latest scan data."""
    if current_user.get("role") == "admin":
        where_clause = TrackedVehicle.vehicle_id == vehicle_id
    else:
        where_clause = and_(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    result = await db.execute(select(TrackedVehicle).where(where_clause))
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Latest scan
    scan_result = await db.execute(
        select(HourlyScan)
        .where(HourlyScan.vehicle_id == vehicle_id)
        .order_by(desc(HourlyScan.scanned_at))
        .limit(1)
    )
    latest_scan = scan_result.scalar_one_or_none()

    return {
        "success": True,
        "vehicle": {
            "vehicle_id": vehicle.vehicle_id,
            "vin": vehicle.vin,
            "make": vehicle.make,
            "model": vehicle.model,
            "plate_number": vehicle.plate_number,
            "status": vehicle.status,
            "health_score": vehicle.latest_score,
            "active_faults": vehicle.active_fault_codes or [],
            "location": {
                "lat": vehicle.latest_location_lat,
                "lng": vehicle.latest_location_lng,
            },
            "speed_kmh": vehicle.current_speed_kmh,
            "fuel_level": vehicle.fuel_level_percent,
            "odometer_km": vehicle.odometer_current,
        },
        "latest_scan": {
            "scan_id": latest_scan.scan_id if latest_scan else None,
            "obd2_status": latest_scan.obd2_status if latest_scan else None,
            "fault_codes": latest_scan.fault_codes if latest_scan else [],
            "coolant_temp_c": latest_scan.coolant_temp_c if latest_scan else None,
            "battery_voltage": latest_scan.battery_voltage if latest_scan else None,
            "engine_rpm": latest_scan.engine_rpm if latest_scan else None,
            "scanned_at": latest_scan.scanned_at.isoformat() if latest_scan else None,
        } if latest_scan else None
    }


@router.get("/vehicle/{vehicle_id}/history", response_model=dict)
async def vehicle_scan_history(
    vehicle_id: str,
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Scan history for a vehicle.
    Returns health score trend over time.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(HourlyScan)
        .where(
            and_(
                HourlyScan.vehicle_id == vehicle_id,
                HourlyScan.scanned_at >= since
            )
        )
        .order_by(HourlyScan.scanned_at)
    )
    scans = result.scalars().all()

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "period_days": days,
        "total_scans": len(scans),
        "history": [
            {
                "scan_id": s.scan_id,
                "health_score": s.health_score,
                "health_status": s.health_status,
                "fault_codes": s.fault_codes,
                "new_faults": s.fault_codes_new,
                "cleared_faults": s.fault_codes_cleared,
                "coolant_temp_c": s.coolant_temp_c,
                "battery_voltage": s.battery_voltage,
                "odometer_km": s.odometer_km,
                "scanned_at": s.scanned_at.isoformat()
            }
            for s in scans
        ]
    }


@router.get("/vehicle/{vehicle_id}/location-trail", response_model=dict)
async def vehicle_location_trail(
    vehicle_id: str,
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    GPS trail for a vehicle over the last N hours.
    Used for live tracking map replay.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(LocationHistory)
        .where(
            and_(
                LocationHistory.vehicle_id == vehicle_id,
                LocationHistory.recorded_at >= since
            )
        )
        .order_by(LocationHistory.recorded_at)
    )
    points = result.scalars().all()

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "hours": hours,
        "points": [
            {
                "lat": p.latitude,
                "lng": p.longitude,
                "speed_kmh": p.speed_kmh,
                "heading": p.heading,
                "recorded_at": p.recorded_at.isoformat()
            }
            for p in points
        ]
    }


@router.get("/alerts", response_model=dict)
async def get_alerts(
    resolved: bool = False,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get all alerts for fleet owner."""
    query = (
        select(VehicleAlert)
        .join(TrackedVehicle, VehicleAlert.vehicle_id == TrackedVehicle.vehicle_id)
        .where(
            and_(
                VehicleAlert.user_id == current_user["user_id"],
                VehicleAlert.is_resolved == resolved,
                TrackedVehicle.status != "inactive"
            )
        )
    )
    if severity:
        query = query.where(VehicleAlert.severity == severity)

    query = query.order_by(desc(VehicleAlert.created_at)).limit(100)
    result = await db.execute(query)
    alerts = result.scalars().all()

    return {
        "success": True,
        "alerts": [
            {
                "alert_id": a.alert_id,
                "vehicle_id": a.vehicle_id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "message": a.message,
                "fault_codes": a.fault_codes,
                "is_resolved": a.is_resolved,
                "created_at": a.created_at.isoformat()
            }
            for a in alerts
        ]
    }

@router.post("/alerts/clear", response_model=dict)
async def clear_all_alerts(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Clear (resolve) all active alerts for the user."""
    await db.execute(
        update(VehicleAlert)
        .where(VehicleAlert.user_id == current_user["user_id"])
        .where(VehicleAlert.is_resolved == False)
        .values(is_resolved=True)
    )
    await db.flush()
    return {"success": True, "message": "All alerts cleared"}

@router.get("/inspectors/directory", response_model=dict)
async def get_inspectors_directory(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Public directory for users to find certified inspectors."""
    from backend.models.user import User
    result = await db.execute(select(User).where(User.role == "inspector", User.is_active == True))
    inspectors = result.scalars().all()
    
    # In production, ratings would be pulled from an InspectorReviews table. 
    # For now, we mock a high trust rating for certified staff.
    return {
        "success": True,
        "inspectors": [{"id": i.user_id, "name": i.full_name, "email": i.email, "phone": i.phone or "Contact Hub", "rating": 4.9, "location": "The Automat Hub, Ibadan"} for i in inspectors]
    }


# ── FLEET REPORT EXPORT ──────────────────────────────────────

@router.get("/report/export", response_class=StreamingResponse)
async def export_fleet_report(
    fleet_id: Optional[str] = None,
    days: int = Query(default=30, ge=1, le=365),
    format: str = Query(default="csv", regex="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Export fleet health report as CSV or JSON.
    Includes all vehicles, scan summaries, fault history.
    """
    query = select(TrackedVehicle).where(
        TrackedVehicle.owner_id == current_user["user_id"]
    )
    if fleet_id:
        query = query.where(TrackedVehicle.fleet_id == fleet_id)

    result = await db.execute(query)
    vehicles = result.scalars().all()

    since = datetime.now(timezone.utc) - timedelta(days=days)
    report_data = []

    for v in vehicles:
        # Get scan stats for this vehicle
        scan_result = await db.execute(
            select(
                func.count(HourlyScan.id).label("total_scans"),
                func.avg(HourlyScan.health_score).label("avg_score"),
                func.min(HourlyScan.health_score).label("min_score")
            ).where(
                and_(
                    HourlyScan.vehicle_id == v.vehicle_id,
                    HourlyScan.scanned_at >= since
                )
            )
        )
        stats = scan_result.fetchone()

        # Active repair jobs
        job_result = await db.execute(
            select(func.count(RepairJob.id)).where(
                and_(
                    RepairJob.vehicle_id == v.vehicle_id,
                    RepairJob.status != "completed"
                )
            )
        )
        active_jobs = job_result.scalar() or 0

        report_data.append({
            "vehicle_id": v.vehicle_id,
            "vin": v.vin,
            "make": v.make,
            "model": v.model,
            "year": v.year,
            "plate_number": v.plate_number,
            "current_status": v.status,
            "current_health_score": v.latest_score or "N/A",
            "active_fault_codes": ", ".join(v.active_fault_codes or []),
            "fault_count": len(v.active_fault_codes or []),
            "total_scans_in_period": stats.total_scans or 0,
            "average_health_score": round(stats.avg_score or 0, 1),
            "lowest_health_score": stats.min_score or "N/A",
            "active_repair_jobs": active_jobs,
            "odometer_km": v.odometer_current,
            "fuel_level_pct": v.fuel_level_percent,
            "last_scan": v.latest_scan_at.isoformat() if v.latest_scan_at else "Never",
            "report_period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat()
        })

    if format == "csv":
        output = io.StringIO()
        if report_data:
            writer = csv.DictWriter(output, fieldnames=report_data[0].keys())
            writer.writeheader()
            writer.writerows(report_data)

        output.seek(0)
        filename = f"automat_fleet_report_{datetime.now().strftime('%Y%m%d')}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    return {"success": True, "report": report_data, "generated_at": datetime.now(timezone.utc).isoformat()}


# ── SCAN INTAKE ──────────────────────────────────────────────

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

    result = await process_hourly_scan(payload.vehicle_id, scan_data, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"success": True, "data": result}
