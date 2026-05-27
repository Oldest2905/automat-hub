"""
core/database.py
PostgreSQL database connection and session management.
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import text
from fastapi import Request
from backend.config import settings

# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "server_settings": {
            "jit": "off",
        }
    }
)

# Async session factory
AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

class Base(DeclarativeBase):
    pass

async def get_db(request: Request):
    """
    Dependency injection for database sessions with RLS context.
    It inspects the request for an auth token, decodes it to find the user,
    and sets PostgreSQL session variables (`app.current_user_id`, `app.current_role`)
    for the duration of the transaction. This enables Row Level Security.
    If no valid token is found, it proceeds as an anonymous request.
    """
    token = request.headers.get("authorization")
    current_user = None

    if token and token.startswith("Bearer "):
        token = token.split(" ")[1]
        try:
            from jose import jwt
            # Assumes ALGORITHM is defined in settings, which is standard practice
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[getattr(settings, 'ALGORITHM', 'HS256')])
            current_user = {
                "user_id": payload.get("sub"),
                "role": payload.get("role", "private_owner")
            }
        except Exception:
            # Invalid token, treat as anonymous
            current_user = None

    async with AsyncSessionLocal() as session:
        try:
            # Use a transaction block to ensure SET LOCAL is scoped correctly
            async with session.begin():
                if current_user and current_user.get("user_id"):
                    await session.execute(text(f"SET LOCAL app.current_user_id = '{current_user['user_id']}'"))
                    await session.execute(text(f"SET LOCAL app.current_role = '{current_user['role']}'"))
                yield session
        except Exception:
            # The 'async with session.begin()' handles rollback automatically on exception.
            raise

async def init_db():
    """Initialize database tables on startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            print("DATABASE: Connection established and tables verified.")
    except Exception as e:
        print(f"DATABASE STARTUP ERROR: {e}")