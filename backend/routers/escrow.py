"""
routers/escrow.py
All Escrow API endpoints.

ENDPOINTS:
POST /escrow/create              — Create new escrow deal
POST /escrow/deposit/confirm     — Confirm buyer deposit (Paystack webhook)
POST /escrow/dcp/confirm         — Confirm DCP match (Automat Hub only)
POST /escrow/delivery/confirm    — Confirm delivery (buyer only)
POST /escrow/dispute             — Raise dispute (buyer only)
GET  /escrow/{escrow_id}         — Get escrow status
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from backend.core.database import get_db
from backend.core.security import get_current_user, verify_api_key
from backend.schemas.escrow import (
    CreateEscrowRequest,
    ConfirmDepositRequest,
    ConfirmDeliveryRequest,
    RaiseDisputeRequest
)
from backend.services.escrow_service import (
    create_escrow,
    confirm_deposit,
    confirm_dcp_match,
    confirm_delivery,
    raise_dispute,
    get_escrow_status
)

router = APIRouter(prefix="/escrow", tags=["Escrow & Settlement"])


@router.post(
    "/create",
    response_model=dict,
    summary="Create a new escrow deal",
    description="Creates escrow for a vehicle transaction. DCP must exist."
)
async def create_escrow_endpoint(
    request: CreateEscrowRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Create escrow deal.
    
    - Links to existing DCP record
    - Calculates platform fee (1.5%)
    - Notifies buyer with payment instructions
    - Returns escrow ID for tracking
    """
    result = await create_escrow(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "message": "Escrow created. Awaiting buyer deposit.",
        "data": result
    }


@router.post(
    "/deposit/confirm",
    response_model=dict,
    summary="Confirm buyer deposit",
    description="Called by Paystack webhook when payment is confirmed."
)
async def confirm_deposit_endpoint(
    request: ConfirmDepositRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """
    Confirm funds received.
    
    - Triggered by Paystack webhook
    - Moves status INITIATED → FUNDED
    - Notifies buyer funds are held
    """
    result = await confirm_deposit(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.post(
    "/dcp/confirm",
    response_model=dict,
    summary="Confirm physical vehicle matches DCP",
    description="Automat Hub inspector confirms vehicle matches Digital Condition Passport. Requires inspector auth."
)
async def confirm_dcp_match_endpoint(
    escrow_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    DCP match confirmation.
    
    - Only Automat Hub inspectors can trigger this
    - Physically confirms vehicle at hub matches DCP
    - Moves status FUNDED → DCP_MATCHED
    - This is the protocol guarantee
    """
    result = await confirm_dcp_match(
        escrow_id=escrow_id,
        auditor_id=current_user["user_id"],
        db=db
    )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.post(
    "/delivery/confirm",
    response_model=dict,
    summary="Buyer confirms vehicle delivery",
    description="Buyer confirms they have received the vehicle. Triggers fund release."
)
async def confirm_delivery_endpoint(
    request: ConfirmDeliveryRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Delivery confirmation and fund release.
    
    - Buyer confirms physical receipt of vehicle
    - System checks ALL conditions are met
    - If all conditions met → funds released to seller
    - Moves status DCP_MATCHED → COMPLETED
    
    CONDITIONS REQUIRED FOR RELEASE:
    1. dcp_verified = True (set by Automat Hub inspector)
    2. physical_delivery_confirmed = True (set here by buyer)
    3. buyer_acknowledged = True (set here by buyer)
    """
    result = await confirm_delivery(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.post(
    "/dispute",
    response_model=dict,
    summary="Raise a dispute",
    description="Buyer raises a dispute. Freezes funds. Automat Hub arbitrates."
)
async def raise_dispute_endpoint(
    request: RaiseDisputeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Raise a dispute.
    
    - Buyer can dispute at any point before COMPLETED
    - Funds are frozen immediately
    - Automat Hub arbitrates within 24 hours
    """
    result = await raise_dispute(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.get(
    "/{escrow_id}",
    response_model=dict,
    summary="Get escrow status",
    description="Get current escrow status with full event history."
)
async def get_escrow_status_endpoint(
    escrow_id: str,
    db: AsyncSession = Depends(get_db)
):
    result = await get_escrow_status(escrow_id, db)

    if isinstance(result, dict) and "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "success": True,
        "data": result
    }
