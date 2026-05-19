"""
routers/admin.py
Admin dashboard endpoints — internal Automat Hub use only.

Admin can:
- View all DCPs, escrows, users
- Approve/suspend workshops
- Manage reseller API keys
- View platform revenue and metrics
- Manage subscriptions
- Override escrow disputes
- View all vehicle alerts
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.dcp import DCPRecord, VerificationLog
from backend.models.escrow import EscrowDeal
from backend.models.fleet import TrackedVehicle, HourlyScan, VehicleAlert
from backend.models.workshop import Workshop, RepairJob
from backend.models.user import User, ResellerAPIKey, Subscription

router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


async def require_admin(current_user: dict = Depends(get_current_user)):
    """Dependency: reject non-admin users."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── PLATFORM OVERVIEW ────────────────────────────────────────

@router.get("/overview", response_model=dict)
async def platform_overview(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """
    Complete platform metrics dashboard.
    Revenue, users, DCPs, escrows, workshops.
    """
    now = datetime.now(timezone.utc)
    this_month = now.replace(day=1, hour=0, minute=0, second=0)
    last_30_days = now - timedelta(days=30)

    # DCP stats
    total_dcps = await db.scalar(select(func.count(DCPRecord.id)))
    dcps_this_month = await db.scalar(
        select(func.count(DCPRecord.id))
        .where(DCPRecord.issued_at >= this_month)
    )

    # Escrow stats
    total_escrow_volume = await db.scalar(
        select(func.sum(EscrowDeal.amount_usd))
        .where(EscrowDeal.status == "COMPLETED")
    ) or 0

    total_platform_fees = await db.scalar(
        select(func.sum(EscrowDeal.platform_fee_amount))
        .where(EscrowDeal.status == "COMPLETED")
    ) or 0

    active_escrows = await db.scalar(
        select(func.count(EscrowDeal.id))
        .where(EscrowDeal.status.in_(["INITIATED", "FUNDED", "DCP_MATCHED"]))
    )

    # User stats
    total_users = await db.scalar(select(func.count(User.id)))
    active_subscriptions = await db.scalar(
        select(func.count(User.id))
        .where(User.subscription_status == "active")
    )

    # Vehicle stats
    total_tracked = await db.scalar(select(func.count(TrackedVehicle.id)))
    critical_vehicles = await db.scalar(
        select(func.count(TrackedVehicle.id))
        .where(TrackedVehicle.status == "critical")
    )

    # Workshop stats
    active_workshops = await db.scalar(
        select(func.count(Workshop.id))
        .where(Workshop.status == "active")
    )
    pending_workshops = await db.scalar(
        select(func.count(Workshop.id))
        .where(Workshop.status == "pending_approval")
    )

    # Scans today
    today_start = now.replace(hour=0, minute=0, second=0)
    scans_today = await db.scalar(
        select(func.count(HourlyScan.id))
        .where(HourlyScan.scanned_at >= today_start)
    )

    return {
        "success": True,
        "generated_at": now.isoformat(),
        "dcps": {
            "total": total_dcps,
            "this_month": dcps_this_month,
        },
        "escrow": {
            "total_volume_usd": float(total_escrow_volume),
            "total_fees_usd": float(total_platform_fees),
            "active_escrows": active_escrows,
        },
        "users": {
            "total": total_users,
            "active_subscriptions": active_subscriptions,
        },
        "fleet": {
            "total_tracked_vehicles": total_tracked,
            "critical_vehicles": critical_vehicles,
            "scans_today": scans_today,
        },
        "workshops": {
            "active": active_workshops,
            "pending_approval": pending_workshops,
        }
    }


# ── USER MANAGEMENT ──────────────────────────────────────────

@router.get("/users", response_model=dict)
async def list_users(
    role: Optional[str] = None,
    subscription: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """List all users with filters."""
    query = select(User).order_by(desc(User.created_at))

    if role:
        query = query.where(User.role == role)
    if subscription:
        query = query.where(User.subscription_plan == subscription)

    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "success": True,
        "page": page,
        "users": [
            {
                "user_id": u.user_id,
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "role": u.role,
                "subscription_plan": u.subscription_plan,
                "subscription_status": u.subscription_status,
                "vehicle_slots": u.vehicle_slots,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat()
            }
            for u in users
        ]
    }


@router.post("/users/{user_id}/suspend", response_model=dict)
async def suspend_user(
    user_id: str,
    reason: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Suspend a user account."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    return {"success": True, "message": f"User {user_id} suspended. Reason: {reason}"}


# ── DCP MANAGEMENT ───────────────────────────────────────────

@router.get("/dcps", response_model=dict)
async def list_dcps(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """List all issued DCPs."""
    result = await db.execute(
        select(DCPRecord)
        .order_by(desc(DCPRecord.issued_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    dcps = result.scalars().all()

    total = await db.scalar(select(func.count(DCPRecord.id)))

    return {
        "success": True,
        "total": total,
        "page": page,
        "dcps": [
            {
                "dcp_id": d.dcp_id,
                "vin": d.vin,
                "make": d.make,
                "model": d.model,
                "year": d.year,
                "score": d.score,
                "grade": d.grade,
                "status": d.status,
                "auditor_id": d.auditor_id,
                "issued_at": d.issued_at.isoformat()
            }
            for d in dcps
        ]
    }


# ── ESCROW MANAGEMENT ────────────────────────────────────────

@router.get("/escrows", response_model=dict)
async def list_escrows(
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """List all escrow deals."""
    query = select(EscrowDeal).order_by(desc(EscrowDeal.initiated_at))
    if status:
        query = query.where(EscrowDeal.status == status)

    result = await db.execute(query.offset((page - 1) * 50).limit(50))
    deals = result.scalars().all()

    return {
        "success": True,
        "page": page,
        "escrows": [
            {
                "escrow_id": d.escrow_id,
                "dcp_id": d.dcp_id,
                "vin": d.vin,
                "buyer_name": d.buyer_name,
                "seller_name": d.seller_name,
                "amount_usd": float(d.amount_usd),
                "status": d.status,
                "dcp_verified": d.dcp_verified,
                "initiated_at": d.initiated_at.isoformat()
            }
            for d in deals
        ]
    }


@router.post("/escrows/{escrow_id}/resolve-dispute", response_model=dict)
async def resolve_dispute(
    escrow_id: str,
    resolution: str,
    release_to: str = Query(..., regex="^(buyer|seller)$"),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Admin resolves an escrow dispute. Releases funds to buyer or seller."""
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        raise HTTPException(status_code=404, detail="Escrow not found")

    if deal.status != "DISPUTED":
        raise HTTPException(status_code=400, detail="Escrow is not in disputed state")

    deal.status = "COMPLETED" if release_to == "seller" else "REFUNDED"

    return {
        "success": True,
        "escrow_id": escrow_id,
        "resolution": resolution,
        "funds_released_to": release_to,
        "resolved_by": admin["user_id"]
    }


# ── WORKSHOP MANAGEMENT ──────────────────────────────────────

@router.get("/workshops/pending", response_model=dict)
async def pending_workshops(
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """List workshops awaiting approval."""
    result = await db.execute(
        select(Workshop)
        .where(Workshop.status == "pending_approval")
        .order_by(Workshop.registered_at)
    )
    workshops = result.scalars().all()

    return {
        "success": True,
        "pending_count": len(workshops),
        "workshops": [
            {
                "workshop_id": w.workshop_id,
                "name": w.name,
                "address": w.address,
                "state": w.state,
                "specializations": w.specializations,
                "registered_at": w.registered_at.isoformat()
            }
            for w in workshops
        ]
    }


@router.post("/workshops/{workshop_id}/approve", response_model=dict)
async def approve_workshop(
    workshop_id: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Approve a workshop application."""
    result = await db.execute(
        select(Workshop).where(Workshop.workshop_id == workshop_id)
    )
    workshop = result.scalar_one_or_none()

    if not workshop:
        raise HTTPException(status_code=404, detail="Workshop not found")

    workshop.status = "active"

    return {
        "success": True,
        "workshop_id": workshop_id,
        "message": f"{workshop.name} approved and now active in the network"
    }


@router.post("/workshops/{workshop_id}/suspend", response_model=dict)
async def suspend_workshop(
    workshop_id: str,
    reason: str,
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Suspend a workshop."""
    result = await db.execute(
        select(Workshop).where(Workshop.workshop_id == workshop_id)
    )
    workshop = result.scalar_one_or_none()

    if not workshop:
        raise HTTPException(status_code=404, detail="Workshop not found")

    workshop.status = "suspended"
    workshop.is_available = False

    return {"success": True, "workshop_id": workshop_id, "reason": reason}


# ── REVENUE REPORTING ────────────────────────────────────────

@router.get("/revenue", response_model=dict)
async def revenue_report(
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    admin: dict = Depends(require_admin)
):
    """Platform revenue breakdown."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Escrow fees
    escrow_fees = await db.scalar(
        select(func.sum(EscrowDeal.platform_fee_amount))
        .where(
            and_(
                EscrowDeal.status == "COMPLETED",
                EscrowDeal.completed_at >= since
            )
        )
    ) or 0

    # Subscription revenue (approximated from active subs)
    active_private = await db.scalar(
        select(func.count(User.id))
        .where(
            and_(
                User.subscription_plan == "private",
                User.subscription_status == "active"
            )
        )
    ) or 0

    active_fleet_vehicles = await db.scalar(
        select(func.sum(User.vehicle_slots))
        .where(
            and_(
                User.subscription_plan == "fleet",
                User.subscription_status == "active"
            )
        )
    ) or 0

    active_resellers = await db.scalar(
        select(func.count(User.id))
        .where(
            and_(
                User.subscription_plan == "reseller",
                User.subscription_status == "active"
            )
        )
    ) or 0

    # Repair job commissions
    repair_fees = await db.scalar(
        select(func.sum(RepairJob.platform_fee_ngn))
        .where(
            and_(
                RepairJob.status == "completed",
                RepairJob.completed_at >= since
            )
        )
    ) or 0

    monthly_sub_revenue = (
        active_private * 15000 +
        active_fleet_vehicles * 8000 +
        active_resellers * 50000
    )

    return {
        "success": True,
        "period_days": days,
        "revenue": {
            "escrow_fees_usd": float(escrow_fees),
            "monthly_subscriptions_ngn": monthly_sub_revenue,
            "repair_commissions_ngn": float(repair_fees),
        },
        "subscriptions": {
            "private_owners": active_private,
            "fleet_vehicles": active_fleet_vehicles,
            "resellers": active_resellers,
        }
    }
