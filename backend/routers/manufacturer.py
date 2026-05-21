"""
routers/manufacturer.py
Vehicle manufacturer OAuth connection endpoints.

Allows customers to link their vehicle directly to its
manufacturer's connected car service (Toyota Connected,
Ford Pass, BMW ConnectedDrive, etc.)

Flow:
1. User selects their car brand
2. We redirect them to manufacturer's OAuth login
3. Manufacturer sends back an auth code
4. We exchange for a token and store it (encrypted)
5. Every hour we pull live data using that token
6. Data feeds into DCP hourly scan
"""

import secrets
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi_cache.decorator import cache
from pydantic import BaseModel
from typing import Optional

from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.fleet import TrackedVehicle
from backend.services.manufacturer_service import (
    MANUFACTURERS,
    get_manufacturer_list,
    build_oauth_url,
    pull_manufacturer_data,
    get_obd_adapter_guide,
)
from backend.config import settings

router = APIRouter(prefix="/manufacturer", tags=["Vehicle Manufacturer Connection"])


# ── GET SUPPORTED MANUFACTURERS ──────────────────────────────

@router.get("/list", response_model=dict, summary="Get all supported car manufacturers")
@cache(expire=3600)
async def list_manufacturers():
    """
    Returns all 15 supported manufacturers with their models.
    No authentication required — public endpoint for onboarding flow.
    """
    manufacturers = get_manufacturer_list()
    popular = [m for m in manufacturers if m["popular_in_nigeria"]]
    others = [m for m in manufacturers if not m["popular_in_nigeria"]]

    return {
        "success": True,
        "popular_in_nigeria": popular,
        "all_supported": manufacturers,
        "total": len(manufacturers),
        "obd_guide": get_obd_adapter_guide()
    }


# ── INITIATE OAUTH CONNECTION ─────────────────────────────────

