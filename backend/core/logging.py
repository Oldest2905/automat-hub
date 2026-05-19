"""
core/logging.py
Structured logging for the entire application.
Every request, error, and key event is logged.
Logs go to console in dev, to file + Sentry in production.
"""

import sys
from loguru import logger
from backend.config import settings


def setup_logging():
    """Configure logging for the application."""

    # Remove default logger
    logger.remove()

    # Console logging — always on
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stdout,
        format=log_format,
        level="DEBUG" if settings.DEBUG else "INFO",
        colorize=True
    )

    # File logging — production only
    if settings.ENVIRONMENT == "production":
        logger.add(
            "logs/automat_{time:YYYY-MM-DD}.log",
            rotation="00:00",        # New file every day
            retention="30 days",     # Keep 30 days of logs
            compression="zip",       # Compress old logs
            format=log_format,
            level="INFO",
            enqueue=True             # Thread-safe async logging
        )

    # Sentry error tracking — production only
    if settings.ENVIRONMENT == "production" and hasattr(settings, 'SENTRY_DSN') and settings.SENTRY_DSN:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=0.1,  # Track 10% of requests for performance
            environment=settings.ENVIRONMENT
        )
        logger.info("Sentry error tracking enabled")

    logger.info(f"Logging configured | Environment: {settings.ENVIRONMENT}")
    return logger


# Export the configured logger
log = logger
