"""
routers/subscription.py
Subscription management and payment endpoints.

Users subscribe to pay monthly via Paystack.
After payment confirmed, their account is upgraded.

POST /subscription/initiate    - Start payment for a plan
POST /subscription/verify      - Verify payment and activate
GET  /subscription/pricing     - Get all pricing info
GET  /subscription/status      - Get current subscription
POST /subscription/cancel      - Cancel subscription
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.user import User
from backend.services.subscription_service import (
    get_plan_pricing, calculate_fleet_price, activate_subscription
)
from backend.services.paystack_service import initialize_payment, verify_payment

router = APIRouter(prefix="/subscription", tags=["Subscriptions & Billing"])


class SubscribeRequest(BaseModel):
    plan: str                        # private, fleet, reseller
    vehicle_count: Optional[int] = 1 # For fleet plan


@router.get("/pricing", response_model=dict, summary="Get all plan pricing")
async def get_pricing():
    """
    Returns full pricing table.
    No authentication required — public endpoint.
    """
    return {
        "success": True,
        "pricing": get_plan_pricing()
    }


@router.get("/fleet-quote", response_model=dict, summary="Get fleet price quote")
async def fleet_quote(vehicle_count: int = Query(..., ge=5)):
    """
    Get a price quote for a fleet subscription.
    Minimum 5 vehicles. Volume discounts apply at 10, 20, 50+.
    """
    quote = calculate_fleet_price(vehicle_count)
    return {"success": True, "quote": quote}


@router.post("/initiate", response_model=dict, summary="Start subscription payment")
async def initiate_subscription(
    request: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Initiate a Paystack payment for a subscription plan.
    Returns a payment URL — redirect user to this URL to complete payment.

    After payment, call /subscription/verify with the reference.
    """
    result = await db.execute(select(User).where(User.user_id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    valid_plans = ["private", "fleet", "reseller"]
    if request.plan not in valid_plans:
        raise HTTPException(400, f"Plan must be one of: {valid_plans}")

    # Calculate amount
    pricing = get_plan_pricing()
    if request.plan == "private":
        amount_ngn = pricing["private_owner"]["price_ngn"] * request.vehicle_count
    elif request.plan == "fleet":
        quote = calculate_fleet_price(request.vehicle_count)
        amount_ngn = quote["monthly_total_ngn"]
    elif request.plan == "reseller":
        amount_ngn = pricing["reseller"]["price_ngn"]
    else:
        amount_ngn = 0

    # Amount in USD for Paystack (approximate conversion)
    amount_usd = amount_ngn / 1600  # Update with live rate in production

    # Initiate Paystack payment
    payment = await initialize_payment(
        email=user.email,
        amount_usd=amount_usd,
        escrow_id=f"SUB-{current_user['user_id']}-{request.plan}",
        vin=f"SUBSCRIPTION-{request.plan.upper()}",
        callback_url=f"{__import__('backend.config', fromlist=['settings']).settings.APP_URL}/subscription/callback"
    )

    if not payment.get("success"):
        raise HTTPException(500, "Failed to initiate payment. Try again.")

    return {
        "success": True,
        "plan": request.plan,
        "vehicle_count": request.vehicle_count,
        "amount_ngn": amount_ngn,
        "payment_url": payment.get("authorization_url"),
        "reference": payment.get("reference"),
        "message": "Complete payment at the URL provided."
    }


@router.post("/verify", response_model=dict, summary="Verify payment and activate plan")
async def verify_subscription_payment(
    reference: str,
    plan: str,
    vehicle_count: int = 1,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Call this after user completes Paystack payment.
    Verifies the payment and activates the subscription.
    """
    # Verify with Paystack
    payment_result = await verify_payment(reference)

    if not payment_result.get("success"):
        raise HTTPException(400, "Payment verification failed")

    if payment_result.get("status") != "success":
        raise HTTPException(400, f"Payment not completed. Status: {payment_result.get('status')}")

    # Activate subscription
    result = await activate_subscription(
        user_id=current_user["user_id"],
        plan=plan,
        vehicle_count=vehicle_count,
        payment_reference=reference,
        db=db
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    return {
        "success": True,
        "message": f"Subscription activated successfully!",
        "plan": plan,
        "vehicle_slots": vehicle_count,
        "valid_until": result.get("valid_until")
    }


@router.get("/status", response_model=dict, summary="Get current subscription status")
async def subscription_status(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Check current subscription status."""
    result = await db.execute(select(User).where(User.user_id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")

    from datetime import timezone
    from datetime import datetime
    days_remaining = None
    if user.subscription_end:
        delta = user.subscription_end - datetime.now(timezone.utc)
        days_remaining = max(0, delta.days)

    return {
        "success": True,
        "subscription": {
            "plan": user.subscription_plan,
            "status": user.subscription_status,
            "vehicle_slots": user.vehicle_slots,
            "valid_until": user.subscription_end.isoformat() if user.subscription_end else None,
            "days_remaining": days_remaining,
            "is_active": user.subscription_status == "active" and (days_remaining or 0) > 0
        }
    }
