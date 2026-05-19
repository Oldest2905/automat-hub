"""
schemas/escrow.py
Pydantic schemas for Escrow request and response validation.
"""

from pydantic import BaseModel, Field, EmailStr, validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class EscrowStatusEnum(str, Enum):
    INITIATED = "INITIATED"
    FUNDED = "FUNDED"
    DCP_MATCHED = "DCP_MATCHED"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


# ─── REQUEST SCHEMAS ────────────────────────────────────────

class BuyerInfo(BaseModel):
    name: str = Field(..., max_length=100)
    email: str = Field(..., description="Buyer email address")
    phone: str = Field(..., description="Buyer phone e.g. +2348012345678")


class SellerInfo(BaseModel):
    name: str = Field(..., max_length=100)
    account: Optional[str] = None


class CreateEscrowRequest(BaseModel):
    dcp_id: str = Field(..., description="DCP ID of the vehicle being purchased")
    vin: str = Field(..., min_length=17, max_length=17)
    buyer: BuyerInfo
    seller: SellerInfo
    amount_usd: Decimal = Field(..., gt=0, description="Transaction amount in USD")
    fx_rate: Optional[Decimal] = Field(None, description="NGN/USD rate at time of deposit")
    notes: Optional[str] = None

    @validator('vin')
    def vin_uppercase(cls, v):
        return v.upper()


class ConfirmDepositRequest(BaseModel):
    escrow_id: str
    payment_reference: str = Field(..., description="Paystack payment reference")
    payment_channel: str = Field(default="bank_transfer")


class ConfirmDeliveryRequest(BaseModel):
    escrow_id: str
    buyer_confirmation_code: str = Field(
        ...,
        description="Code sent to buyer on delivery"
    )
    notes: Optional[str] = None


class RaiseDisputeRequest(BaseModel):
    escrow_id: str
    reason: str = Field(..., min_length=20, description="Detailed dispute reason")


# ─── RESPONSE SCHEMAS ───────────────────────────────────────

class EscrowEventResponse(BaseModel):
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    triggered_by: str
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class EscrowResponse(BaseModel):
    escrow_id: str
    dcp_id: str
    vin: str

    buyer_name: str
    seller_name: str

    amount_usd: Decimal
    platform_fee_percent: float
    platform_fee_amount: Optional[Decimal]
    seller_net_amount: Optional[Decimal]

    status: str

    dcp_verified: bool
    physical_delivery_confirmed: bool
    buyer_acknowledged: bool

    initiated_at: datetime
    funded_at: Optional[datetime]
    dcp_matched_at: Optional[datetime]
    delivery_confirmed_at: Optional[datetime]
    completed_at: Optional[datetime]
    expiry_at: Optional[datetime]

    events: List[EscrowEventResponse] = []

    class Config:
        from_attributes = True


class EscrowSummaryResponse(BaseModel):
    escrow_id: str
    dcp_id: str
    vin: str
    status: str
    amount_usd: Decimal
    buyer_name: str
    initiated_at: datetime

    class Config:
        from_attributes = True
