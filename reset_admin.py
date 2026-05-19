import asyncio
import uuid
from backend.core.database import AsyncSessionLocal
from backend.core.security import hash_password
from sqlalchemy import text

async def reset():
    print("Generating hash and record details for admin...")
    new_hash = hash_password('Onimisi@1')
    
    # Generate unique IDs
    primary_id = str(uuid.uuid4())
    public_user_id = f"ADM-{str(uuid.uuid4())[:8].upper()}"
    
    async with AsyncSessionLocal() as session:
        # 1. Clear old admin data
        print("Cleaning up old admin records...")
        await session.execute(
            text("DELETE FROM users WHERE email = :email"),
            {"email": "ceo@automatcorp.org.ng"}
        )
        
        # 2. Insert fresh admin with all detected mandatory fields
        print("Inserting fresh admin record...")
        query = text("""
            INSERT INTO users (
                id, user_id, email, full_name, password_hash, 
                role, is_active, is_verified, phone, 
                email_verified, phone_verified
            )
            VALUES (
                :id, :u_id, :email, :name, :hash, 
                :role, :active, :verified, :phone, 
                :e_ver, :p_ver
            )
        """)
        
        await session.execute(query, {
            "id": primary_id,
            "u_id": public_user_id,
            "email": "ceo@automatcorp.org.ng",
            "name": "Admin User",
            "hash": new_hash,
            "role": "admin",
            "active": True,
            "verified": True,
            "phone": "+2348000000000",
            "e_ver": True,
            "p_ver": True
        })
        
        await session.commit()
        print(f"SUCCESS: Admin user created!")
        print(f"Login Email: ceo@automatcorp.org.ng")

if __name__ == '__main__':
    asyncio.run(reset())