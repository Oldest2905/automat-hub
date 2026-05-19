"""
models/dcp.py
SQLAlchemy database models for DCP records.

THREE TABLES:
1. dcp_records        — main DCP record per vehicle
2. dcp_hash_ledger    — APPEND-ONLY tamper-evident hash store
3. inspection_details — full 150-point inspection breakdown
4. verification_log   — every public verification recorded
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, Text, JSON, ForeignKey, Enum,
    UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from backend.core.database import Base
import enum


class DCPStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"


class DCPGrade(str, enum.Enum):
    A = "A"   # 90-100
    B = "B"   # 75-89
    C = "C"   # 60-74
    D = "D"   # Below 60


class DCPRecord(Base):
    """
    Main DCP record.
    Created once per inspection.
    Never updated — only status can change.
    """
    __tablename__ = "dcp_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dcp_id = Column(String(50), unique=True, nullable=False, index=True)
    vin = Column(String(17), nullable=False, index=True)
    make = Column(String(50))
    model = Column(String(50))
    year = Column(Integer)
    colour = Column(String(30))
    odometer = Column(Integer)

    # Inspection summary
    score = Column(Integer, nullable=False)
    grade = Column(String(1), nullable=False)
    status = Column(
        String(20),
        default=DCPStatus.VERIFIED,
        nullable=False
    )

    # Auditor
    auditor_id = Column(String(50), nullable=False)
    auditor_name = Column(String(100))

    # Warranty
    warranty_days = Column(Integer, default=30)
    warranty_expiry = Column(DateTime(timezone=True))

    # Timestamps
    issued_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    hash_record = relationship(
        "DCPHashLedger",
        back_populates="dcp_record",
        uselist=False
    )
    inspection = relationship(
        "InspectionDetail",
        back_populates="dcp_record",
        uselist=False
    )
    verifications = relationship(
        "VerificationLog",
        back_populates="dcp_record"
    )

    __table_args__ = (
        Index('idx_dcp_vin_issued', 'vin', 'issued_at'),
    )


class DCPHashLedger(Base):
    """
    APPEND-ONLY tamper-evident hash ledger.
    This table has NO UPDATE and NO DELETE permissions.
    Once a hash is written it is permanent.
    This is the cryptographic trust anchor of the protocol.
    """
    __tablename__ = "dcp_hash_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dcp_id = Column(
        String(50),
        ForeignKey("dcp_records.dcp_id"),
        nullable=False,
        unique=True
    )
    vin = Column(String(17), nullable=False)

    # The hash
    hash = Column(String(64), nullable=False, unique=True)
    hash_algorithm = Column(String(20), default="SHA-256", nullable=False)

    # The exact payload that was hashed
    # Stored so anyone can independently verify
    payload_json = Column(JSONB, nullable=False)
    payload_string = Column(Text, nullable=False)

    # Metadata
    auditor_id = Column(String(50), nullable=False)
    issuer = Column(String(100), default="The Automat Hub Ltd")
    protocol_version = Column(String(10), default="1.0")

    # Timestamp — immutable record of when hash was created
    issued_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship
    dcp_record = relationship("DCPRecord", back_populates="hash_record")

    __table_args__ = (
        Index('idx_hash_ledger_vin', 'vin'),
        Index('idx_hash_ledger_hash', 'hash'),
    )


class InspectionDetail(Base):
    """
    Full 150-point inspection breakdown.
    Linked to DCP record.
    Stored for complete audit trail.
    """
    __tablename__ = "inspection_details"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dcp_id = Column(
        String(50),
        ForeignKey("dcp_records.dcp_id"),
        nullable=False,
        unique=True
    )

    # OBD-II Data
    obd2_status = Column(String(20))
    obd2_fault_codes = Column(JSONB, default=list)
    obd2_readiness_monitors = Column(JSONB, default=dict)

    # Engine
    engine_compression = Column(String(20))
    engine_oil_condition = Column(String(20))
    coolant_condition = Column(String(20))
    timing_belt_condition = Column(String(20))

    # Transmission
    transmission_condition = Column(String(20))
    transmission_fluid = Column(String(20))

    # Chassis & Body
    frame_alignment = Column(String(20))
    rust_assessment = Column(String(20))
    accident_history_indicators = Column(Boolean, default=False)
    paint_uniformity = Column(String(20))

    # Electrical
    battery_health = Column(String(20))
    alternator_output = Column(String(20))
    electronics_status = Column(String(20))

    # Safety Systems
    brake_condition = Column(String(20))
    tyre_condition = Column(JSONB, default=dict)
    airbag_status = Column(String(20))
    abs_status = Column(String(20))

    # AI Diagnostics
    ai_condition_grade = Column(String(20))
    ai_confidence_score = Column(Float)
    ai_flags = Column(JSONB, default=list)

    # Full checklist — all 150 points stored as JSON
    checklist_results = Column(JSONB, nullable=False)

    # Inspection photos stored in S3
    photos_s3_urls = Column(JSONB, default=list)

    # Notes
    inspector_notes = Column(Text)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationship
    dcp_record = relationship("DCPRecord", back_populates="inspection")


class VerificationLog(Base):
    """
    Every public DCP verification is recorded.
    This builds the Dealer Reputation Graph over time.
    It also proves market demand for each passport.
    """
    __tablename__ = "verification_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dcp_id = Column(
        String(50),
        ForeignKey("dcp_records.dcp_id"),
        nullable=False
    )
    verified_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )
    verified_by_ip = Column(String(45))
    result = Column(Boolean)
    method = Column(String(20))  # QR, NFC, API, MANUAL

    # Relationship
    dcp_record = relationship("DCPRecord", back_populates="verifications")

    __table_args__ = (
        Index('idx_verification_dcp', 'dcp_id'),
        Index('idx_verification_date', 'verified_at'),
    )
