"""
routers/reseller.py
Reseller API — licensed dealers access DCP issuance,
escrow rails, and condition registry via API keys.

RESELLER PRICING:
- ₦50,000/month base subscription
- ₦5,000 per DCP issued
- 1.5% escrow transaction fee
- Usage tracked per API key
"""

import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.user import ResellerAPIKey, User
from backend.services.dcp_service import issue_dcp, verify_dcp
from backend.schemas.dcp import IssueDCPRequest

router = APIRouter(prefix="/reseller", tags=["Reseller API"])

RESELLER_DCP_FEE_NGN = 5000
RESELLER_MONTHLY_FEE_NGN = 50000


def generate_api_key() -> tuple[str, str]:
    """Generate a secure API key. Returns (full_key, prefix)."""
    key = f"ATH-{secrets.token_hex(28).upper()}"
    prefix = key[:12]
    return key, prefix


def hash_api_key(key: str) -> str:
    """Hash API key for storage. Never store raw keys."""
    return hashlib.sha256(key.encode()).hexdigest()


async def validate_reseller_key(
    x_api_key: str = Header(..., description="Reseller API key"),
    db: AsyncSession = Depends(get_db)
) -> ResellerAPIKey:
    """
    Dependency: validate reseller API key.
    Checks: key exists, is active, within rate limits.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")

    # Look up by hashed key
    key_hash = hash_api_key(x_api_key)

    result = await db.execute(
        select(ResellerAPIKey).where(
            ResellerAPIKey.api_key == key_hash
        )
    )
    key_record = result.scalar_one_or_none()

    if not key_record or not key_record.is_active:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key")

    # Check hourly rate limit
    now = datetime.now(timezone.utc)
    if key_record.last_reset_hour:
        hours_elapsed = (now - key_record.last_reset_hour).total_seconds() / 3600
        if hours_elapsed >= 1:
            key_record.current_hour_count = 0
            key_record.last_reset_hour = now

    if key_record.current_hour_count >= key_record.requests_per_hour:
        raise HTTPException(
            status_code=429,
            detail=f"Hourly rate limit exceeded ({key_record.requests_per_hour}/hour). Try again later."
        )

    # Increment usage
    key_record.current_hour_count += 1
    key_record.total_requests += 1
    key_record.last_used_at = now

    return key_record


# ── KEY MANAGEMENT ───────────────────────────────────────────

@router.post("/keys/generate", response_model=dict)
async def generate_reseller_key(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Generate a new reseller API key.
    Only available to reseller role users.
    Key is shown ONCE — store it securely.
    """
    # Check existing key
    result = await db.execute(
        select(ResellerAPIKey).where(
            ResellerAPIKey.user_id == current_user["user_id"]
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.is_active:
        raise HTTPException(
            status_code=400,
            detail="Active API key exists. Revoke it before generating a new one."
        )

    full_key, prefix = generate_api_key()
    key_hash = hash_api_key(full_key)

    key_record = ResellerAPIKey(
        user_id=current_user["user_id"],
        api_key=key_hash,
        api_key_prefix=prefix,
        requests_per_hour=100,
        requests_per_day=1000,
        last_reset_hour=datetime.now(timezone.utc),
        last_reset_day=datetime.now(timezone.utc)
    )
    db.add(key_record)
    await db.flush()

    return {
        "success": True,
        "api_key": full_key,  # Shown ONCE — store securely
        "prefix": prefix,
        "warning": "This key will not be shown again. Store it securely.",
        "rate_limits": {
            "requests_per_hour": 100,
            "requests_per_day": 1000
        },
        "pricing": {
            "monthly_base_ngn": RESELLER_MONTHLY_FEE_NGN,
            "per_dcp_ngn": RESELLER_DCP_FEE_NGN,
            "escrow_fee_percent": 1.5
        }
    }


@router.get("/keys/status", response_model=dict)
async def get_key_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Get API key usage statistics."""
    result = await db.execute(
        select(ResellerAPIKey).where(
            ResellerAPIKey.user_id == current_user["user_id"]
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="No API key found")

    return {
        "success": True,
        "prefix": key.api_key_prefix,
        "is_active": key.is_active,
        "usage": {
            "total_requests": key.total_requests,
            "total_dcps_issued": key.total_dcps_issued,
            "current_hour_requests": key.current_hour_count,
            "hourly_limit": key.requests_per_hour
        },
        "permissions": {
            "can_issue_dcp": key.can_issue_dcp,
            "can_use_escrow": key.can_use_escrow,
            "can_access_registry": key.can_access_registry
        },
        "last_used": key.last_used_at.isoformat() if key.last_used_at else None
    }


@router.post("/keys/revoke", response_model=dict)
async def revoke_key(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Revoke the active API key."""
    result = await db.execute(
        select(ResellerAPIKey).where(
            ResellerAPIKey.user_id == current_user["user_id"]
        )
    )
    key = result.scalar_one_or_none()

    if not key:
        raise HTTPException(status_code=404, detail="No API key found")

    key.is_active = False

    return {"success": True, "message": "API key revoked"}


# ── RESELLER DCP API ─────────────────────────────────────────

@router.post("/dcp/issue", response_model=dict)
async def reseller_issue_dcp(
    request: IssueDCPRequest,
    db: AsyncSession = Depends(get_db),
    key_record: ResellerAPIKey = Depends(validate_reseller_key)
):
    """
    Issue a DCP via reseller API key.
    Charges ₦5,000 per DCP issued.
    Billed monthly from reseller's Paystack subscription.
    """
    if not key_record.can_issue_dcp:
        raise HTTPException(
            status_code=403,
            detail="DCP issuance not enabled for this API key"
        )

    result = await issue_dcp(request, db)

    # Track usage
    key_record.total_dcps_issued += 1

    # TODO: Log billable event for monthly invoice
    # await log_billable_event(key_record.user_id, "dcp_issued", RESELLER_DCP_FEE_NGN)

    return {
        "success": True,
        "data": result,
        "billing": {
            "event": "dcp_issued",
            "fee_ngn": RESELLER_DCP_FEE_NGN,
            "note": "Billed on monthly invoice"
        }
    }


@router.get("/dcp/verify/{dcp_id}", response_model=dict)
async def reseller_verify_dcp(
    dcp_id: str,
    db: AsyncSession = Depends(get_db),
    key_record: ResellerAPIKey = Depends(validate_reseller_key)
):
    """Verify a DCP via reseller API. Free — no charge."""
    result = await verify_dcp(dcp_id=dcp_id, db=db, method="RESELLER_API")

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {"success": True, "data": result}


@router.get("/vehicle/{vin}/history", response_model=dict)
async def reseller_vehicle_history(
    vin: str,
    db: AsyncSession = Depends(get_db),
    key_record: ResellerAPIKey = Depends(validate_reseller_key)
):
    """
    Get DCP history for a VIN via reseller API.
    Requires registry access permission.
    """
    if not key_record.can_access_registry:
        raise HTTPException(
            status_code=403,
            detail="Condition Registry access not enabled. Contact support to upgrade."
        )

    from backend.services.dcp_service import get_vehicle_history
    result = await get_vehicle_history(vin, db)

    return {"success": True, "data": result}
