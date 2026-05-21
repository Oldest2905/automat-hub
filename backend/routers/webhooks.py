"""
routers/webhooks.py
Flutterwave webhook handler.

Listens for Flutterwave payment events and triggers escrow updates.

HOW FLUTTERWAVE WEBHOOKS WORK:
  1. Buyer pays on Flutterwave checkout
  2. Flutterwave sends POST to /webhooks/flutterwave
  3. We verify the signature using FLUTTERWAVE_SECRET_KEY
  4. We re-verify the transaction by calling Flutterwave GET API
     (never trust a webhook alone — always re-verify)
  5. We update the escrow status to FUNDED
  6. Buyer and seller are notified

FLUTTERWAVE WEBHOOK SIGNATURE:
  Flutterwave sends the hash as the verif-hash header.
  It is a SHA-256 hash of the raw request body + secret key.
  We recompute it and compare. If it does not match, we reject.

ESCROW REFERENCE FORMAT:
  When creating a Flutterwave payment link, set tx_ref to the escrow_id.
  Example: tx_ref = "ESC-A1B2C3D4"
  The webhook payload includes this tx_ref so we can find the escrow.

EVENTS HANDLED:
  charge.completed  → buyer payment confirmed → escrow moves to FUNDED
  transfer.completed → seller payout confirmed → log for audit trail
  transfer.failed    → seller payout failed → alert operations team
"""

import hmac
import hashlib
import json
import httpx
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.schemas.escrow import ConfirmDepositRequest
from backend.services.escrow_service import confirm_deposit
from backend.config import settings

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def verify_flutterwave_signature(payload: bytes, signature: str) -> bool:
    """
    Verify Flutterwave webhook signature.

    Flutterwave documentation says:
    Hash = SHA-256(secretKey + payload) — but in practice they send
    the secretHash directly in the verif-hash header.
    We compare it against our stored FLUTTERWAVE_SECRET_KEY.

    For security we support both the simple header match AND
    a SHA-256 HMAC computation.
    """
    secret = settings.FLUTTERWAVE_SECRET_KEY

    # Method 1: Direct header comparison (Flutterwave standard)
    # Flutterwave sends the exact secret as the verif-hash header
    if signature == secret:
        return True

    # Method 2: HMAC-SHA256 fallback (some Flutterwave versions)
    computed = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


