"""
services/dcp_service.py
DCP business logic layer.
Orchestrates hashing, database operations, and QR generation.
"""

from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import Optional

from backend.core.hashing import issue_dcp_hash, verify_dcp_hash
from backend.models.dcp import DCPRecord, DCPHashLedger, InspectionDetail, VerificationLog
from backend.schemas.dcp import IssueDCPRequest, DCPResponse, DCPVerificationResponse
from backend.services.qr_service import generate_qr_code
from backend.config import settings


def calculate_grade(score: int) -> str:
    if score >= 90:
        return "A"
    elif score >= 75:
        return "B"
    elif score >= 60:
        return "C"
    else:
        return "D"


async def issue_dcp(
    request: IssueDCPRequest,
    db: AsyncSession
) -> dict:
    """
    Issue a new Digital Condition Passport.

    Flow:
    1. Build inspection data dict
    2. Generate SHA-256 hash
    3. Save DCP record to PostgreSQL
    4. Save hash to APPEND-ONLY ledger
    5. Save full inspection details
    6. Generate QR code
    7. Return complete DCP record
    """

    grade = calculate_grade(request.inspection.score)

    # Build inspection data for hashing
    inspection_dict = request.inspection.model_dump()

    # Generate the DCP hash
    hash_record = issue_dcp_hash(
        vin=request.vehicle.vin,
        auditor_id=request.auditor_id,
        inspection_data={
            **request.vehicle.model_dump(),
            **inspection_dict,
            "grade": grade
        }
    )

    # Calculate warranty expiry
    warranty_expiry = datetime.now(timezone.utc) + timedelta(
        days=request.warranty_days
    )

    # Save main DCP record
    dcp_record = DCPRecord(
        dcp_id=hash_record["dcp_id"],
        vin=request.vehicle.vin,
        make=request.vehicle.make,
        model=request.vehicle.model,
        year=request.vehicle.year,
        colour=request.vehicle.colour,
        odometer=request.vehicle.odometer,
        score=request.inspection.score,
        grade=grade,
        status="VERIFIED",
        auditor_id=request.auditor_id,
        warranty_days=request.warranty_days,
        warranty_expiry=warranty_expiry,
        issued_at=hash_record["issued_at"],
    )
    db.add(dcp_record)

    # Save to APPEND-ONLY hash ledger
    # This is the tamper-evident record
    hash_ledger = DCPHashLedger(
        dcp_id=hash_record["dcp_id"],
        vin=request.vehicle.vin,
        hash=hash_record["hash"],
        hash_algorithm="SHA-256",
        payload_json=hash_record["payload"],
        payload_string=hash_record["payload_string"],
        auditor_id=request.auditor_id,
        issued_at=hash_record["issued_at"],
    )
    db.add(hash_ledger)

    # Save full inspection details
    inspection_detail = InspectionDetail(
        dcp_id=hash_record["dcp_id"],
        obd2_status=request.inspection.obd2_status.value,
        obd2_fault_codes=request.inspection.obd2_fault_codes,
        obd2_readiness_monitors=request.inspection.obd2_readiness_monitors,
        engine_compression=request.inspection.engine_compression.value,
        engine_oil_condition=request.inspection.engine_oil_condition.value,
        coolant_condition=request.inspection.coolant_condition.value,
        timing_belt_condition=request.inspection.timing_belt_condition.value,
        transmission_condition=request.inspection.transmission_condition.value,
        transmission_fluid=request.inspection.transmission_fluid.value,
        frame_alignment=request.inspection.frame_alignment,
        rust_assessment=request.inspection.rust_assessment.value,
        accident_history_indicators=request.inspection.accident_history_indicators,
        paint_uniformity=request.inspection.paint_uniformity.value,
        battery_health=request.inspection.battery_health.value,
        alternator_output=request.inspection.alternator_output.value,
        electronics_status=request.inspection.electronics_status.value,
        brake_condition=request.inspection.brake_condition.value,
        tyre_condition=request.inspection.tyre_condition,
        airbag_status=request.inspection.airbag_status.value,
        abs_status=request.inspection.abs_status.value,
        ai_condition_grade=request.inspection.ai_condition_grade,
        ai_confidence_score=request.inspection.ai_confidence_score,
        ai_flags=request.inspection.ai_flags,
        checklist_results=request.inspection.checklist_results,
        inspector_notes=request.inspection.inspector_notes,
    )
    db.add(inspection_detail)
    await db.flush()

    # Generate QR code and upload to S3
    qr_url = hash_record["verification_url"]
    qr_s3_url = await generate_qr_code(
        data=qr_url,
        dcp_id=hash_record["dcp_id"]
    )

    return {
        "dcp_id": hash_record["dcp_id"],
        "vin": request.vehicle.vin,
        "make": request.vehicle.make,
        "model": request.vehicle.model,
        "year": request.vehicle.year,
        "score": request.inspection.score,
        "grade": grade,
        "status": "VERIFIED",
        "auditor_id": request.auditor_id,
        "issued_at": hash_record["issued_at"],
        "warranty_expiry": warranty_expiry,
        "verification_url": qr_url,
        "qr_code_url": qr_s3_url,
        "hash": hash_record["hash"],
        "hash_algorithm": "SHA-256",
    }


