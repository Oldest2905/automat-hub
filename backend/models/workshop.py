"""
models/workshop.py
Workshop registry, mechanic accounts, and repair job models.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Boolean, Float,
    DateTime, Numeric, ForeignKey, Index, Text
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.core.database import Base
import enum


class WorkshopStatus(str, enum.Enum):
    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class JobStatus(str, enum.Enum):
    CREATED = "created"
    VEHICLE_ARRIVED = "vehicle_arrived"
    DIAGNOSIS_COMPLETE = "diagnosis_complete"
    QUOTE_SENT = "quote_sent"
    PAYMENT_RECEIVED = "payment_received"
    REPAIR_IN_PROGRESS = "repair_in_progress"
    REPAIR_COMPLETE = "repair_complete"
    FINAL_SCAN_DONE = "final_scan_done"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Workshop(Base):
    """
    Registered mechanic workshops.
    Routed fault vehicles automatically.
    Earn 92% of repair revenue (8% platform fee).
    """
    __tablename__ = "workshops"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workshop_id = Column(String(50), unique=True, nullable=False, index=True)
    owner_user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)

    # Details
    name = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    state = Column(String(50), nullable=False)
    lga = Column(String(50))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    # Capabilities
    specializations = Column(JSONB, default=list)
    # e.g. ["engine", "transmission", "electrical", "bodywork", "tyres"]
    accepted_brands = Column(JSONB, default=list)
    # e.g. ["Toyota", "Honda", "Range Rover"]

    # Operating hours
    open_time = Column(String(10), default="08:00")
    close_time = Column(String(10), default="18:00")
    open_days = Column(JSONB, default=list)
    # e.g. ["monday","tuesday","wednesday","thursday","friday","saturday"]

    # Capacity
    max_concurrent_jobs = Column(Integer, default=5)
    current_active_jobs = Column(Integer, default=0)

    # Status
    status = Column(String(30), default=WorkshopStatus.PENDING_APPROVAL)
    is_available = Column(Boolean, default=True)

    # Performance metrics
    total_jobs_completed = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)
    total_revenue = Column(Numeric(12, 2), default=0)
    platform_fees_paid = Column(Numeric(12, 2), default=0)

    # Paystack for receiving payments
    paystack_recipient_code = Column(String(100))

    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    mechanics = relationship("Mechanic", back_populates="workshop")
    jobs = relationship("RepairJob", back_populates="workshop")

    __table_args__ = (
        Index('idx_workshop_state', 'state'),
        Index('idx_workshop_location', 'latitude', 'longitude'),
        Index('idx_workshop_status', 'status'),
    )


class Mechanic(Base):
    """
    Individual mechanic accounts within a workshop.
    Mechanics perform final scans to close repair jobs.
    """
    __tablename__ = "mechanics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mechanic_id = Column(String(50), unique=True, nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    workshop_id = Column(String(50), ForeignKey("workshops.workshop_id"), nullable=False)

    full_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    specialization = Column(String(50))
    certification_number = Column(String(50))

    is_active = Column(Boolean, default=True)
    total_jobs_completed = Column(Integer, default=0)
    average_rating = Column(Float, default=0.0)

    # Relationship
    workshop = relationship("Workshop", back_populates="mechanics")
    jobs = relationship("RepairJob", back_populates="assigned_mechanic")


class RepairJob(Base):
    """
    A repair job created when a fault is detected.
    Tracks the entire fix workflow from alert to completion.
    Final scan by mechanic closes the job and releases payment.
    """
    __tablename__ = "repair_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String(50), unique=True, nullable=False, index=True)

    # Links
    vehicle_id = Column(String(50), ForeignKey("tracked_vehicles.vehicle_id"), nullable=False)
    vin = Column(String(17), nullable=False)
    owner_user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    workshop_id = Column(String(50), ForeignKey("workshops.workshop_id"), nullable=False)
    assigned_mechanic_id = Column(String(50), ForeignKey("mechanics.mechanic_id"))
    alert_id = Column(String(50))  # The alert that triggered this job
    dcp_id = Column(String(50))    # DCP to be updated after fix

    # Fault details
    fault_codes = Column(JSONB, default=list)
    fault_description = Column(Text)
    severity = Column(String(20))

    # Job status
    status = Column(String(30), default=JobStatus.CREATED)

    # Quote and payment
    diagnosis_notes = Column(Text)
    quoted_amount_ngn = Column(Numeric(12, 2))
    final_amount_ngn = Column(Numeric(12, 2))
    platform_fee_ngn = Column(Numeric(12, 2))
    workshop_net_ngn = Column(Numeric(12, 2))

    # Payment via Paystack escrow
    payment_reference = Column(String(100))
    payment_status = Column(String(20), default="pending")

    # Fix verification
    pre_fix_scan_id = Column(String(50))   # Scan on vehicle arrival
    post_fix_scan_id = Column(String(50))  # Final scan confirming fix
    fix_verified = Column(Boolean, default=False)

    # Owner rating
    owner_rating = Column(Integer)  # 1-5
    owner_review = Column(Text)

    # Timeline
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    vehicle_arrived_at = Column(DateTime(timezone=True))
    diagnosis_completed_at = Column(DateTime(timezone=True))
    payment_received_at = Column(DateTime(timezone=True))
    repair_completed_at = Column(DateTime(timezone=True))
    final_scan_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Relationships
    workshop = relationship("Workshop", back_populates="jobs")
    assigned_mechanic = relationship("Mechanic", back_populates="jobs")

    __table_args__ = (
        Index('idx_job_vehicle', 'vehicle_id'),
        Index('idx_job_workshop', 'workshop_id'),
        Index('idx_job_status', 'status'),
    )
