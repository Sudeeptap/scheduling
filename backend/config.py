"""
backend/config.py

Application configuration loaded from environment variables.

Validation runs at import time. If OPENAI_API_KEY or CLINIC_TIMEZONE is
missing or invalid the process logs an error and exits before FastAPI binds
to any port.

Usage in other modules:
    from backend.config import settings

    client = openai.OpenAI(api_key=settings.api_key)
    model  = settings.model
    tz     = settings.tz          # zoneinfo.ZoneInfo object
    tz_str = settings.clinic_timezone  # raw string e.g. "Asia/Kolkata"
"""

import logging
import os
import sys
import zoneinfo
from dataclasses import dataclass

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    database_url: str
    clinic_timezone: str
    tz: zoneinfo.ZoneInfo


def _load_settings() -> Settings:
    errors: list[str] = []

    # --- OPENAI_API_KEY (required) ---
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        logger.error(
            "OPENAI_API_KEY is not set or is empty. "
            "Set this environment variable to your OpenAI API key before starting."
        )
        errors.append("OPENAI_API_KEY")

    # --- CLINIC_TIMEZONE (required, must be valid IANA identifier) ---
    tz_str = os.environ.get("CLINIC_TIMEZONE", "").strip()
    tz: zoneinfo.ZoneInfo | None = None
    if not tz_str:
        logger.error(
            "CLINIC_TIMEZONE is not set. "
            "Set it to a valid IANA timezone identifier, e.g. Asia/Kolkata or America/New_York. "
            "Offset strings like UTC+5:30 are not valid."
        )
        errors.append("CLINIC_TIMEZONE")
    else:
        try:
            tz = zoneinfo.ZoneInfo(tz_str)
        except zoneinfo.ZoneInfoNotFoundError:
            logger.error(
                "CLINIC_TIMEZONE=%r is not a valid IANA timezone identifier. "
                "Valid examples: Asia/Kolkata, America/New_York, Europe/London. "
                "Offset strings like UTC+5:30 are not accepted.",
                tz_str,
            )
            errors.append("CLINIC_TIMEZONE")
        except Exception as exc:
            logger.error("Failed to load CLINIC_TIMEZONE=%r: %s", tz_str, exc)
            errors.append("CLINIC_TIMEZONE")

    # --- Exit early if any required variable is missing/invalid ---
    if errors:
        logger.error(
            "Application startup aborted due to missing or invalid environment "
            "variable(s): %s. Fix the above error(s) and restart.",
            ", ".join(errors),
        )
        sys.exit(1)

    # --- Optional variables with defaults ---
    model = os.environ.get("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o"
    database_url = os.environ.get("DATABASE_URL", "./clinic.db").strip() or "./clinic.db"

    return Settings(
        api_key=api_key,
        model=model,
        database_url=database_url,
        clinic_timezone=tz_str,
        tz=tz,  # type: ignore[arg-type]  # guaranteed non-None if no errors
    )


settings = _load_settings()