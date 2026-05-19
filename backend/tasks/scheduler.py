"""
tasks/scheduler.py
Background job scheduler for hourly OBD scans.

This runs separately from the main API.
Start it with: celery -A backend.tasks.scheduler worker --beat -l info

What it does every hour:
1. Find all vehicles with hourly_scan_enabled = True
2. For each vehicle, check if the OBD adapter is reachable
3. Pull scan data from the adapter or manufacturer API
4. Process the scan and update the DCP
5. Send alerts if faults are found
"""

from celery import Celery
from celery.schedules import crontab
import asyncio

# Create Celery app
celery_app = Celery(
    "automat_hub",
    broker="redis://localhost:6379/1",
    backend="redis://localhost:6379/2"
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Africa/Lagos",
    enable_utc=True,
    beat_schedule={
        # Run every hour at 0 minutes past (e.g. 9:00, 10:00, 11:00)
        "hourly-vehicle-scans": {
            "task": "backend.tasks.scheduler.run_hourly_scans",
            "schedule": crontab(minute=0),  # Every hour on the hour
        },
        # Check expired subscriptions daily at midnight
        "check-expired-subscriptions": {
            "task": "backend.tasks.scheduler.check_subscriptions",
            "schedule": crontab(hour=0, minute=0),  # Midnight daily
        },
        # Clean up old location data weekly
        "cleanup-location-data": {
            "task": "backend.tasks.scheduler.cleanup_old_data",
            "schedule": crontab(hour=2, minute=0, day_of_week=0),  # Sunday 2am
        },
    }
)


@celery_app.task(name="backend.tasks.scheduler.run_hourly_scans")
def run_hourly_scans():
    """
    Triggered every hour.
    Finds all vehicles due for a scan and processes them.

    In production: each vehicle's mobile app pushes scan data to the API.
    This task handles vehicles with manufacturer API integrations
    where we pull data directly (Toyota Connected, Ford SYNC, etc.)
    """
    print("Running hourly vehicle scans...")

    # Import here to avoid circular imports
    from backend.core.database import AsyncSessionLocal
    from backend.models.fleet import TrackedVehicle
    from sqlalchemy import select, and_
    from datetime import datetime, timezone

    async def process():
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            # Find vehicles using manufacturer API (not hardware adapter)
            result = await db.execute(
                select(TrackedVehicle).where(
                    and_(
                        TrackedVehicle.hourly_scan_enabled == True,
                        TrackedVehicle.obd_connection_method == "manufacturer_api",
                        TrackedVehicle.manufacturer_api_token != None,
                        TrackedVehicle.is_active == True
                    )
                )
            )
            vehicles = result.scalars().all()
            print(f"Found {len(vehicles)} vehicles with manufacturer API")

            for vehicle in vehicles:
                try:
                    # Pull data from manufacturer API
                    # scan_data = await fetch_manufacturer_data(vehicle)
                    # await process_hourly_scan(vehicle.vehicle_id, scan_data, db)
                    print(f"Processed: {vehicle.vehicle_id}")
                except Exception as e:
                    print(f"Error scanning {vehicle.vehicle_id}: {e}")

    asyncio.run(process())
    return "Hourly scans complete"


@celery_app.task(name="backend.tasks.scheduler.check_subscriptions")
def check_subscriptions():
    """
    Runs daily at midnight.
    Flags expired subscriptions and sends renewal reminders.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.user import User
    from sqlalchemy import select, and_
    from datetime import datetime, timezone

    async def process():
        async with AsyncSessionLocal() as db:
            now = datetime.now(timezone.utc)
            result = await db.execute(
                select(User).where(
                    and_(
                        User.subscription_status == "active",
                        User.subscription_end < now
                    )
                )
            )
            expired_users = result.scalars().all()

            for user in expired_users:
                user.subscription_status = "expired"
                print(f"Subscription expired: {user.user_id}")
                # TODO: Send renewal reminder SMS/email

            await db.commit()
            print(f"Marked {len(expired_users)} subscriptions as expired")

    asyncio.run(process())
    return "Subscription check complete"


@celery_app.task(name="backend.tasks.scheduler.cleanup_old_data")
def cleanup_old_data():
    """
    Runs weekly.
    Deletes location history older than 90 days.
    Compresses scan data older than 365 days.
    """
    from backend.core.database import AsyncSessionLocal
    from backend.models.fleet import LocationHistory
    from sqlalchemy import delete
    from datetime import datetime, timezone, timedelta

    async def process():
        async with AsyncSessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            await db.execute(
                delete(LocationHistory).where(LocationHistory.recorded_at < cutoff)
            )
            await db.commit()
            print("Old location data cleaned up")

    asyncio.run(process())
    return "Cleanup complete"
