"""
services/paystack_service.py
Paystack payment integration.
Handles deposit initiation and fund release to sellers.
"""

import httpx
from backend.config import settings

PAYSTACK_BASE = "https://api.paystack.co"

HEADERS = {
    "Authorization": f"Bearer {settings.FLUTTERWAVE_SECRET_KEY}",
    "Content-Type": "application/json"
}


async def initialize_payment(
    email: str,
    amount_usd: float,
    escrow_id: str,
    vin: str,
    callback_url: str = None
) -> dict:
    """
    Initialize a Paystack payment for escrow deposit.
    Amount is in kobo (NGN × 100) for Paystack.
    We store and settle in USD but collect in NGN.

    Returns Paystack authorization URL for buyer to complete payment.
    """
    # Convert USD to NGN using current rate
    # In production: fetch live rate from CBN or a forex API
    ngn_rate = 1600  # Placeholder — fetch dynamically
    amount_ngn = amount_usd * ngn_rate
    amount_kobo = int(amount_ngn * 100)

    payload = {
        "email": email,
        "amount": amount_kobo,
        "currency": "NGN",
        "reference": f"ATH-{escrow_id}",
        "callback_url": callback_url or f"{settings.APP_URL}/escrow/{escrow_id}",
        "metadata": {
            "escrow_id": escrow_id,
            "vin": vin,
            "custom_fields": [
                {
                    "display_name": "Escrow ID",
                    "variable_name": "escrow_id",
                    "value": escrow_id
                },
                {
                    "display_name": "Vehicle VIN",
                    "variable_name": "vin",
                    "value": vin
                }
            ]
        }
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYSTACK_BASE}/transaction/initialize",
            json=payload,
            headers=HEADERS,
            timeout=30
        )
        data = response.json()

    if not data.get("status"):
        return {
            "success": False,
            "error": data.get("message", "Payment initialization failed")
        }

    return {
        "success": True,
        "authorization_url": data["data"]["authorization_url"],
        "access_code": data["data"]["access_code"],
        "reference": data["data"]["reference"]
    }


async def verify_payment(reference: str) -> dict:
    """
    Verify a Paystack payment by reference.
    Called after webhook or as fallback.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{PAYSTACK_BASE}/transaction/verify/{reference}",
            headers=HEADERS,
            timeout=30
        )
        data = response.json()

    if not data.get("status"):
        return {"success": False, "error": "Verification failed"}

    transaction = data["data"]
    return {
        "success": True,
        "status": transaction["status"],
        "amount_kobo": transaction["amount"],
        "reference": transaction["reference"],
        "paid_at": transaction.get("paid_at"),
        "channel": transaction.get("channel")
    }


async def create_transfer_recipient(
    account_number: str,
    bank_code: str,
    name: str
) -> dict:
    """
    Create a Paystack transfer recipient for seller payout.
    Must be called before transferring funds.
    """
    payload = {
        "type": "nuban",
        "name": name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": "NGN"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYSTACK_BASE}/transferrecipient",
            json=payload,
            headers=HEADERS,
            timeout=30
        )
        data = response.json()

    if not data.get("status"):
        return {"success": False, "error": data.get("message")}

    return {
        "success": True,
        "recipient_code": data["data"]["recipient_code"]
    }


async def transfer_to_seller(
    recipient_code: str,
    amount_ngn: float,
    escrow_id: str,
    reason: str = "Automat Hub Escrow Settlement"
) -> dict:
    """
    Transfer funds to seller after escrow conditions are met.
    This is the final step in the escrow settlement.

    CRITICAL: Only call this after ALL escrow conditions are verified.
    """
    amount_kobo = int(amount_ngn * 100)

    payload = {
        "source": "balance",
        "amount": amount_kobo,
        "recipient": recipient_code,
        "reason": reason,
        "reference": f"ATH-SETTLE-{escrow_id}"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{PAYSTACK_BASE}/transfer",
            json=payload,
            headers=HEADERS,
            timeout=30
        )
        data = response.json()

    if not data.get("status"):
        return {
            "success": False,
            "error": data.get("message", "Transfer failed")
        }

    return {
        "success": True,
        "transfer_code": data["data"]["transfer_code"],
        "reference": data["data"]["reference"],
        "status": data["data"]["status"]
    }
