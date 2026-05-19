import asyncio
import uuid
import bcrypt
from datetime import datetime, timezone
from sqlalchemy import select

# Import your database session factory
from backend.core.database import AsyncSessionLocal

# --- DYNAMIC MODEL LOADING ---
import backend.models.user as user_mod
import backend.models.fleet as fleet_mod
import backend.models.escrow as escrow_mod
import backend.models.workshop as workshop_mod
import backend.models.dcp as dcp_mod

User = user_mod.User
# ------------------------------

async def seed_user():
    async with AsyncSessionLocal() as session:
        try:
            # 1. Check if user already exists
            query = select(User).where(User.email == "ceo@automatcorp.org.ng")
            result = await session.execute(query)
            existing = result.scalar_one_or_none()

            if existing:
                print("--- [INFO] User already exists! ---")
                return

            # 2. Hash the password manually using bcrypt
            password = "Onimisi@1"
            # bcrypt requires bytes, so we encode the string
            salt = bcrypt.gensalt()
            hashed_pw = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

            # 3. Create the admin user instance
            admin = User(
                id=uuid.uuid4(),
                user_id="ADMIN001",
                email="ceo@automatcorp.org.ng",
                phone="08100000000",
                full_name="CEO Automat",
                password_hash=hashed_pw,
                role="admin",
                is_active=True,
                is_verified=True,
                email_verified=True,
                phone_verified=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc)
            )

            session.add(admin)
            await session.commit()
            print("--- [SUCCESS] Admin user created successfully! ---")
            
        except Exception as e:
            print(f"--- [ERROR] Seeding failed: {e} ---")
            await session.rollback()
        finally:
            await session.close()

if __name__ == "__main__":
    asyncio.run(seed_user())