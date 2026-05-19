"""
models/user.py
User accounts, roles, and subscription management.

USER ROLES:
- private_owner   : individual car owner
- fleet_owner     : manages multiple vehicles
- reseller        : licensed dealer with API access
- mechanic        : workshop mechanic who performs fixes
- admin           : Automat Hub internal staff
- inspector       : Automat Hub inspector
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean,
    DateTime, Numeric, ForeignKey, Index, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.core.database import Base
import enum


class UserRole(str, enum.Enum):
    PRIVATE_OWNER = "private_owner"
    FLEET_OWNER = "fleet_owner"
    RESELLER = "reseller"
    MECHANIC = "mechanic"
    ADMIN = "admin"
    INSPECTOR = "inspector"


class SubscriptionPlan(str, enum.Enum):
    PRIVATE = "private"          # ₦15,000/month per vehicle
    FLEET = "fleet"              # ₦8,000/vehicle/month (min 5)
    RESELLER = "reseller"        # ₦50,000/month + per-use fees
    FREE = "free"                # Limited — no hourly scans


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    TRIAL = "trial"


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    phone = Column(String(20), unique=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(30), nullable=False, default=UserRole.PRIVATE_OWNER)

    # Profile
    company_name = Column(String(100))
    address = Column(Text)
    state = Column(String(50))
    nin = Column(String(20))          # National ID
    cac_number = Column(String(20))   # For businesses

    # Status
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    phone_verified = Column(Boolean, default=False)

    # Subscription
    subscription_plan = Column(String(30), default=SubscriptionPlan.FREE)
    subscription_status = Column(String(20), default=SubscriptionStatus.TRIAL)
    subscription_start = Column(DateTime(timezone=True))
    subscription_end = Column(DateTime(timezone=True))
    vehicle_slots = Column(Integer, default=1)  # How many vehicles on plan

    # Paystack
    paystack_customer_code = Column(String(100))
    paystack_subscription_code = Column(String(100))

    # Push notifications
    fcm_token = Column(String(500))  # Firebase push token

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    vehicles = relationship("TrackedVehicle", back_populates="owner")
    fleet = relationship("Fleet", back_populates="owner", uselist=False)
    reseller_key = relationship("ResellerAPIKey", back_populates="user", uselist=False)

    __table_args__ = (
        Index('idx_users_role', 'role'),
        Index('idx_users_subscription', 'subscription_status'),
    )


class ResellerAPIKey(Base):
    """
    API keys for licensed resellers/dealers.
    Each reseller gets a unique key with rate limits and usage tracking.
    """
    __tablename__ = "reseller_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    api_key = Column(String(64), unique=True, nullable=False, index=True)
    api_key_prefix = Column(String(10))  # First 8 chars for display

    # Rate limiting
    requests_per_hour = Column(Integer, default=100)
    requests_per_day = Column(Integer, default=1000)
    current_hour_count = Column(Integer, default=0)
    current_day_count = Column(Integer, default=0)
    last_reset_hour = Column(DateTime(timezone=True))
    last_reset_day = Column(DateTime(timezone=True))

    # Usage tracking
    total_requests = Column(Integer, default=0)
    total_dcps_issued = Column(Integer, default=0)
    total_revenue_generated = Column(Numeric(12, 2), default=0)

    # Permissions
    can_issue_dcp = Column(Boolean, default=True)
    can_access_registry = Column(Boolean, default=False)
    can_use_escrow = Column(Boolean, default=True)
    can_access_fleet = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime(timezone=True))

    # Relationship
    user = relationship("User", back_populates="reseller_key")


class Subscription(Base):
    """
    Subscription billing records.
    One record per billing cycle per user.
    """
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    plan = Column(String(30), nullable=False)
    vehicle_count = Column(Integer, default=1)
    amount_ngn = Column(Numeric(12, 2), nullable=False)
    billing_period_start = Column(DateTime(timezone=True))
    billing_period_end = Column(DateTime(timezone=True))
    status = Column(String(20), default="active")
    paystack_reference = Column(String(100))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (Index('idx_sub_user', 'user_id'),)
