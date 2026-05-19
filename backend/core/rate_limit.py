"""
core/rate_limit.py
Rate limiting to protect the API from abuse.
Uses Redis to track request counts per IP.

Limits:
- Public endpoints: 60 requests/minute
- Auth endpoints: 10 requests/minute (prevents brute force)
- Reseller API: per-key limits (handled in reseller router)
"""

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, Response

# Create limiter using client IP address
limiter = Limiter(key_func=get_remote_address)


def get_rate_limit_handler():
    """Return the rate limit exceeded handler for FastAPI."""
    return RateLimitExceeded, _rate_limit_exceeded_handler