async def verify_dcp(
    dcp_id: str,
    db: AsyncSession,
    requester_ip: Optional[str] = None,
    method: str = "API"
) -> dict:
    """
    Verify a DCP record.
    Fetches hash from ledger, recomputes, compares.
    Logs every verification attempt.
    """

    # Fetch DCP record
    result = await db.execute(
        select(DCPRecord).where(DCPRecord.dcp_id == dcp_id)
    )
    dcp = result.scalar_one_or_none()

    if not dcp:
        return {"error": "DCP not found", "dcp_id": dcp_id}

    # Fetch hash from ledger
    hash_result = await db.execute(
        select(DCPHashLedger).where(DCPHashLedger.dcp_id == dcp_id)
    )
    hash_record = hash_result.scalar_one_or_none()

    if not hash_record:
        return {"error": "Hash record not found", "dcp_id": dcp_id}

    # Fetch inspection details
    inspection_result = await db.execute(
        select(InspectionDetail).where(InspectionDetail.dcp_id == dcp_id)
    )
    inspection = inspection_result.scalar_one_or_none()

    # Verify the hash
    verification = verify_dcp_hash(
        stored_hash=hash_record.hash,
        stored_payload=hash_record.payload_json
    )

    # Log this verification
    log_entry = VerificationLog(
        dcp_id=dcp_id,
        verified_by_ip=requester_ip,
        result=verification["is_valid"],
        method=method
    )
    db.add(log_entry)

    return {
        "dcp_id": dcp_id,
        "vin": dcp.vin,
        "make": dcp.make,
        "model": dcp.model,
        "year": str(dcp.year),
        "colour": dcp.colour,
        "score": dcp.score,
        "grade": dcp.grade,
        "status": dcp.status,
        "issued_at": dcp.issued_at,
        "warranty_expiry": dcp.warranty_expiry,
        "issuer": "The Automat Hub Ltd",
        "auditor_id": dcp.auditor_id,
        # Verification result
        **verification,
        # Inspection summary
        "obd2_status": inspection.obd2_status if inspection else None,
        "engine_compression": inspection.engine_compression if inspection else None,
        "frame_alignment": inspection.frame_alignment if inspection else None,
        "accident_history": inspection.accident_history_indicators if inspection else None,
        "ai_condition_grade": inspection.ai_condition_grade if inspection else None,
    }


async def get_vehicle_history(vin: str, db: AsyncSession) -> dict:
    """
    Get full DCP history for a VIN.
    This is the embryonic form of the Condition Registry.
    """
    result = await db.execute(
        select(DCPRecord)
        .where(DCPRecord.vin == vin.upper())
        .order_by(desc(DCPRecord.issued_at))
    )
    dcps = result.scalars().all()

    return {
        "vin": vin.upper(),
        "total_inspections": len(dcps),
        "dcps": dcps
    }
