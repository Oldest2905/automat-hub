"""
models/archive.py
Archive tables for soft-deleted or permanently removed entities.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON

from backend.core.database import Base

class DeletedVehicleArchive(Base):
    __tablename__ = "deleted_vehicle_archive"

    archive_id = Column(String, primary_key=True, default=lambda: f"ARC-{str(uuid.uuid4())[:8].upper()}")
    original_vehicle_id = Column(String, index=True)
    vin = Column(String, index=True)
    owner_id = Column(String, index=True)
    deleted_by = Column(String)
    deleted_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    
    vehicle_data = Column(JSON, default=dict)
    telemetry_snapshot = Column(JSON, default=dict)