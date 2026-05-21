"""
services/escrow_service.py
Escrow business logic.
Manages the complete escrow lifecycle from deposit to release.

CRITICAL RULE:
Funds are NEVER released unless ALL conditions are met:
1. dcp_verified = True
2. physical_delivery_confirmed = True
3. buyer_acknowledged = True

This is the protocol guarantee.
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.models.escrow import EscrowDeal, EscrowEvent, EscrowStatus
from backend.schemas.escrow import (
    CreateEscrowRequest,
    ConfirmDepositRequest,
    ConfirmDeliveryRequest,
    RaiseDisputeRequest
)
from backend.services.notification_service import (
    notify_escrow_created,
    notify_funds_received,
    notify_dcp_matched,
    notify_delivery_confirmed,
    notify_funds_released,
    notify_dispute_raised
)


PLATFORM_FEE_PERCENT = 1.5  # 1.5% transaction fee
ESCROW_EXPIRY_DAYS = 30     # Escrow expires after 30 days if uncompleted


def generate_escrow_id() -> str:
    year = datetime.now(timezone.utc).year
    suffix = str(uuid.uuid4()).replace('-', '').upper()[:8]
    return f"ESC-{year}-{suffix}"


def calculate_fees(amount_usd: Decimal) -> dict:
    fee = amount_usd * Decimal(str(PLATFORM_FEE_PERCENT / 100))
    seller_net = amount_usd - fee
    return {
        "platform_fee_percent": PLATFORM_FEE_PERCENT,
        "platform_fee_amount": round(fee, 2),
        "seller_net_amount": round(seller_net, 2)
    }


async def log_event(
    escrow_id: str,
    event_type: str,
    from_status: Optional[str],
    to_status: Optional[str],
    triggered_by: str,
    notes: Optional[str],
    db: AsyncSession,
    metadata: dict = None
):
    """Log every escrow state change. Immutable audit trail."""
    event = EscrowEvent(
        escrow_id=escrow_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        triggered_by=triggered_by,
        notes=notes,
        metadata=metadata or {}
    )
    db.add(event)


async def create_escrow(
    request: CreateEscrowRequest,
    db: AsyncSession
) -> dict:
    """
    Create a new escrow deal.
    Validates DCP exists before creating.
    Calculates fees and net amounts.
    """
    from backend.models.dcp import DCPRecord

    # ── VALIDATE DCP (Loophole 2 Fix) ─────────────────────────────
    dcp_result = await db.execute(
        select(DCPRecord).where(
            DCPRecord.dcp_id == request.dcp_id,
            DCPRecord.vin == request.vin.upper(),
            DCPRecord.status == "VERIFIED"
        )
    )
    if not dcp_result.scalar_one_or_none():
        return {"error": f"No active/verified DCP found for VIN {request.vin.upper()}"}

    escrow_id = generate_escrow_id()
    fees = calculate_fees(request.amount_usd)

    # Calculate NGN equivalent if FX rate provided
    amount_ngn = None
    if request.fx_rate:
        amount_ngn = request.amount_usd * request.fx_rate

    deal = EscrowDeal(
        escrow_id=escrow_id,
        dcp_id=request.dcp_id,
        vin=request.vin.upper(),
        buyer_name=request.buyer.name,
        buyer_email=request.buyer.email,
        buyer_phone=request.buyer.phone,
        seller_name=request.seller.name,
        seller_account=request.seller.account,
        amount_usd=request.amount_usd,
        amount_ngn=amount_ngn,
        fx_rate_at_deposit=request.fx_rate,
        platform_fee_percent=fees["platform_fee_percent"],
        platform_fee_amount=fees["platform_fee_amount"],
        seller_net_amount=fees["seller_net_amount"],
        status=EscrowStatus.INITIATED,
        initiated_at=datetime.now(timezone.utc),
        expiry_at=datetime.now(timezone.utc) + timedelta(days=ESCROW_EXPIRY_DAYS),
        notes=request.notes
    )
    db.add(deal)

    await log_event(
        escrow_id=escrow_id,
        event_type="ESCROW_CREATED",
        from_status=None,
        to_status=EscrowStatus.INITIATED,
        triggered_by="SYSTEM",
        notes=f"Escrow created for VIN {request.vin}",
        db=db
    )

    await db.flush()

    # Notify buyer with payment instructions
    await notify_escrow_created(
        buyer_name=request.buyer.name,
        buyer_phone=request.buyer.phone,
        escrow_id=escrow_id,
        amount_usd=float(request.amount_usd),
        vin=request.vin
    )

    return {
        "escrow_id": escrow_id,
        "dcp_id": request.dcp_id,
        "vin": request.vin.upper(),
        "buyer_name": request.buyer.name,
        "seller_name": request.seller.name,
        "amount_usd": float(request.amount_usd),
        "platform_fee_percent": fees["platform_fee_percent"],
        "platform_fee_amount": float(fees["platform_fee_amount"]),
        "seller_net_amount": float(fees["seller_net_amount"]),
        "status": EscrowStatus.INITIATED,
        "expiry_at": deal.expiry_at,
        "message": "Escrow created. Awaiting buyer deposit."
    }


async def confirm_deposit(
    request: ConfirmDepositRequest,
    db: AsyncSession
) -> dict:
    """
    Confirm buyer has deposited funds.
    Triggered after Paystack webhook confirms payment.
    Moves status from INITIATED → FUNDED.
    """
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == request.escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        return {"error": "Escrow not found"}

    if deal.status != EscrowStatus.INITIATED:
        return {"error": f"Cannot confirm deposit. Current status: {deal.status}"}

    prev_status = deal.status
    deal.status = EscrowStatus.FUNDED
    deal.funded_at = datetime.now(timezone.utc)
    deal.payment_reference = request.payment_reference
    deal.payment_channel = request.payment_channel

    await log_event(
        escrow_id=request.escrow_id,
        event_type="FUNDS_DEPOSITED",
        from_status=prev_status,
        to_status=EscrowStatus.FUNDED,
        triggered_by="PAYSTACK_WEBHOOK",
        notes=f"Payment reference: {request.payment_reference}",
        db=db,
        metadata={"payment_reference": request.payment_reference}
    )

    # Notify buyer and seller
    await notify_funds_received(
        buyer_name=deal.buyer_name,
        buyer_phone=deal.buyer_phone,
        escrow_id=request.escrow_id,
        amount_usd=float(deal.amount_usd)
    )

    return {
        "escrow_id": request.escrow_id,
        "status": EscrowStatus.FUNDED,
        "message": "Funds received and held in escrow. DCP verification next.",
        "funded_at": deal.funded_at
    }


async def confirm_dcp_match(
    escrow_id: str,
    auditor_id: str,
    db: AsyncSession
) -> dict:
    """
    Automat Hub confirms physical vehicle matches DCP.
    Only Automat Hub (auditor) can trigger this.
    Moves status from FUNDED → DCP_MATCHED.

    This is the critical verification step.
    Inspector physically confirms vehicle at hub matches
    the Digital Condition Passport on file.
    """
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        return {"error": "Escrow not found"}

    if deal.status != EscrowStatus.FUNDED:
        return {"error": f"Cannot confirm DCP match. Current status: {deal.status}"}

    prev_status = deal.status
    deal.status = EscrowStatus.DCP_MATCHED
    deal.dcp_verified = True
    deal.dcp_matched_at = datetime.now(timezone.utc)

    await log_event(
        escrow_id=escrow_id,
        event_type="DCP_MATCHED",
        from_status=prev_status,
        to_status=EscrowStatus.DCP_MATCHED,
        triggered_by=auditor_id,
        notes="Physical vehicle confirmed to match Digital Condition Passport",
        db=db
    )

    await notify_dcp_matched(
        buyer_name=deal.buyer_name,
        buyer_phone=deal.buyer_phone,
        escrow_id=escrow_id,
        vin=deal.vin
    )

    return {
        "escrow_id": escrow_id,
        "status": EscrowStatus.DCP_MATCHED,
        "dcp_verified": True,
        "message": "Vehicle confirmed to match Digital Condition Passport. Awaiting delivery confirmation.",
        "dcp_matched_at": deal.dcp_matched_at
    }


async def confirm_delivery(
    request: ConfirmDeliveryRequest,
    db: AsyncSession
) -> dict:
    """
    Buyer confirms physical delivery of vehicle.
    Only buyer can trigger this.
    Moves status DCP_MATCHED → DELIVERY_CONFIRMED.
    Then checks if all conditions are met → releases funds.

    THIS IS THE RELEASE TRIGGER.
    Funds only move when this is called AND dcp_verified is True.
    """
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == request.escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        return {"error": "Escrow not found"}

    if deal.status != EscrowStatus.DCP_MATCHED:
        return {"error": f"Cannot confirm delivery. Current status: {deal.status}"}

    prev_status = deal.status
    deal.physical_delivery_confirmed = True
    deal.buyer_acknowledged = True
    deal.delivery_confirmed_at = datetime.now(timezone.utc)
    deal.status = EscrowStatus.DELIVERY_CONFIRMED

    await log_event(
        escrow_id=request.escrow_id,
        event_type="DELIVERY_CONFIRMED",
        from_status=prev_status,
        to_status=EscrowStatus.DELIVERY_CONFIRMED,
        triggered_by="BUYER",
        notes=request.notes or "Buyer confirmed vehicle delivery",
        db=db
    )

    await notify_delivery_confirmed(
        buyer_name=deal.buyer_name,
        buyer_phone=deal.buyer_phone,
        escrow_id=request.escrow_id
    )

    # Check all conditions — release funds if all met
    if (
        deal.dcp_verified and
        deal.physical_delivery_confirmed and
        deal.buyer_acknowledged
    ):
        return await _release_funds(deal, db)

    return {
        "escrow_id": request.escrow_id,
        "status": deal.status,
        "message": "Delivery confirmed. Processing fund release.",
    }


async def _release_funds(deal: EscrowDeal, db: AsyncSession) -> dict:
    """
    Internal — release funds to seller.
    Called only when ALL conditions are verified.

    CRITICAL: All three conditions must be True:
    1. dcp_verified
    2. physical_delivery_confirmed
    3. buyer_acknowledged

    In production: trigger Paystack transfer to seller here.
    """

    # Safety check — never release without all conditions
    if not (deal.dcp_verified and deal.physical_delivery_confirmed and deal.buyer_acknowledged):
        return {"error": "Cannot release funds — conditions not fully met"}

    prev_status = deal.status
    deal.status = EscrowStatus.COMPLETED
    deal.completed_at = datetime.now(timezone.utc)

    from backend.models.fleet import TrackedVehicle
    from backend.models.user import User

    # Transfer vehicle ownership to buyer
    vehicle = await db.scalar(select(TrackedVehicle).where(TrackedVehicle.vin == deal.vin))
    buyer = await db.scalar(select(User).where(User.email == deal.buyer_email))

    if vehicle and buyer:
        vehicle.owner_id = buyer.user_id
        vehicle.fleet_id = None # Clear any previous fleet associations

    await log_event(
        escrow_id=deal.escrow_id,
        event_type="FUNDS_RELEASED",
        from_status=prev_status,
        to_status=EscrowStatus.COMPLETED,
        triggered_by="SYSTEM",
        notes=f"Funds released to seller. Net amount: ${deal.seller_net_amount}",
        db=db,
        metadata={
            "seller_net_amount": str(deal.seller_net_amount),
            "platform_fee": str(deal.platform_fee_amount),
            "conditions": {
                "dcp_verified": deal.dcp_verified,
                "delivery_confirmed": deal.physical_delivery_confirmed,
                "buyer_acknowledged": deal.buyer_acknowledged
            }
        }
    )

    # TODO: Trigger Paystack transfer to seller account
    # paystack.transfer(deal.seller_account, deal.seller_net_amount)

    await notify_funds_released(
        buyer_name=deal.buyer_name,
        buyer_phone=deal.buyer_phone,
        seller_name=deal.seller_name,
        escrow_id=deal.escrow_id,
        amount=float(deal.seller_net_amount)
    )

    return {
        "escrow_id": deal.escrow_id,
        "status": EscrowStatus.COMPLETED,
        "seller_net_amount": float(deal.seller_net_amount),
        "platform_fee": float(deal.platform_fee_amount),
        "completed_at": deal.completed_at,
        "message": "Transaction complete. Funds released to seller."
    }


async def raise_dispute(
    request: RaiseDisputeRequest,
    db: AsyncSession
) -> dict:
    """
    Buyer raises a dispute.
    Freezes escrow. Automat Hub arbitrates.
    Funds held until resolution.
    """
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == request.escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        return {"error": "Escrow not found"}

    if deal.status in [EscrowStatus.COMPLETED, EscrowStatus.REFUNDED]:
        return {"error": f"Cannot dispute a {deal.status} escrow"}

    prev_status = deal.status
    deal.status = EscrowStatus.DISPUTED
    deal.dispute_reason = request.reason

    await log_event(
        escrow_id=request.escrow_id,
        event_type="DISPUTE_RAISED",
        from_status=prev_status,
        to_status=EscrowStatus.DISPUTED,
        triggered_by="BUYER",
        notes=request.reason,
        db=db
    )

    await notify_dispute_raised(
        buyer_name=deal.buyer_name,
        escrow_id=request.escrow_id,
        reason=request.reason
    )

    return {
        "escrow_id": request.escrow_id,
        "status": EscrowStatus.DISPUTED,
        "message": "Dispute raised. Automat Hub will contact you within 24 hours. Funds are frozen.",
        "contact": "support@automatcorp.org.ng"
    }


async def get_escrow_status(escrow_id: str, db: AsyncSession) -> dict:
    """Get current escrow status with full event history."""
    result = await db.execute(
        select(EscrowDeal).where(EscrowDeal.escrow_id == escrow_id)
    )
    deal = result.scalar_one_or_none()

    if not deal:
        return {"error": "Escrow not found"}

    return deal