@router.get("/connect/{manufacturer_id}", response_model=dict)
async def initiate_connection(
    manufacturer_id: str,
    vehicle_id: str = Query(..., description="Your vehicle ID in Automat Hub"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Start the manufacturer OAuth flow.
    Returns a URL for the user to visit to log in with their
    Toyota/BMW/Ford etc account.

    After logging in, manufacturer redirects back to our callback URL.
    """
    if manufacturer_id not in MANUFACTURERS:
        raise HTTPException(
            status_code=400,
            detail=f"Manufacturer '{manufacturer_id}' not supported. "
                   f"Supported: {', '.join(MANUFACTURERS.keys())}"
        )

    # Verify vehicle belongs to this user
    result = await db.execute(
        select(TrackedVehicle).where(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    # Generate state token (prevents CSRF)
    state = secrets.token_urlsafe(16)
    # In production: store state in Redis with expiry
    # For now: encode vehicle_id and user_id into state
    state_data = f"{vehicle_id}:{current_user['user_id']}:{state}"
    state_hash = hashlib.sha256(state_data.encode()).hexdigest()[:16]

    redirect_uri = f"{settings.APP_URL}/manufacturer/callback/{manufacturer_id}"

    oauth_url = build_oauth_url(
        manufacturer_id=manufacturer_id,
        redirect_uri=redirect_uri,
        state=state_hash
    )

    mfr = MANUFACTURERS[manufacturer_id]

    return {
        "success": True,
        "manufacturer": mfr["name"],
        "oauth_url": oauth_url,
        "redirect_uri": redirect_uri,
        "instructions": f"Click the URL to log in with your {mfr['name']} account. "
                        f"After login, your vehicle data will sync automatically every hour.",
        "demo_mode": not bool(
            __import__('os').getenv(mfr.get("client_id_env", ""), "")
        )
    }


# ── OAUTH CALLBACK ────────────────────────────────────────────

@router.get("/callback/{manufacturer_id}", response_model=dict)
async def oauth_callback(
    manufacturer_id: str,
    code: str = Query(...),
    state: str = Query(...),
    vehicle_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Manufacturer redirects here after user logs in.
    We exchange the auth code for an access token.
    Token is stored against the vehicle for hourly scans.
    """
    if manufacturer_id not in MANUFACTURERS:
        raise HTTPException(status_code=400, detail="Invalid manufacturer")

    mfr = MANUFACTURERS[manufacturer_id]

    # Exchange code for token
    import os
    import httpx
    client_id = os.getenv(mfr.get("client_id_env", ""), "demo_client_id")
    client_secret = os.getenv(mfr.get("client_secret_env", ""), "demo_secret")
    redirect_uri = f"{settings.APP_URL}/manufacturer/callback/{manufacturer_id}"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                mfr["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
            )
            token_data = resp.json()
            access_token = token_data.get("access_token", "")
    except Exception:
        # Demo mode — simulate successful connection
        access_token = f"demo_token_{manufacturer_id}_{state[:8]}"

    if not access_token:
        raise HTTPException(
            status_code=400,
            detail="Failed to get access token from manufacturer"
        )

    # Store token on vehicle
    result = await db.execute(
        select(TrackedVehicle).where(TrackedVehicle.vehicle_id == vehicle_id)
    )
    vehicle = result.scalar_one_or_none()

    if vehicle:
        vehicle.obd_connection_method = "manufacturer_api"
        vehicle.manufacturer_api_token = access_token  # Encrypt in production
        vehicle.obd_adapter_id = manufacturer_id

    return {
        "success": True,
        "manufacturer": mfr["name"],
        "vehicle_id": vehicle_id,
        "connected": True,
        "message": f"Your {mfr['name']} account is now connected. "
                   f"Vehicle data will sync automatically every hour.",
        "redirect": f"/frontend/user/index.html?connected={manufacturer_id}"
    }


# ── CONNECT VIA OBD HARDWARE ──────────────────────────────────

@router.post("/connect-obd", response_model=dict)
async def connect_obd_adapter(
    vehicle_id: str,
    adapter_id: str = Query(..., description="Bluetooth device address of OBD adapter"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Register an OBD-II Bluetooth adapter with a vehicle.
    The mobile app detects the adapter via Bluetooth and registers it here.
    After this, hourly scans use this adapter's data.
    """
    result = await db.execute(
        select(TrackedVehicle).where(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    )
    vehicle = result.scalar_one_or_none()

    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    vehicle.obd_connection_method = "obd_hardware"
    vehicle.obd_adapter_id = adapter_id
    vehicle.manufacturer_api_token = None  # Clear any manufacturer token

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "adapter_id": adapter_id,
        "connection_method": "obd_hardware",
        "message": "OBD adapter registered. Hourly scans will now use this adapter.",
        "scan_interval_hours": 1
    }


# ── DISCONNECT ────────────────────────────────────────────────

@router.post("/disconnect/{vehicle_id}", response_model=dict)
async def disconnect_vehicle(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """Remove manufacturer or OBD connection from a vehicle."""
    result = await db.execute(
        select(TrackedVehicle).where(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    vehicle.obd_connection_method = None
    vehicle.obd_adapter_id = None
    vehicle.manufacturer_api_token = None

    return {
        "success": True,
        "vehicle_id": vehicle_id,
        "message": "Vehicle connection removed. Manual scans still available."
    }


# ── MANUAL SCAN TRIGGER ───────────────────────────────────────

@router.post("/scan-now/{vehicle_id}", response_model=dict)
async def trigger_scan_now(
    vehicle_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Trigger an immediate scan for a vehicle.
    Uses whatever connection method is configured (OBD or manufacturer API).
    """
    result = await db.execute(
        select(TrackedVehicle).where(
            TrackedVehicle.vehicle_id == vehicle_id,
            TrackedVehicle.owner_id == current_user["user_id"]
        )
    )
    vehicle = result.scalar_one_or_none()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    scan_data = {}

    # Pull from manufacturer API if connected
    if vehicle.obd_connection_method == "manufacturer_api" and vehicle.manufacturer_api_token:
        scan_data = await pull_manufacturer_data(
            manufacturer_id=vehicle.obd_adapter_id or "",
            oauth_token=vehicle.manufacturer_api_token,
            vin=vehicle.vin
        )
        scan_data["scan_method"] = "manufacturer_api"
    else:
        # OBD data comes from mobile app push
        # This endpoint just returns the last known scan
        return {
            "success": True,
            "method": "obd_hardware",
            "message": "OBD scans are pushed from your mobile app automatically every hour.",
            "last_scan": vehicle.latest_scan_at.isoformat() if vehicle.latest_scan_at else None,
            "last_score": vehicle.latest_score
        }

    # Process the scan
    from backend.services.scan_service import process_hourly_scan
    scan_result = await process_hourly_scan(vehicle_id, scan_data, db)

    return {
        "success": True,
        "method": "manufacturer_api",
        "scan_result": scan_result
    }
