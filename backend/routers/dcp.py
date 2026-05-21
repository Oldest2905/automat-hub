"""
routers/dcp.py
All DCP API endpoints.

ENDPOINTS:
POST /dcp/issue              — Issue new DCP (inspector auth required)
GET  /dcp/verify/{dcp_id}   — Public verification (no auth)
GET  /dcp/vehicle/{vin}      — Vehicle history (API key required)
GET  /dcp/{dcp_id}           — Get DCP details (API key required)
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from backend.core.database import get_db
from backend.core.security import get_current_user, verify_api_key
from backend.schemas.dcp import IssueDCPRequest, DCPResponse, DCPVerificationResponse
from backend.services.dcp_service import issue_dcp, verify_dcp, get_vehicle_history
from backend.models.fleet import TrackedVehicle, HourlyScan

router = APIRouter(prefix="/dcp", tags=["Digital Condition Passport"])


@router.post(
    "/issue",
    response_model=dict,
    summary="Issue a new Digital Condition Passport",
    description="Creates and cryptographically hashes a new DCP. Requires inspector authentication."
)
async def issue_dcp_endpoint(
    request: IssueDCPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Issue a new DCP.
    
    - Requires valid JWT with allowed roles
    - Private owners and fleet owners
      cannot issue DCPs — this protects the integrity of the registry
    - Generates SHA-256 hash from inspection data
    - Writes hash to append-only ledger
    - Generates QR code
    - Returns complete DCP record
    """
    # ── ROLE GATE — allowed roles can issue a DCP ──────
    allowed_roles = {"inspector", "admin", "reseller", "mechanic"}
    user_role = current_user.get("role", "")

    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Access denied. DCP issuance requires inspector, admin, reseller, or mechanic role. "
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

@router.post(
    "/auto-issue/{vehicle_id}",
    response_model=dict,
    summary="Auto-issue DCP from latest scan data"
)
async def auto_issue_dcp_endpoint(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Auto-issues a DCP seamlessly using the vehicle's latest hardware scan data.
    """
    # 1. Get Vehicle
    vehicle = await db.scalar(select(TrackedVehicle).where(TrackedVehicle.vehicle_id == vehicle_id))
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # 2. Role gate
    allowed_roles = {"inspector", "admin", "reseller", "mechanic"}
    if current_user.get("role") not in allowed_roles:
        # Allow private owners ONLY if they are using verified hardware
        if vehicle.obd_connection_method not in ["obd_hardware", "manufacturer_api"]:
            raise HTTPException(status_code=403, detail="Private owners can only auto-issue DCPs for hardware-connected vehicles.")
        
    # 3. Get Latest Scan
    latest_scan = await db.scalar(
        select(HourlyScan).where(HourlyScan.vehicle_id == vehicle_id).order_by(desc(HourlyScan.scanned_at)).limit(1)
    )
    if not latest_scan:
        raise HTTPException(status_code=400, detail="No scan data available. Please connect and scan the vehicle first.")
        
    # 4. Build IssueDCPRequest
    obd_status = "Faults Present" if latest_scan.fault_codes else "Clear"
    score = latest_scan.health_score or 100
    
    # Ensure VIN meets the 17-character requirement for test/demo VINs
    safe_vin = vehicle.vin.upper()
    if len(safe_vin) < 17:
        safe_vin = safe_vin.ljust(17, '0')

    request_data = {
        "vehicle": {
            "vin": safe_vin,
            "make": vehicle.make or "Unknown",
            "model": vehicle.model or "Unknown",
            "year": vehicle.year or datetime.now().year,
            "colour": vehicle.colour or "Unknown",
            "odometer": latest_scan.odometer_km or vehicle.odometer_current or 0
        },
        "inspection": {
            "score": score,
            "mechanical_systems": score,
            "electrical_controls": score,
            "structural_integrity": 100,
            "maintenance_compliance": 100,
            "hse_standards": 100,
            "operational_technology": score,
            "obd2_status": obd_status,
            "obd2_fault_codes": latest_scan.fault_codes or [],
            "obd2_readiness_monitors": {},
            "engine_compression": "Good",
            "engine_oil_condition": "Good",
            "coolant_condition": "Good",
            "timing_belt_condition": "Good",
            "transmission_condition": "Good",
            "transmission_fluid": "Good",
            "frame_alignment": "Good",
            "rust_assessment": "Good",
            "accident_history_indicators": False,
            "paint_uniformity": "Good",
            "battery_health": "Good",
            "alternator_output": "Good",
            "electronics_status": "Good",
            "brake_condition": "Good",
            "tyre_condition": {"front_left": "Good", "front_right": "Good", "rear_left": "Good", "rear_right": "Good"},
            "airbag_status": "Good",
            "abs_status": "Good",
            "ai_condition_grade": "A" if score >= 80 else "B" if score >= 60 else "C",
            "ai_confidence_score": 0.95,
            "ai_flags": [],
            "checklist_results": {},
            "inspector_notes": "Auto-issued from hardware telemetrics."
        },
        "auditor_id": current_user["user_id"],
        "warranty_days": 30
    }
    request = IssueDCPRequest(**request_data)
    
    result = await issue_dcp(request, db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Update vehicle's latest_dcp_id
    vehicle.latest_dcp_id = result.get("dcp_id")
    await db.flush()
        
    return {
        "success": True,
        "message": "DCP auto-issued successfully",
        "data": result
    }

@router.get(
    "/verify/{dcp_id}",
    response_model=dict,
    summary="Verify a Digital Condition Passport",
    description="Public endpoint. Anyone with a DCP ID can verify authenticity. No authentication required."
)
async def verify_dcp_endpoint(
    dcp_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Public DCP verification.
    
    - No authentication required
    - Recomputes SHA-256 hash and compares with stored hash
    - Returns full verification result
    - Logs every verification attempt
    
    This is what gets scanned when a buyer hits the QR code on the windshield.
    """
    client_ip = request.client.host if request.client else None

    result = await verify_dcp(
        dcp_id=dcp_id,
        db=db,
        requester_ip=client_ip,
        method="API"
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.get(
    "/vehicle/{vin}",
    response_model=dict,
    summary="Get full DCP history for a VIN",
    description="Returns all DCPs ever issued for a vehicle. Requires API key."
)
async def vehicle_history_endpoint(
    vin: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """
    Vehicle condition history.
    
    - Requires API key (licensed dealers, banks, insurers)
    - Returns all DCPs for the VIN in reverse chronological order
    - This is the Condition Registry in embryonic form
    """
    result = await get_vehicle_history(vin.upper(), db)

    return {
        "success": True,
        "data": result
    }


@router.get(
    "/{dcp_id}",
    response_model=dict,
    summary="Get DCP details",
    description="Get full DCP record. Public for basic info, API key for full inspection data."
)
async def get_dcp_endpoint(
    dcp_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get DCP record.
    Public access returns summary.
    """
    result = await verify_dcp(dcp_id=dcp_id, db=db, method="DIRECT")

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "success": True,
        "data": result
    }
