"""
services/subscription_service.py
Subscription management and pricing.

PRICING:
Private Owner:   ₦15,000/month per vehicle
                 - Hourly OBD scans
                 - Fault alerts via SMS + push
                 - Workshop routing
                 - DCP history
                 - Basic report

Fleet Owner:     ₦8,000/vehicle/month (minimum 5 vehicles = ₦40,000/month)
                 - Everything in Private
                 - Fleet health dashboard
                 - Live GPS tracking
                 - CSV/JSON export reports
                 - Multi-vehicle management
                 - Dedicated account manager (10+ vehicles)

Reseller:        ₦50,000/month base
                 + ₦5,000 per DCP issued
                 + 1.5% escrow transaction fee
                 - API access
                 - DCP issuance
                 - Escrow rails
                 - Condition Registry (add-on)

Workshop:        FREE to register
                 8% commission on repair revenue
                 (Workshop earns 92%)

Fix Payment:     Owner pays workshop via in-app Paystack escrow
                 Platform takes 8% on fix completion
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models.user import User, Subscription, SubscriptionPlan


PRICING = {
    "private": {
        "monthly_ngn": 15000,
        "per_vehicle": True,
        "min_vehicles": 1,
        "features": [
            "Hourly OBD scans",
            "Fault alerts (SMS + push)",
            "Workshop routing",
            "DCP history access",
            "Basic health report"
        ]
    },
    "fleet": {
        "monthly_per_vehicle_ngn": 8000,
        "min_vehicles": 5,
        "min_monthly_ngn": 40000,  # 5 vehicles × ₦8,000
        "features": [
            "Everything in Private",
            "Fleet health dashboard",
            "Live GPS tracking",
            "CSV/JSON export reports",
            "Multi-vehicle management",
            "Dedicated account manager (10+ vehicles)"
        ]
    },
    "reseller": {
        "monthly_base_ngn": 50000,
        "per_dcp_ngn": 5000,
        "escrow_fee_percent": 1.5,
        "features": [
            "API access (REST)",
            "DCP issuance",
            "Escrow rails",
            "Verified buyer registry",
            "Condition Registry (add-on)"
        ]
    },
    "workshop": {
        "registration_fee_ngn": 0,
        "commission_percent": 8,
        "mechanic_net_percent": 92,
        "features": [
            "Job routing from platform",
            "Mechanic scan app",
            "Paystack payments",
            "Performance dashboard"
        ]
    }
}


def calculate_fleet_price(vehicle_count: int) -> dict:
    """Calculate fleet subscription price for N vehicles."""
    if vehicle_count < 5:
        vehicle_count = 5  # Minimum 5 vehicles

    monthly_total = vehicle_count * 8000

    # Volume discounts
    discount_pct = 0
    if vehicle_count >= 50:
        discount_pct = 15
    elif vehicle_count >= 20:
        discount_pct = 10
    elif vehicle_count >= 10:
        discount_pct = 5

    if discount_pct:
        monthly_total = int(monthly_total * (1 - discount_pct / 100))

    return {
        "vehicle_count": vehicle_count,
        "per_vehicle_ngn": 8000,
        "monthly_total_ngn": monthly_total,
        "discount_percent": discount_pct,
        "annual_total_ngn": monthly_total * 12,
        "annual_savings_ngn": (8000 * vehicle_count * 12) - (monthly_total * 12)
    }


def get_plan_pricing() -> dict:
    """Return full pricing table for display."""
    return {
        "private_owner": {
            "name": "Private Owner",
            "price": "₦15,000/vehicle/month",
            "price_ngn": 15000,
            "billing": "per vehicle, monthly",
            "features": PRICING["private"]["features"]
        },
        "fleet_owner": {
            "name": "Fleet Owner",
            "price": "₦8,000/vehicle/month",
            "price_ngn": 8000,
            "minimum": "5 vehicles minimum (₦40,000/month)",
            "billing": "per vehicle, monthly",
            "discounts": {
                "10+": "5% off",
                "20+": "10% off",
                "50+": "15% off"
            },
            "features": PRICING["fleet"]["features"]
        },
        "reseller": {
            "name": "Licensed Reseller",
            "price": "₦50,000/month base",
            "price_ngn": 50000,
            "per_dcp": "₦5,000 per DCP issued",
            "escrow_fee": "1.5% per transaction",
            "billing": "monthly base + usage",
            "features": PRICING["reseller"]["features"]
        },
        "workshop": {
            "name": "Workshop Partner",
            "price": "FREE",
            "price_ngn": 0,
            "commission": "8% of repair revenue",
            "mechanic_keeps": "92% of every job",
            "billing": "commission on completed jobs only",
            "features": PRICING["workshop"]["features"]
        }
    }


async def activate_subscription(
    user_id: str,
    plan: str,
    vehicle_count: int,
    payment_reference: str,
    db: AsyncSession
) -> dict:
    """Activate a subscription after successful payment."""
    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        return {"error": "User not found"}

    now = datetime.now(timezone.utc)
    end_date = now + timedelta(days=30)

    # Calculate amount
    if plan == "private":
        amount = 15000 * vehicle_count
    elif plan == "fleet":
        pricing = calculate_fleet_price(vehicle_count)
        amount = pricing["monthly_total_ngn"]
    elif plan == "reseller":
        amount = 50000
    else:
        amount = 0

    # Update user subscription
    user.subscription_plan = plan
    user.subscription_status = "active"
    user.subscription_start = now
    user.subscription_end = end_date
    user.vehicle_slots = vehicle_count

    # Create subscription record
    sub = Subscription(
        user_id=user_id,
        plan=plan,
        vehicle_count=vehicle_count,
        amount_ngn=amount,
        billing_period_start=now,
        billing_period_end=end_date,
        status="active",
        paystack_reference=payment_reference
    )
    db.add(sub)

    return {
        "success": True,
        "plan": plan,
        "vehicle_slots": vehicle_count,
        "amount_ngn": amount,
        "valid_until": end_date.isoformat()
    }
