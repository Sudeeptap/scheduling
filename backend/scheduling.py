"""
backend/scheduling.py -- Scheduling_Service

Tasks:
  6.1  search_doctor
  6.2  suggest_specialty
  6.3  get_availability
"""

from __future__ import annotations

import sqlite3
import zoneinfo
import re
from datetime import date, timedelta
from typing import Any

from backend.slots import (
    UTC,
    from_utc_z,
    localize,
    slots_for_day,
    to_utc_z,
)


# ---------------------------------------------------------------------------
# Task 6.1 -- search_doctor
# ---------------------------------------------------------------------------

def search_doctor(doctor_name: str, db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Case-insensitive partial match on first_name || ' ' || last_name.

    Returns up to 20 active doctors with id, full_name, specialties, slot_duration_minutes.
    Returns [] when nothing matches.
    """
    cleaned_name = re.sub(
    r"^\s*(?:dr\.?|doctor)\s+",
    "",
    doctor_name.strip(),
    flags=re.IGNORECASE,
    )

    pattern = f"%{cleaned_name}%"
    rows = db.execute(
        """
        SELECT d.id,
               d.first_name || ' ' || d.last_name AS full_name,
               d.slot_duration_minutes
        FROM DOCTOR d
        WHERE d.is_active = 1
          AND (d.first_name || ' ' || d.last_name) LIKE ? COLLATE NOCASE
        ORDER BY d.last_name, d.first_name
        LIMIT 20
        """,
        (pattern,),
    ).fetchall()

    if not rows:
        return []

    results: list[dict[str, Any]] = []
    for row in rows:
        doctor_id = row["id"]
        spec_rows = db.execute(
            """
            SELECT s.name
            FROM SPECIALTY s
            JOIN DOCTOR_SPECIALTY ds ON ds.specialty_id = s.id
            WHERE ds.doctor_id = ? AND s.is_active = 1
            ORDER BY s.name
            """,
            (doctor_id,),
        ).fetchall()
        results.append(
            {
                "id": doctor_id,
                "full_name": row["full_name"],
                "specialties": [r["name"] for r in spec_rows],
                "slot_duration_minutes": row["slot_duration_minutes"],
            }
        )
    return results

    
def search_doctors_by_specialty(
    specialty_name: str,
    db: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Find active doctors matching a specialty name."""
    name = specialty_name.strip()

    if not name:
        return []

    rows = db.execute(
        """
        SELECT
            d.id,
            d.first_name,
            d.last_name,
            s.name AS specialty,
            d.slot_duration_minutes
        FROM DOCTOR d
        JOIN DOCTOR_SPECIALTY ds ON ds.doctor_id = d.id
        JOIN SPECIALTY s ON s.id = ds.specialty_id
        WHERE d.is_active = 1
          AND LOWER(s.name) = LOWER(?)
        ORDER BY d.first_name, d.last_name
        """,
        (name,),
    ).fetchall()

    return [
        {
            "id": row["id"],
            "full_name": f"{row['first_name']} {row['last_name']}",
            "specialties": [row["specialty"]],
            "slot_duration_minutes": row["slot_duration_minutes"],
        }
        for row in rows
    ]



# ---------------------------------------------------------------------------
# Task 6.2 -- suggest_specialty
# ---------------------------------------------------------------------------

def suggest_specialty(symptom_description: str, db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all active specialties from the database.

    The OpenAI model selects the best match from the returned list based on
    the patient's symptoms. This function does not perform NLP or diagnosis --
    it only supplies the list so the model can reason over it.

    Returns a list of dicts with keys: id, name, description.
    Returns [] if no active specialties exist.
    """
    rows = db.execute(
        """
        SELECT id, name, description
        FROM SPECIALTY
        WHERE is_active = 1
        ORDER BY name
        """,
    ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Task 6.3 -- get_availability
# ---------------------------------------------------------------------------

def get_availability(
    doctor_id: int,
    date: str,
    find_next_available: bool,
    db: sqlite3.Connection,
    clinic_tz: str,
) -> dict[str, Any]:
    """Compute available appointment slots for a doctor on a given date.

    Args:
        doctor_id:            Doctor to check.
        date:                 Clinic-local date string "YYYY-MM-DD".
        find_next_available:  If True, scan forward up to 30 days and return
                              only the earliest single free slot.
        db:                   Open SQLite connection.
        clinic_tz:            IANA timezone string e.g. "Asia/Kolkata".

    Returns one of:
        {"available_slots": ["2026-10-15T04:30:00Z", ...]}   -- success
        {"available_slots": []}                               -- nothing free
        {"error": "doctor_not_found"}
        {"error": "invalid_date"}
    """
    # -- Validate doctor_id --------------------------------------------------
    doctor_row = db.execute(
        "SELECT id, slot_duration_minutes, is_active FROM DOCTOR WHERE id = ?",
        (doctor_id,),
    ).fetchone()
    if doctor_row is None:
        return {"error": "doctor_not_found"}

    # -- Validate date string -------------------------------------------------
    try:
        from datetime import date as _date
        requested_date = _date.fromisoformat(date)
    except ValueError:
        return {"error": "invalid_date"}

    slot_minutes = doctor_row["slot_duration_minutes"]
    tz = zoneinfo.ZoneInfo(clinic_tz)
    today_local = _today_in_tz(clinic_tz)

    if not find_next_available:
        slots = _free_slots_for_date(
            doctor_id, requested_date, slot_minutes, db, tz, today_local
        )
        return {"available_slots": slots}

    # find_next_available: scan forward up to 30 days
    scan_date = requested_date
    for _ in range(30):
        slots = _free_slots_for_date(
            doctor_id, scan_date, slot_minutes, db, tz, today_local
        )
        if slots:
            return {"available_slots": [slots[0]]}   # only the earliest
        scan_date += timedelta(days=1)

    return {"available_slots": []}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _today_in_tz(clinic_tz: str):
    from datetime import datetime as _dt
    import zoneinfo as _zi
    return _dt.now(_zi.ZoneInfo(clinic_tz)).date()


def _free_slots_for_date(
    doctor_id: int,
    target_date,
    slot_minutes: int,
    db: sqlite3.Connection,
    tz: zoneinfo.ZoneInfo,
    today_local,
) -> list[str]:
    """Return UTC Z-suffix strings for every free slot on target_date."""
    # Past dates always empty
    if target_date < today_local:
        return []

    day_of_week = target_date.weekday()   # 0=Mon, 6=Sun

    avail_rows = db.execute(
        """
        SELECT start_time, end_time
        FROM DOCTOR_AVAILABILITY
        WHERE doctor_id = ? AND day_of_week = ? AND is_active = 1
        """,
        (doctor_id, day_of_week),
    ).fetchall()

    if not avail_rows:
        return []

    # Build all candidate slots (naive local datetimes) then attach tz
    candidate_slots: list = []
    for avail in avail_rows:
        naive_slots = slots_for_day(
            target_date, avail["start_time"], avail["end_time"], slot_minutes
        )
        for ns in naive_slots:
            candidate_slots.append(localize(ns, tz.key))

    if not candidate_slots:
        return []

    # Fetch confirmed appointments that overlap the day window
    day_start = localize(
        __import__("datetime").datetime(
            target_date.year, target_date.month, target_date.day, 0, 0
        ),
        tz.key,
    ).astimezone(UTC)
    day_end = localize(
        __import__("datetime").datetime(
            target_date.year, target_date.month, target_date.day, 23, 59, 59
        ),
        tz.key,
    ).astimezone(UTC)

    booked_rows = db.execute(
        """
        SELECT appointment_datetime, end_datetime
        FROM APPOINTMENT
        WHERE doctor_id = ?
          AND status = 'confirmed'
          AND appointment_datetime < ?
          AND end_datetime > ?
        """,
        (doctor_id, to_utc_z(day_end), to_utc_z(day_start)),
    ).fetchall()

    booked: list[tuple] = []
    for br in booked_rows:
        booked.append((from_utc_z(br["appointment_datetime"]), from_utc_z(br["end_datetime"])))

    from backend.slots import overlaps
    from datetime import timedelta as _td

    free: list[str] = []
    now_utc = __import__("datetime").datetime.now(UTC)

    for slot_local in candidate_slots:
        slot_utc = slot_local.astimezone(UTC)
        # Skip slots already in the past
        if slot_utc <= now_utc:
            continue
        slot_end_utc = slot_utc + _td(minutes=slot_minutes)
        # Skip if overlaps any confirmed booking
        if any(overlaps(slot_utc, slot_end_utc, bs, be) for bs, be in booked):
            continue
        free.append(to_utc_z(slot_utc))

    return free