async def verify_transaction_with_flutterwave(transaction_id: str) -> dict:
    """
    Re-verify a transaction directly with Flutterwave API.

    CRITICAL: Never update financial records based on webhook alone.
    Always call this to confirm the payment before marking escrow as funded.

    Flutterwave endpoint: GET /v3/transactions/{id}/verify
    Returns the full transaction object if successful.
    """
    url = f"https://api.flutterwave.com/v3/transactions/{transaction_id}/verify"
    headers = {
        "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
            data = response.json()

            if response.status_code == 200 and data.get("status") == "success":
                tx = data.get("data", {})
                return {
                    "verified": True,
                    "status": tx.get("status"),          # "successful"
                    "amount": tx.get("amount"),
                    "currency": tx.get("currency"),
                    "tx_ref": tx.get("tx_ref"),           # our escrow_id
                    "flw_ref": tx.get("flw_ref"),
                    "transaction_id": tx.get("id"),
                    "customer_email": tx.get("customer", {}).get("email"),
                    "customer_name": tx.get("customer", {}).get("name"),
                }
            return {"verified": False, "error": data.get("message", "Verification failed")}

    except Exception as e:
        return {"verified": False, "error": str(e)}


@router.post(
    "/flutterwave",
    summary="Flutterwave webhook receiver",
    description="Receives and processes Flutterwave payment events. Verifies signature and re-verifies with Flutterwave API before updating escrow."
)
async def flutterwave_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Process Flutterwave webhooks.

    Events handled:
    - charge.completed  → buyer payment confirmed → escrow = FUNDED
    - transfer.completed → seller payout sent → log for audit
    - transfer.failed    → payout failed → alert operations team
    """
    # ── STEP 1: Read raw body for signature verification ─────────
    payload = await request.body()
    signature = request.headers.get("verif-hash", "")

    # ── STEP 2: Verify signature — reject any unsigned webhook ───
    if not settings.FLUTTERWAVE_SECRET_KEY:
        # No secret configured — log and reject
        raise HTTPException(
            status_code=503,
            detail="Flutterwave webhook secret not configured"
        )

    if not verify_flutterwave_signature(payload, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid Flutterwave signature. Request rejected."
        )

    # ── STEP 3: Parse JSON body ───────────────────────────────────
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = data.get("event")
    event_data = data.get("data", {})

    # ── STEP 4: Handle charge.completed ──────────────────────────
    # This fires when a buyer successfully pays for a vehicle.
    # We re-verify with Flutterwave before updating the escrow.
    if event == "charge.completed":
        tx_status = event_data.get("status", "")
        tx_ref    = event_data.get("tx_ref", "")      # This is our escrow_id
        flw_id    = str(event_data.get("id", ""))     # Flutterwave transaction ID

        # Only process successful charges
        if tx_status != "successful":
            return {
                "status": "ignored",
                "reason": f"Charge status was '{tx_status}', not 'successful'",
                "tx_ref": tx_ref
            }

        # tx_ref IS the escrow_id — format: ESC-XXXXXXXX
        # Validate it looks like an escrow ID
        if not tx_ref.startswith("ESC-"):
            return {
                "status": "ignored",
                "reason": f"tx_ref '{tx_ref}' does not match escrow format ESC-XXXXXXXX",
            }

        escrow_id = tx_ref

        # ── RE-VERIFY with Flutterwave before touching the database ──
        verification = await verify_transaction_with_flutterwave(flw_id)

        if not verification.get("verified"):
            raise HTTPException(
                status_code=400,
                detail=f"Flutterwave re-verification failed: {verification.get('error')}"
            )

        # Double-check the re-verified status
        if verification.get("status") != "successful":
            return {
                "status": "ignored",
                "reason": f"Re-verified status was '{verification.get('status')}', not 'successful'",
                "escrow_id": escrow_id
            }

        # ── UPDATE ESCROW STATUS TO FUNDED ───────────────────────
        confirm_request = ConfirmDepositRequest(
            escrow_id=escrow_id,
            payment_reference=flw_id,
            payment_channel="flutterwave"
        )
        result = await confirm_deposit(confirm_request, db)

        return {
            "status": "processed",
            "event": event,
            "escrow_id": escrow_id,
            "flw_transaction_id": flw_id,
            "verified_amount": verification.get("amount"),
            "verified_currency": verification.get("currency"),
            "result": result
        }

    # ── STEP 5: Handle transfer.completed ────────────────────────
    # This fires when Flutterwave sends money to the seller.
    elif event == "transfer.completed":
        reference = event_data.get("reference", "")
        amount     = event_data.get("amount")
        currency   = event_data.get("currency", "NGN")
        bank_name  = event_data.get("bank_name", "")
        account_no = event_data.get("account_number", "")

        # Log for audit trail
        # In production: write to a TransferLog table
        print(
            f"[TRANSFER COMPLETE] ref={reference} amount={currency} {amount} "
            f"bank={bank_name} account=****{str(account_no)[-4:]}"
        )
        return {
            "status": "logged",
            "event": event,
            "reference": reference,
            "amount": amount,
            "currency": currency
        }

    # ── STEP 6: Handle transfer.failed ───────────────────────────
    # This fires when a payout to the seller fails (wrong account,
    # bank downtime, etc.). Operations must be alerted immediately.
    elif event == "transfer.failed":
        reference = event_data.get("reference", "")
        reason    = event_data.get("complete_message", "Unknown reason")
        amount    = event_data.get("amount")

        # ALERT OPERATIONS — In production replace print with:
        # - Send SMS via Termii to operations phone
        # - Send email via Sendgrid/Mailersend to ops@automatcorp.org.ng
        # - Write to an alert log table
        print(
            f"[ALERT — TRANSFER FAILED] ref={reference} "
            f"amount={amount} reason={reason}"
        )
        return {
            "status": "alerted",
            "event": event,
            "reference": reference,
            "reason": reason
        }

    # ── Unknown event — acknowledge and ignore ────────────────────
    return {"status": "received", "event": event}


# ── KEEP THIS: old /paystack route as redirect for safety ─────────
# If any old Paystack webhook is still configured somewhere, it will
# hit this and get a clear error rather than a 404.
@router.post(
    "/paystack",
    include_in_schema=False
)
async def paystack_legacy_redirect():
    """
    Legacy Paystack endpoint — this project now uses Flutterwave.
    If you are seeing this, update your webhook URL in Paystack dashboard.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "This project has migrated from Paystack to Flutterwave. "
            "Update your webhook URL to /webhooks/flutterwave"
        )
    )
