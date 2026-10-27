"""
backend/slots.py — Shared slot-boundary arithmetic.

Used by both scheduling.py (get_availability) and appointment.py (book_appointment)
so that slot calculation, overlap detection, and timezone conversion stay consistent.

Slot model
----------
A doctor works from start_time to end_time on a given day_of_week.
Slots are non-overlapping windows of slot_duration_minutes, starting exactly
at start_time and repeating until there is no room for another full slot before
end_time.

All public functions accept and return timezone-aware datetime objects or
UTC ISO 8601 strings with a Z suffix.  Naive datetimes are never used.
"""

from __future__ import annotations

import zoneinfo
from datetime import date, datetime, timedelta, timezone


UTC = timezone.utc


def _tz(clinic_tz: str) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(clinic_tz)


def slots_for_day(
    local_date: date,
    start_hhmm: str,
    end_hhmm: str,
    slot_minutes: int,
) -> list[datetime]:
    """Return all slot start times for one availability window on local_date.

    Args:
        local_date:   clinic-local calendar date
        start_hhmm:   window start as "HH:MM"
        end_hhmm:     window end   as "HH:MM"
        slot_minutes: slot duration in minutes

    Returns:
        List of timezone-NAIVE datetime objects (local date + time).
        Callers must attach the clinic timezone and convert to UTC.
    """
    sh, sm = map(int, start_hhmm.split(":"))
    eh, em = map(int, end_hhmm.split(":"))
    start_min = sh * 60 + sm
    end_min   = eh * 60 + em
    slots = []
    t = start_min
    while t + slot_minutes <= end_min:
        slots.append(
            datetime(
                local_date.year, local_date.month, local_date.day,
                t // 60, t % 60,
            )
        )
        t += slot_minutes
    return slots


def localize(naive_dt: datetime, clinic_tz: str) -> datetime:
    """Attach clinic timezone to a naive datetime (no conversion)."""
    return naive_dt.replace(tzinfo=_tz(clinic_tz))


def to_utc_z(dt: datetime) -> str:
    """Convert a timezone-aware datetime to a UTC Z-suffix ISO 8601 string."""
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def from_utc_z(s: str) -> datetime:
    """Parse a UTC Z-suffix ISO 8601 string to a timezone-aware datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def is_slot_boundary(slot_dt_local: datetime, avail_start_hhmm: str, slot_minutes: int) -> bool:
    """Return True if slot_dt_local aligns exactly to a slot boundary."""
    sh, sm = map(int, avail_start_hhmm.split(":"))
    avail_start_min = sh * 60 + sm
    slot_min = slot_dt_local.hour * 60 + slot_dt_local.minute
    return (slot_min - avail_start_min) % slot_minutes == 0


def overlaps(
    slot_start: datetime,
    slot_end: datetime,
    booked_start: datetime,
    booked_end: datetime,
) -> bool:
    """Return True if two half-open intervals [s,e) overlap."""
    return slot_start < booked_end and slot_end > booked_start