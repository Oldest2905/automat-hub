"""
models/fleet.py
Fleet management, vehicle tracking, and scan history models.
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


class VehicleStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WARNING = "warning"          # Minor faults
    CRITICAL = "critical"        # Severe faults — needs immediate attention
    IN_WORKSHOP = "in_workshop"  # Currently being serviced
    INACTIVE = "inactive"        # Removed from tracking


class Fleet(Base):
    """
    Fleet group — owned by a fleet_owner user.
    A fleet owner can have multiple fleets (e.g. different cities).
    """
    __tablename__ = "fleets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fleet_id = Column(String(50), unique=True, nullable=False, index=True)
    owner_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    industry = Column(String(50))  # logistics, ride_hailing, corporate, rental

    # Settings
    geofence_enabled = Column(Boolean, default=False)
    geofence_polygon = Column(JSONB)  # GeoJSON polygon
    speed_limit_kmh = Column(Integer, default=120)
    hourly_scan_enabled = Column(Boolean, default=True)

    # Stats (updated on each scan)
    total_vehicles = Column(Integer, default=0)
    healthy_count = Column(Integer, default=0)
    warning_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    owner = relationship("User", back_populates="fleet")
    vehicles = relationship("TrackedVehicle", back_populates="fleet")

    __table_args__ = (Index('idx_fleet_owner', 'owner_id'),)


class TrackedVehicle(Base):
    """
    A vehicle registered for DCP tracking.
    Can belong to private owner or fleet.
    """
    __tablename__ = "tracked_vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(String(50), unique=True, nullable=False, index=True)
    vin = Column(String(17), nullable=False, index=True)
    owner_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)
    fleet_id = Column(String(50), ForeignKey("fleets.fleet_id"), nullable=True)

    # Vehicle details
    make = Column(String(50))
    model = Column(String(50))
    year = Column(Integer)
    colour = Column(String(30))
    plate_number = Column(String(20), index=True)
    odometer_at_registration = Column(Integer)

    # Current status
    status = Column(String(20), default=VehicleStatus.HEALTHY)
    latest_dcp_id = Column(String(50))
    latest_scan_at = Column(DateTime(timezone=True))
    latest_score = Column(Integer)
    latest_location_lat = Column(Float)
    latest_location_lng = Column(Float)
    latest_location_at = Column(DateTime(timezone=True))
    current_speed_kmh = Column(Float, default=0)
    odometer_current = Column(Integer)
    fuel_level_percent = Column(Float)

    # OBD connection
    obd_adapter_id = Column(String(100))   # Hardware adapter ID
    obd_connection_method = Column(String(20))  # bluetooth, wifi, manufacturer_api
    manufacturer_api_token = Column(String(500))  # Encrypted OAuth token

    # Scan schedule
    hourly_scan_enabled = Column(Boolean, default=True)
    next_scan_due = Column(DateTime(timezone=True))

    # Active faults
    has_active_faults = Column(Boolean, default=False)
    active_fault_codes = Column(JSONB, default=list)
    fault_detected_at = Column(DateTime(timezone=True))

    # Workshop
    assigned_workshop_id = Column(String(50))
    workshop_job_id = Column(String(50))

    is_active = Column(Boolean, default=True)
    registered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    owner = relationship("User", back_populates="vehicles")
    fleet = relationship("Fleet", back_populates="vehicles")
    scans = relationship("HourlyScan", back_populates="vehicle", order_by="HourlyScan.scanned_at.desc()")
    location_history = relationship("LocationHistory", back_populates="vehicle")

    __table_args__ = (
        Index('idx_vehicle_owner', 'owner_id'),
        Index('idx_vehicle_fleet', 'fleet_id'),
        Index('idx_vehicle_status', 'status'),
    )


class HourlyScan(Base):
    """
    Every hourly OBD scan result.
    Appended to DCP as condition history.
    Each scan is hashed for integrity.
    """
    __tablename__ = "hourly_scans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id = Column(String(50), unique=True, nullable=False)
    vehicle_id = Column(String(50), ForeignKey("tracked_vehicles.vehicle_id"), nullable=False)
    vin = Column(String(17), nullable=False)
    dcp_id = Column(String(50))  # Links to parent DCP

    # Scan source
    scan_method = Column(String(20))  # obd_hardware, manufacturer_api, manual
    adapter_id = Column(String(100))

    # OBD Data
    obd2_status = Column(String(20))
    fault_codes = Column(JSONB, default=list)
    fault_codes_cleared = Column(JSONB, default=list)  # Faults cleared since last scan
    fault_codes_new = Column(JSONB, default=list)      # New faults since last scan
    readiness_monitors = Column(JSONB, default=dict)

    # Live sensor data
    engine_rpm = Column(Float)
    coolant_temp_c = Column(Float)
    oil_temp_c = Column(Float)
    throttle_position_pct = Column(Float)
    battery_voltage = Column(Float)
    fuel_level_pct = Column(Float)
    odometer_km = Column(Integer)
    speed_kmh = Column(Float)

    # Location at time of scan
    latitude = Column(Float)
    longitude = Column(Float)

    # Health score for this scan
    health_score = Column(Integer)
    health_status = Column(String(20))  # healthy, warning, critical

    # Hash for integrity
    scan_hash = Column(String(64))

    # Alerts triggered
    alerts_triggered = Column(JSONB, default=list)
    workshop_referral_triggered = Column(Boolean, default=False)

    scanned_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationship
    vehicle = relationship("TrackedVehicle", back_populates="scans")

    __table_args__ = (
        Index('idx_scan_vehicle', 'vehicle_id'),
        Index('idx_scan_vin', 'vin'),
        Index('idx_scan_time', 'scanned_at'),
    )


class LocationHistory(Base):
    """
    Vehicle location history for live tracking.
    Points stored every 30 seconds when vehicle is moving.
    Pruned after 90 days to manage storage.
    """
    __tablename__ = "location_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(String(50), ForeignKey("tracked_vehicles.vehicle_id"), nullable=False)
    vin = Column(String(17))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed_kmh = Column(Float, default=0)
    heading = Column(Float)  # Degrees 0-360
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationship
    vehicle = relationship("TrackedVehicle", back_populates="location_history")

    __table_args__ = (
        Index('idx_location_vehicle_time', 'vehicle_id', 'recorded_at'),
    )


class VehicleAlert(Base):
    """
    Alerts generated from scan results.
    Sent to owner/fleet manager via push + SMS.
    """
    __tablename__ = "vehicle_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id = Column(String(50), unique=True, nullable=False)
    vehicle_id = Column(String(50), ForeignKey("tracked_vehicles.vehicle_id"), nullable=False)
    user_id = Column(String(50), ForeignKey("users.user_id"), nullable=False)

    alert_type = Column(String(50))  # fault_detected, speed_exceeded, geofence_breach, etc
    severity = Column(String(20))    # info, warning, critical
    title = Column(String(100))
    message = Column(Text)
    fault_codes = Column(JSONB, default=list)

    # Resolution
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))
    resolution_notes = Column(Text)

    # Notification status
    push_sent = Column(Boolean, default=False)
    sms_sent = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index('idx_alert_vehicle', 'vehicle_id'),
        Index('idx_alert_user', 'user_id'),
        Index('idx_alert_resolved', 'is_resolved'),
    )
