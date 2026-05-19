"""
core/security.py
JWT authentication and API key management.
Protects DCP issuance and escrow endpoints.
"""

import bcrypt  # Added for stable password verification
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from backend.config import settings

# Keep this for other utilities, but we will use bcrypt directly for verify
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_password(password: str) -> str:
    """
    Uses direct bcrypt for hashing to ensure compatibility with 
    the verification logic and avoid passlib metadata errors.
    """
    # bcrypt requires bytes; salt is generated automatically
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    MODIFIED: Uses direct bcrypt to avoid the '72 bytes' error and 
    passlib version mismatch on Windows/Linux environments.
    """
    try:
        # We must encode both the password and the stored hash to bytes
        return bcrypt.checkpw(
            plain_password.encode('utf-8'), 
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        print(f"DEBUG: Password verification failed: {e}")
        return False

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create JWT access token for authenticated users.
    Used by inspectors and admin dashboard.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)
) -> dict:
    """
    Dependency: validates JWT bearer token.
    Use in routes that require inspector/admin auth.
    """
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return {"user_id": user_id, "role": payload.get("role", "inspector")}


async def verify_api_key(
    api_key: str = Security(api_key_header)
) -> bool:
    """
    Dependency: validates API key for third-party access.
    Used by licensed dealers and partner integrations.
    """
    if not api_key or api_key != settings.API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key. Contact support@automatcorp.org.ng"
        )
    return True