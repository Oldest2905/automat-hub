"""
routers/tracking.py
WebSocket endpoint for live fleet GPS tracking.
Fleet owners connect here to receive real-time vehicle location updates.

CONNECTION: ws://yourserver.com/ws/fleet/{fleet_id}?token=JWT_TOKEN

The server pushes location updates every 10 seconds per vehicle.
Clients can also send commands: {"action": "focus", "vehicle_id": "VEH-xxx"}
"""

import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.core.database import AsyncSessionLocal
from backend.core.security import decode_access_token
from backend.models.fleet import TrackedVehicle, LocationHistory

router = APIRouter(tags=["Live Tracking"])

# Store active WebSocket connections per fleet
# {fleet_id: {websocket1, websocket2, ...}}
active_connections: Dict[str, Set[WebSocket]] = {}


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, fleet_id: str):
        await websocket.accept()
        if fleet_id not in self.active:
            self.active[fleet_id] = set()
        self.active[fleet_id].add(websocket)

    def disconnect(self, websocket: WebSocket, fleet_id: str):
        if fleet_id in self.active:
            self.active[fleet_id].discard(websocket)
            if not self.active[fleet_id]:
                del self.active[fleet_id]

    async def broadcast_to_fleet(self, fleet_id: str, data: dict):
        """Send update to all clients watching this fleet."""
        if fleet_id not in self.active:
            return
        dead = set()
        for ws in self.active[fleet_id]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.active[fleet_id].discard(ws)


manager = ConnectionManager()


@router.websocket("/ws/fleet/{fleet_id}")
async def fleet_tracking_websocket(
    websocket: WebSocket,
    fleet_id: str,
    token: str = Query(...)
):
    """
    WebSocket endpoint for live fleet tracking.

    Client connects with JWT token as query param.
    Server pushes vehicle locations every 10 seconds.

    Message format pushed to client:
    {
        "type": "fleet_update",
        "fleet_id": "FLT-xxx",
        "timestamp": "2026-04-13T10:00:00Z",
        "vehicles": [
            {
                "vehicle_id": "VEH-xxx",
                "vin": "1C4...",
                "lat": 7.3775,
                "lng": 3.9470,
                "speed_kmh": 45.2,
                "status": "healthy",
                "health_score": 94,
                "plate_number": "OY-123-ABC"
            }
        ]
    }
    """
    # Validate JWT token
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token")
            return
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    await manager.connect(websocket, fleet_id)

    try:
        # Send initial fleet snapshot immediately on connect
        await send_fleet_snapshot(websocket, fleet_id, user_id)

        # Start background push loop
        push_task = asyncio.create_task(
            push_location_updates(websocket, fleet_id, user_id)
        )

        # Listen for client commands
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                message = json.loads(data)

                # Handle client commands
                if message.get("action") == "ping":
                    await websocket.send_json({"type": "pong"})

                elif message.get("action") == "focus":
                    # Client wants detailed data for one vehicle
                    vehicle_id = message.get("vehicle_id")
                    if vehicle_id:
                        await send_vehicle_detail(websocket, vehicle_id)

            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        manager.disconnect(websocket, fleet_id)
        push_task.cancel()
    except Exception as e:
        manager.disconnect(websocket, fleet_id)


async def send_fleet_snapshot(websocket: WebSocket, fleet_id: str, user_id: str):
    """Send complete fleet status on initial connection."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TrackedVehicle).where(
                TrackedVehicle.fleet_id == fleet_id
            )
        )
        vehicles = result.scalars().all()

        vehicle_data = [
            {
                "vehicle_id": v.vehicle_id,
                "vin": v.vin,
                "make": v.make,
                "model": v.model,
                "plate_number": v.plate_number,
                "lat": v.latest_location_lat,
                "lng": v.latest_location_lng,
                "speed_kmh": v.current_speed_kmh or 0,
                "status": v.status,
                "health_score": v.latest_score,
                "has_faults": v.has_active_faults,
                "fuel_level": v.fuel_level_percent,
                "last_seen": v.latest_location_at.isoformat() if v.latest_location_at else None
            }
            for v in vehicles
            if v.latest_location_lat and v.latest_location_lng
        ]

        await websocket.send_json({
            "type": "fleet_snapshot",
            "fleet_id": fleet_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vehicle_count": len(vehicle_data),
            "vehicles": vehicle_data
        })


async def push_location_updates(websocket: WebSocket, fleet_id: str, user_id: str):
    """Push location updates every 10 seconds."""
    while True:
        await asyncio.sleep(10)
        try:
            await send_fleet_snapshot(websocket, fleet_id, user_id)
        except Exception:
            break


async def send_vehicle_detail(websocket: WebSocket, vehicle_id: str):
    """Send detailed single vehicle data on focus."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TrackedVehicle).where(TrackedVehicle.vehicle_id == vehicle_id)
        )
        v = result.scalar_one_or_none()
        if not v:
            return

        await websocket.send_json({
            "type": "vehicle_detail",
            "vehicle_id": vehicle_id,
            "data": {
                "vin": v.vin,
                "make": v.make,
                "model": v.model,
                "year": v.year,
                "plate_number": v.plate_number,
                "status": v.status,
                "health_score": v.latest_score,
                "active_faults": v.active_fault_codes or [],
                "lat": v.latest_location_lat,
                "lng": v.latest_location_lng,
                "speed_kmh": v.current_speed_kmh,
                "fuel_level": v.fuel_level_percent,
                "odometer_km": v.odometer_current,
                "last_scan": v.latest_scan_at.isoformat() if v.latest_scan_at else None
            }
        })


async def push_alert_to_fleet(fleet_id: str, alert: dict):
    """
    Called by scan service when a fault is detected.
    Pushes alert to all connected fleet owner clients immediately.
    """
    await manager.broadcast_to_fleet(fleet_id, {
        "type": "alert",
        "fleet_id": fleet_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert": alert
    })
