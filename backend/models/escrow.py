"""
models/escrow.py
SQLAlchemy database models for Escrow settlement.

ESCROW FLOW:
INITIATED → FUNDED → DCP_MATCHED → DELIVERY_CONFIRMED → COMPLETED
                                                       → DISPUTED
                                                       → REFUNDED
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, Text, ForeignKey, Index, Numeric
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.core.database import Base
import enum


class EscrowStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    FUNDED = "FUNDED"
    DCP_MATCHED = "DCP_MATCHED"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class EscrowDeal(Base):
    """
    Main escrow deal record.
    One escrow per vehicle transaction.
    Links to a DCP record — no DCP, no escrow.
    """
    __tablename__ = "escrow_deals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escrow_id = Column(String(50), unique=True, nullable=False, index=True)
    dcp_id = Column(String(50), nullable=False, index=True)
    vin = Column(String(17), nullable=False)

    # Parties
    buyer_name = Column(String(100), nullable=False)
    buyer_email = Column(String(100), nullable=False)
    buyer_phone = Column(String(20))

    seller_name = Column(String(100), nullable=False)
    seller_account = Column(String(50))

    # Amount
    amount_usd = Column(Numeric(12, 2), nullable=False)
    amount_ngn = Column(Numeric(15, 2))
    fx_rate_at_deposit = Column(Numeric(10, 2))
    platform_fee_percent = Column(Float, default=1.5)
    platform_fee_amount = Column(Numeric(12, 2))
    seller_net_amount = Column(Numeric(12, 2))

    # Status
    status = Column(
        String(30),
        default=EscrowStatus.INITIATED,
        nullable=False
    )

    # Conditions — ALL must be True before funds release
    dcp_verified = Column(Boolean, default=False)
    physical_delivery_confirmed = Column(Boolean, default=False)
    buyer_acknowledged = Column(Boolean, default=False)

    # Payment reference (Paystack)
    payment_reference = Column(String(100))
    payment_channel = Column(String(50))

    # Timeline
    initiated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    funded_at = Column(DateTime(timezone=True))
    dcp_matched_at = Column(DateTime(timezone=True))
    delivery_confirmed_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    expiry_at = Column(DateTime(timezone=True))

    # Notes
    notes = Column(Text)
    dispute_reason = Column(Text)

    # Relationships
    events = relationship(
        "EscrowEvent",
        back_populates="escrow_deal",
        order_by="EscrowEvent.created_at"
    )

    __table_args__ = (
        Index('idx_escrow_status', 'status'),
        Index('idx_escrow_vin', 'vin'),
    )


class EscrowEvent(Base):
    """
    Immutable audit trail for every escrow status change.
    Every action on an escrow deal creates an event.
    This is the tamper-evident history of the transaction.
    """
    __tablename__ = "escrow_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    escrow_id = Column(
        String(50),
        ForeignKey("escrow_deals.escrow_id"),
        nullable=False
    )

    event_type = Column(String(50), nullable=False)
    from_status = Column(String(30))
    to_status = Column(String(30))
    triggered_by = Column(String(100))  # user_id or system
    notes = Column(Text)
    event_metadata = Column("metadata", JSONB, default=dict)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship
    escrow_deal = relationship("EscrowDeal", back_populates="events")

    __table_args__ = (
        Index('idx_event_escrow', 'escrow_id'),
        Index('idx_event_type', 'event_type'),
    )
