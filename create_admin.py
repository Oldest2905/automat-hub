import asyncio
from backend.core.database import SessionLocal
from backend.models.user import User # Adjust path if your model is elsewhere
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

async def create_admin():
    db = SessionLocal()
    hashed_password = pwd_context.hash("Onimisi@1")
    admin_user = User(
        email="ceo@automatcorp.org.ng",
        password_hash=hashed_password,
        full_name="CEO Automat",
        role="admin",
        is_active=True,
        is_verified=True,
        # fill in other required fields like phone, user_id, etc.
        phone="08064009401",
        user_id="ADMINPETER"
    )
    db.add(admin_user)
    try:
        db.commit()
        print("Admin user created successfully!")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(create_admin())