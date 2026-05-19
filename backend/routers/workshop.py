"""
routers/workshop.py
Workshop and mechanic endpoints.

Workshop owner can:
- Register workshop
- Manage mechanics
- View and accept repair jobs
- Submit pre/post fix scans
- Track earnings

Mechanic can:
- View assigned jobs
- Submit arrival scan
- Submit post-fix scan to close job
"""

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.workshop import Workshop, Mechanic, RepairJob, JobStatus
from backend.models.fleet import TrackedVehicle, VehicleAlert
from backend.services.scan_service import process_hourly_scan

router = APIRouter(prefix="/workshop", tags=["Workshop & Repairs"])


# ── WORKSHOP REGISTRATION ────────────────────────────────────

@router.post("/register", response_model=dict)
async def register_workshop(
    name: str,
    address: str,
    state: str,
    lga: str,
    latitude: float,
    longitude: float,
    specializations: list,
    open_time: str = "08:00",
    close_time: str = "18:00",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Register a new workshop.
    Goes into pending_approval state.
    Admin approves before workshop goes live.
    No cost to register. 8% commission on jobs.
    """
    workshop_id = f"WS-{str(uuid.uuid4())[:8].upper()}"

    workshop = Workshop(
        workshop_id=workshop_id,
        owner_user_id=current_user["user_id"],
        name=name,
        address=address,
        state=state,
        lga=lga,
        latitude=latitude,
        longitude=longitude,
        specializations=specializations,
        open_time=open_time,
        close_time=close_time,
        open_days=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"],
        status="pending_approval"
    )
    db.add(workshop)
    await db.flush()

    return {
        "success": True,
        "workshop_id": workshop_id,
        "status": "pending_approval",
        "message": "Workshop registered. Automat Hub will review and approve within 48 hours.",
        "commission_rate": "8% of repair revenue",
        "note": "Free to join. You earn 92% of every job completed."
    }


@router.post("/mechanic/add", response_model=dict)
async def add_mechanic(
    workshop_id: str,
    full_name: str,
    phone: str,
    specialization: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Add a mechanic to the workshop."""
    mechanic_id = f"MCH-{str(uuid.uuid4())[:8].upper()}"

    # Create user account for mechanic
    mechanic = Mechanic(
        mechanic_id=mechanic_id,
        user_id=current_user["user_id"],
        workshop_id=workshop_id,
        full_name=full_name,
        phone=phone,
        specialization=specialization
    )
    db.add(mechanic)

    return {
        "success": True,
        "mechanic_id": mechanic_id,
        "message": f"Mechanic {full_name} added to workshop"
    }


# ── JOB MANAGEMENT ───────────────────────────────────────────

@router.get("/jobs", response_model=dict)
async def get_workshop_jobs(
    workshop_id: str,
    status: str = Query(default="all"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get all repair jobs for a workshop."""
    query = select(RepairJob).where(RepairJob.workshop_id == workshop_id)

    if status != "all":
        query = query.where(RepairJob.status == status)

    query = query.order_by(desc(RepairJob.created_at)).limit(100)
    result = await db.execute(query)
    jobs = result.scalars().all()

    return {
        "success": True,
        "jobs": [
            {
                "job_id": j.job_id,
                "vehicle_id": j.vehicle_id,
                "vin": j.vin,
                "fault_codes": j.fault_codes,
                "fault_description": j.fault_description,
                "severity": j.severity,
                "status": j.status,
                "quoted_amount_ngn": float(j.quoted_amount_ngn) if j.quoted_amount_ngn else None,
                "payment_status": j.payment_status,
                "created_at": j.created_at.isoformat()
            }
            for j in jobs
        ]
    }


@router.post("/jobs/{job_id}/vehicle-arrived", response_model=dict)
async def confirm_vehicle_arrival(
    job_id: str,
    mechanic_id: str,
    initial_scan_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Mechanic confirms vehicle has arrived at workshop.
    Performs arrival OBD scan to confirm faults.
    """
    result = await db.execute(select(RepairJob).where(RepairJob.job_id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Perform arrival scan
    scan_result = await process_hourly_scan(
        vehicle_id=job.vehicle_id,
        scan_data={**initial_scan_data, "scan_method": "mechanic_arrival"},
        db=db
    )

    job.status = JobStatus.VEHICLE_ARRIVED
    job.assigned_mechanic_id = mechanic_id
    job.vehicle_arrived_at = datetime.now(timezone.utc)
    job.pre_fix_scan_id = scan_result.get("scan_id")

    # Update vehicle status
    vehicle_result = await db.execute(
        select(TrackedVehicle).where(TrackedVehicle.vehicle_id == job.vehicle_id)
    )
    vehicle = vehicle_result.scalar_one_or_none()
    if vehicle:
        vehicle.status = "in_workshop"
        vehicle.assigned_workshop_id = job.workshop_id
        vehicle.workshop_job_id = job_id

    return {
        "success": True,
        "job_id": job_id,
        "status": "vehicle_arrived",
        "arrival_scan_id": scan_result.get("scan_id"),
        "confirmed_faults": scan_result.get("fault_codes", [])
    }


@router.post("/jobs/{job_id}/submit-quote", response_model=dict)
async def submit_repair_quote(
    job_id: str,
    diagnosis_notes: str,
    quoted_amount_ngn: float,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Workshop submits repair quote to vehicle owner."""
    result = await db.execute(select(RepairJob).where(RepairJob.job_id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    platform_fee = quoted_amount_ngn * 0.08
    workshop_net = quoted_amount_ngn - platform_fee

    job.status = JobStatus.QUOTE_SENT
    job.diagnosis_notes = diagnosis_notes
    job.quoted_amount_ngn = quoted_amount_ngn
    job.platform_fee_ngn = platform_fee
    job.workshop_net_ngn = workshop_net
    job.diagnosis_completed_at = datetime.now(timezone.utc)

    # TODO: Send quote to vehicle owner via push + SMS

    return {
        "success": True,
        "job_id": job_id,
        "quoted_amount_ngn": quoted_amount_ngn,
        "platform_fee_ngn": platform_fee,
        "workshop_net_ngn": workshop_net,
        "message": "Quote sent to vehicle owner for approval"
    }


@router.post("/jobs/{job_id}/final-scan", response_model=dict)
async def submit_final_scan(
    job_id: str,
    post_fix_scan_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Mechanic submits post-fix OBD scan.
    This is the protocol verification that fix is complete.
    If scan shows clear — job closes and payment releases.
    This scan is recorded permanently on the vehicle DCP.
    """
    result = await db.execute(select(RepairJob).where(RepairJob.job_id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Perform post-fix scan
    scan_result = await process_hourly_scan(
        vehicle_id=job.vehicle_id,
        scan_data={**post_fix_scan_data, "scan_method": "post_fix_verification"},
        db=db
    )

    remaining_faults = scan_result.get("fault_codes", [])
    original_faults = set(job.fault_codes or [])
    fixed_faults = original_faults - set(remaining_faults)
    unfixed_faults = original_faults.intersection(set(remaining_faults))

    fix_verified = len(unfixed_faults) == 0

    job.post_fix_scan_id = scan_result.get("scan_id")
    job.fix_verified = fix_verified
    job.final_scan_at = datetime.now(timezone.utc)

    if fix_verified:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.final_amount_ngn = job.quoted_amount_ngn

        # Update vehicle status back to healthy
        vehicle_result = await db.execute(
            select(TrackedVehicle).where(TrackedVehicle.vehicle_id == job.vehicle_id)
        )
        vehicle = vehicle_result.scalar_one_or_none()
        if vehicle:
            vehicle.status = "healthy"
            vehicle.has_active_faults = False
            vehicle.active_fault_codes = remaining_faults
            vehicle.assigned_workshop_id = None
            vehicle.workshop_job_id = None

        # TODO: Release payment to workshop via Paystack transfer

        return {
            "success": True,
            "job_id": job_id,
            "fix_verified": True,
            "status": "completed",
            "faults_fixed": list(fixed_faults),
            "remaining_faults": remaining_faults,
            "payment_status": "releasing",
            "workshop_net_ngn": float(job.workshop_net_ngn or 0),
            "message": "Fix verified. Payment releasing to workshop."
        }
    else:
        job.status = JobStatus.REPAIR_IN_PROGRESS

        return {
            "success": True,
            "job_id": job_id,
            "fix_verified": False,
            "status": "repair_in_progress",
            "faults_fixed": list(fixed_faults),
            "unfixed_faults": list(unfixed_faults),
            "message": f"Fix incomplete. {len(unfixed_faults)} fault(s) still present. Continue repair."
        }
