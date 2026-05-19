"""
schemas/dcp.py
Pydantic schemas for DCP request and response validation.
These define the exact shape of data in and out of the API.
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class DCPGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class OBD2StatusEnum(str, Enum):
    CLEAR = "Clear"
    FAULTS_PRESENT = "Faults Present"
    NOT_READY = "Not Ready"


class ConditionEnum(str, Enum):
    NOMINAL = "Nominal"
    GOOD = "Good"
    FAIR = "Fair"
    POOR = "Poor"
    CRITICAL = "Critical"
    FACTORY = "Factory"


# ─── REQUEST SCHEMAS ────────────────────────────────────────

class VehicleInfo(BaseModel):
    vin: str = Field(..., min_length=17, max_length=17, description="17-character VIN")
    make: str = Field(..., max_length=50)
    model: str = Field(..., max_length=50)
    year: int = Field(..., ge=1990, le=2030)
    colour: str = Field(..., max_length=30)
    odometer: int = Field(..., ge=0)

    @validator('vin')
    def vin_must_be_uppercase(cls, v):
        return v.upper()


class InspectionData(BaseModel):
    # OBD-II
    obd2_status: OBD2StatusEnum
    obd2_fault_codes: List[str] = Field(default_factory=list)
    obd2_readiness_monitors: Dict[str, bool] = Field(default_factory=dict)

    # Engine
    engine_compression: ConditionEnum
    engine_oil_condition: ConditionEnum
    coolant_condition: ConditionEnum
    timing_belt_condition: ConditionEnum

    # Transmission
    transmission_condition: ConditionEnum
    transmission_fluid: ConditionEnum

    # Chassis & Body
    frame_alignment: str = Field(default="Factory")
    rust_assessment: ConditionEnum
    accident_history_indicators: bool = False
    paint_uniformity: ConditionEnum

    # Electrical
    battery_health: ConditionEnum
    alternator_output: ConditionEnum
    electronics_status: ConditionEnum

    # Safety
    brake_condition: ConditionEnum
    tyre_condition: Dict[str, str] = Field(default_factory=dict)
    airbag_status: ConditionEnum
    abs_status: ConditionEnum

    # AI
    ai_condition_grade: str
    ai_confidence_score: float = Field(..., ge=0.0, le=1.0)
    ai_flags: List[str] = Field(default_factory=list)

    # Full checklist — all 150 points
    checklist_results: Dict[str, Any] = Field(
        ...,
        description="Full 150-point checklist results"
    )

    # Overall score
    score: int = Field(..., ge=0, le=100)

    # Inspector notes
    inspector_notes: Optional[str] = None


class IssueDCPRequest(BaseModel):
    vehicle: VehicleInfo
    inspection: InspectionData
    auditor_id: str = Field(..., description="Inspector ID e.g. ATH-QA-084")
    warranty_days: int = Field(default=30, ge=0, le=365)


# ─── RESPONSE SCHEMAS ───────────────────────────────────────

class HashRecord(BaseModel):
    hash: str
    hash_algorithm: str
    issued_at: datetime

    class Config:
        from_attributes = True


class DCPResponse(BaseModel):
    dcp_id: str
    vin: str
    make: str
    model: str
    year: int
    score: int
    grade: str
    status: str
    auditor_id: str
    issued_at: datetime
    warranty_expiry: Optional[datetime]
    verification_url: str
    hash: str
    hash_algorithm: str

    class Config:
        from_attributes = True


class DCPVerificationResponse(BaseModel):
    dcp_id: str
    vin: str
    make: str
    model: str
    year: str
    colour: str
    score: int
    grade: str
    status: str
    issued_at: datetime
    warranty_expiry: Optional[datetime]
    issuer: str
    auditor_id: str

    # Verification result
    is_valid: bool
    stored_hash: str
    recomputed_hash: str
    hashes_match: bool
    verified_at: str
    algorithm: str
    tamper_evident: bool

    # Inspection summary
    obd2_status: Optional[str]
    engine_compression: Optional[str]
    frame_alignment: Optional[str]
    accident_history: Optional[bool]
    ai_condition_grade: Optional[str]

    class Config:
        from_attributes = True


class VehicleHistoryResponse(BaseModel):
    vin: str
    total_inspections: int
    dcps: List[DCPResponse]

    class Config:
        from_attributes = True
