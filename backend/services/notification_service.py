"""
services/notification_service.py
SMS and email notifications for DCP and Escrow events.
Uses Twilio for SMS.
"""

from backend.config import settings


async def send_sms(phone: str, message: str) -> bool:
    """Send SMS via Twilio."""
    try:
        if not settings.TWILIO_ACCOUNT_SID:
            print(f"SMS (mock): {phone} — {message}")
            return True

        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone
        )
        return True
    except Exception as e:
        print(f"SMS error: {e}")
        return False


async def notify_escrow_created(
    buyer_name: str,
    buyer_phone: str,
    escrow_id: str,
    amount_usd: float,
    vin: str
):
    msg = (
        f"The Automat Hub: Escrow {escrow_id} created for VIN {vin}. "
        f"Amount: ${amount_usd:,.2f}. "
        f"Please make your deposit to activate the escrow. "
        f"Ref: {escrow_id}"
    )
    await send_sms(buyer_phone, msg)


async def notify_funds_received(
    buyer_name: str,
    buyer_phone: str,
    escrow_id: str,
    amount_usd: float
):
    msg = (
        f"The Automat Hub: Funds received for escrow {escrow_id}. "
        f"${amount_usd:,.2f} is now held securely. "
        f"We will verify your vehicle against its DCP and notify you. "
        f"No handshakes. Just protocol."
    )
    await send_sms(buyer_phone, msg)


async def notify_dcp_matched(
    buyer_name: str,
    buyer_phone: str,
    escrow_id: str,
    vin: str
):
    msg = (
        f"The Automat Hub: VERIFIED. Vehicle VIN {vin} matches its "
        f"Digital Condition Passport. Delivery can now proceed. "
        f"Confirm delivery to release funds. Escrow: {escrow_id}"
    )
    await send_sms(buyer_phone, msg)


async def notify_delivery_confirmed(
    buyer_name: str,
    buyer_phone: str,
    escrow_id: str
):
    msg = (
        f"The Automat Hub: Delivery confirmed for escrow {escrow_id}. "
        f"Processing fund release to seller. Transaction complete."
    )
    await send_sms(buyer_phone, msg)


async def notify_funds_released(
    buyer_name: str,
    buyer_phone: str,
    seller_name: str,
    escrow_id: str,
    amount: float
):
    msg = (
        f"The Automat Hub: Transaction complete. "
        f"Escrow {escrow_id} settled. "
        f"${amount:,.2f} released to seller. "
        f"Drive verified. Drive Automat."
    )
    await send_sms(buyer_phone, msg)


async def notify_dispute_raised(
    buyer_name: str,
    escrow_id: str,
    reason: str
):
    msg = (
        f"The Automat Hub: Dispute raised on escrow {escrow_id}. "
        f"Funds are frozen. Our team will contact you within 24 hours. "
        f"Email: support@automatcorp.org.ng"
    )
    print(f"Dispute notification logged: {escrow_id} — {reason}")
