"""
backend/appointment.py -- Appointment_Service  (Task 7)

Implements book_appointment() with:
  - BEGIN IMMEDIATE transaction
  - Patient upsert by unique identity
  - Guard checks: doctor active, slot in future, slot in schedule, no overlap
  - booking_reference generation (SC-YYYY-NNNNN, clinic-local year)
  - UTC Z-suffix timestamp storage
"""

from __future__ import annotations

import sqlite3
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.slots import (
    UTC,
    from_utc_z,
    is_slot_boundary,
    localize,
    overlaps,
    to_utc_z,
)


def book_appointment(
    doctor_id: int,
    appointment_datetime: str,       # UTC Z-suffix ISO 8601 e.g. "2027-01-04T03:30:00Z"
    patient_details: dict[str, Any], # keys: first_name, last_name, date_of_birth, phone
    db: sqlite3.Connection,
    clinic_tz: str,
) -> dict[str, Any]:
    """Book a confirmed appointment inside a single IMMEDIATE transaction.

    Returns:
        {"booking_reference": "SC-YYYY-NNNNN"}   on success
        {"error": "SLOT_TAKEN"}                   overlap with existing booking
        {"error": "DOCTOR_INACTIVE"}              doctor is inactive
        {"error": "SLOT_IN_PAST"}                 requested slot already passed
        {"error": "SLOT_NOT_IN_SCHEDULE"}         outside working hours / bad boundary
        {"error": "invalid_datetime"}             unparseable appointment_datetime
        {"error": "invalid_patient", "detail": …} missing/invalid patient fields
    """
    # -- Parse & validate appointment_datetime --------------------------------
    try:
        appt_utc: datetime = from_utc_z(appointment_datetime)
    except (ValueError, TypeError):
        return {"error": "invalid_datetime"}

    slot_end_utc = None   # computed once we know slot_minutes

    # -- Validate patient_details shape (not full Pydantic -- just presence) --
    required = ("first_name", "last_name", "date_of_birth", "phone")
    missing = [f for f in required if not (patient_details.get(f) or "").strip()]
    if missing:
        return {"error": "invalid_patient", "detail": f"Missing fields: {', '.join(missing)}"}

    tz = zoneinfo.ZoneInfo(clinic_tz)

    # ── BEGIN IMMEDIATE ──────────────────────────────────────────────────────
    db.execute("BEGIN IMMEDIATE")
    try:
        # 1. Fetch doctor -------------------------------------------------------
        doctor = db.execute(
            "SELECT id, slot_duration_minutes, is_active FROM DOCTOR WHERE id = ?",
            (doctor_id,),
        ).fetchone()
        if doctor is None or doctor["is_active"] != 1:
            db.execute("ROLLBACK")
            return {"error": "DOCTOR_INACTIVE"}

        slot_minutes: int = doctor["slot_duration_minutes"]
        slot_end_utc = appt_utc + timedelta(minutes=slot_minutes)

        # 2. Slot must be in the future ----------------------------------------
        now_utc = datetime.now(UTC)
        if appt_utc <= now_utc:
            db.execute("ROLLBACK")
            return {"error": "SLOT_IN_PAST"}

        # 3. Slot must align with the doctor's schedule -----------------------
        appt_local = appt_utc.astimezone(tz)
        day_of_week = appt_local.weekday()   # 0=Mon, 6=Sun

        avail_rows = db.execute(
            """
            SELECT start_time, end_time
            FROM DOCTOR_AVAILABILITY
            WHERE doctor_id = ? AND day_of_week = ? AND is_active = 1
            """,
            (doctor_id, day_of_week),
        ).fetchall()

        in_schedule = False
        for avail in avail_rows:
            sh, sm = map(int, avail["start_time"].split(":"))
            eh, em = map(int, avail["end_time"].split(":"))
            avail_start_min = sh * 60 + sm
            avail_end_min   = eh * 60 + em
            slot_start_min  = appt_local.hour * 60 + appt_local.minute
            slot_end_min    = slot_start_min + slot_minutes

            if (
                slot_start_min >= avail_start_min
                and slot_end_min <= avail_end_min
                and is_slot_boundary(appt_local, avail["start_time"], slot_minutes)
            ):
                in_schedule = True
                break

        if not in_schedule:
            db.execute("ROLLBACK")
            return {"error": "SLOT_NOT_IN_SCHEDULE"}

        # 4. Overlap check against confirmed appointments ---------------------
        # Fetch any confirmed appointment whose interval overlaps [appt_utc, slot_end_utc)
        conflict_rows = db.execute(
            """
            SELECT appointment_datetime, end_datetime
            FROM APPOINTMENT
            WHERE doctor_id = ? AND status = 'confirmed'
              AND appointment_datetime < ?
              AND end_datetime > ?
            """,
            (doctor_id, to_utc_z(slot_end_utc), to_utc_z(appt_utc)),
        ).fetchall()

        for cr in conflict_rows:
            bs = from_utc_z(cr["appointment_datetime"])
            be = from_utc_z(cr["end_datetime"])
            if overlaps(appt_utc, slot_end_utc, bs, be):
                db.execute("ROLLBACK")
                return {"error": "SLOT_TAKEN"}

        # 5. Patient upsert ---------------------------------------------------
        fn = patient_details["first_name"].strip()
        ln = patient_details["last_name"].strip()
        dob = patient_details["date_of_birth"].strip()
        phone = patient_details["phone"].strip()

        existing_patient = db.execute(
            "SELECT id FROM PATIENT WHERE first_name=? AND last_name=? AND date_of_birth=? AND phone=?",
            (fn, ln, dob, phone),
        ).fetchone()

        if existing_patient is not None:
            patient_id = existing_patient["id"]
        else:
            db.execute(
                "INSERT INTO PATIENT (first_name, last_name, date_of_birth, phone) VALUES (?,?,?,?)",
                (fn, ln, dob, phone),
            )
            patient_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 6. Generate booking_reference using clinic-local year ---------------
        clinic_year = appt_utc.astimezone(tz).year
        seq_row = db.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(booking_reference, 9) AS INTEGER)), 0) + 1 "
            "FROM APPOINTMENT WHERE booking_reference LIKE ?",
            (f"SC-{clinic_year}-%",),
        ).fetchone()
        sequence = seq_row[0]
        booking_reference = f"SC-{clinic_year}-{sequence:05d}"

        # 7. Insert appointment -----------------------------------------------
        db.execute(
            """
            INSERT INTO APPOINTMENT
                (booking_reference, doctor_id, patient_id,
                 appointment_datetime, end_datetime, status)
            VALUES (?, ?, ?, ?, ?, 'confirmed')
            """,
            (
                booking_reference,
                doctor_id,
                patient_id,
                to_utc_z(appt_utc),
                to_utc_z(slot_end_utc),
            ),
        )

        db.execute("COMMIT")
        return {"booking_reference": booking_reference}

    except Exception:
        # Ensure rollback on any unexpected error; re-raise for caller to log
        try:
            db.execute("ROLLBACK")
        except Exception:
            pass
        raise