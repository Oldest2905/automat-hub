"""
routers/webhooks.py
Paystack webhook handler.
Listens for payment events and triggers escrow updates.

Paystack sends a webhook when:
- Payment is successful → trigger escrow deposit confirmation
- Transfer is successful → log fund release confirmation
"""

import hmac
import hashlib
import json
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.schemas.escrow import ConfirmDepositRequest
from backend.services.escrow_service import confirm_deposit
from backend.config import settings

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_paystack_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Paystack webhook signature.
    Paystack signs every webhook with HMAC-SHA512.
    Never process a webhook without verifying this.
    """
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post(
    "/paystack",
    summary="Paystack webhook receiver",
    description="Receives and processes Paystack payment events."
)
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Process Paystack webhooks.

    Events handled:
    - charge.success → confirm escrow deposit
    - transfer.success → log fund release
    - transfer.failed → alert operations team
    """
    # Get raw body for signature verification
    payload = await request.body()
    signature = request.headers.get("x-paystack-signature", "")

    # Verify signature — reject if invalid
    if not verify_paystack_signature(payload, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid Paystack signature"
        )

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = data.get("event")
    event_data = data.get("data", {})

    # ── CHARGE SUCCESS → Confirm escrow deposit ──────────────
    if event == "charge.success":
        reference = event_data.get("reference", "")
        metadata = event_data.get("metadata", {})
        escrow_id = metadata.get("escrow_id")

        if escrow_id:
            confirm_request = ConfirmDepositRequest(
                escrow_id=escrow_id,
                payment_reference=reference,
                payment_channel=event_data.get("channel", "paystack")
            )
            result = await confirm_deposit(confirm_request, db)
            return {
                "status": "processed",
                "event": event,
                "escrow_id": escrow_id,
                "result": result
            }

    # ── TRANSFER SUCCESS → Log confirmation ──────────────────
    elif event == "transfer.success":
        reference = event_data.get("reference", "")
        # Log the successful transfer
        print(f"Transfer success: {reference}")
        return {"status": "logged", "event": event}

    # ── TRANSFER FAILED → Alert operations ───────────────────
    elif event == "transfer.failed":
        reference = event_data.get("reference", "")
        reason = event_data.get("reason", "Unknown")
        # In production: alert ops team via SMS/email
        print(f"ALERT: Transfer failed — {reference} — {reason}")
        return {"status": "alerted", "event": event}

    return {"status": "received", "event": event}
