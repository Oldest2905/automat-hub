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

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import csv
import io

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.fleet import (
    Fleet, TrackedVehicle, HourlyScan,
    VehicleAlert, LocationHistory
)
from backend.models.workshop import RepairJob
from backend.services.scan_service import process_hourly_scan

router = APIRouter(prefix="/fleet", tags=["Fleet Management"])


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


# ── FLEET DASHBOARD ──────────────────────────────────────────

@router.get("/dashboard", response_model=dict)
async def fleet_dashboard(
    fleet_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Fleet health dashboard.
    Returns overview of all vehicles with current status.
    This is the main view for fleet managers.
    """
    query = select(TrackedVehicle).where(
        TrackedVehicle.owner_id == current_user["user_id"]
    )
    if fleet_id:
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
            "fault_count": len(v.active_fault_codes or []),
            "last_scan": v.latest_scan_at.isoformat() if v.latest_scan_at else None,
            "location": {
                "lat": v.latest_location_lat,
                "lng": v.latest_location_lng,
                "updated_at": v.latest_location_at.isoformat() if v.latest_location_at else None
            },
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
    result = await db.execute(
        select(TrackedVehicle).where(
            and_(
                TrackedVehicle.vehicle_id == vehicle_id,
                TrackedVehicle.owner_id == current_user["user_id"]
            )
        )
    )
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
    query = select(VehicleAlert).where(
        and_(
            VehicleAlert.user_id == current_user["user_id"],
            VehicleAlert.is_resolved == resolved
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
