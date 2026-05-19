"""
routers/dcp.py
All DCP API endpoints.

ENDPOINTS:
POST /dcp/issue              — Issue new DCP (inspector auth required)
GET  /dcp/verify/{dcp_id}   — Public verification (no auth)
GET  /dcp/vehicle/{vin}      — Vehicle history (API key required)
GET  /dcp/{dcp_id}           — Get DCP details (API key required)
"""

from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import get_current_user, verify_api_key
from backend.schemas.dcp import IssueDCPRequest, DCPResponse, DCPVerificationResponse
from backend.services.dcp_service import issue_dcp, verify_dcp, get_vehicle_history

router = APIRouter(prefix="/dcp", tags=["Digital Condition Passport"])


@router.post(
    "/issue",
    response_model=dict,
    summary="Issue a new Digital Condition Passport",
    description="Creates and cryptographically hashes a new DCP. Requires inspector authentication."
)
async def issue_dcp_endpoint(
    request: IssueDCPRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Issue a new DCP.
    
    - Requires valid JWT (inspector login)
    - Generates SHA-256 hash from inspection data
    - Writes hash to append-only ledger
    - Generates QR code
    - Returns complete DCP record
    """
    result = await issue_dcp(request, db)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "success": True,
        "message": "Digital Condition Passport issued successfully",
        "data": result
    }


@router.get(
    "/verify/{dcp_id}",
    response_model=dict,
    summary="Verify a Digital Condition Passport",
    description="Public endpoint. Anyone with a DCP ID can verify authenticity. No authentication required."
)
async def verify_dcp_endpoint(
    dcp_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Public DCP verification.
    
    - No authentication required
    - Recomputes SHA-256 hash and compares with stored hash
    - Returns full verification result
    - Logs every verification attempt
    
    This is what gets scanned when a buyer hits the QR code on the windshield.
    """
    client_ip = request.client.host if request.client else None

    result = await verify_dcp(
        dcp_id=dcp_id,
        db=db,
        requester_ip=client_ip,
        method="API"
    )

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "success": True,
        "data": result
    }


@router.get(
    "/vehicle/{vin}",
    response_model=dict,
    summary="Get full DCP history for a VIN",
    description="Returns all DCPs ever issued for a vehicle. Requires API key."
)
async def vehicle_history_endpoint(
    vin: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_api_key)
):
    """
    Vehicle condition history.
    
    - Requires API key (licensed dealers, banks, insurers)
    - Returns all DCPs for the VIN in reverse chronological order
    - This is the Condition Registry in embryonic form
    """
    result = await get_vehicle_history(vin.upper(), db)

    return {
        "success": True,
        "data": result
    }


@router.get(
    "/{dcp_id}",
    response_model=dict,
    summary="Get DCP details",
    description="Get full DCP record. Public for basic info, API key for full inspection data."
)
async def get_dcp_endpoint(
    dcp_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get DCP record.
    Public access returns summary.
    """
    result = await verify_dcp(dcp_id=dcp_id, db=db, method="DIRECT")

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    return {
        "success": True,
        "data": result
    }
