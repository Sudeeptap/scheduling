"""
backend/seed.py

Idempotent seed data for the Doctor's Assistant MVP.

Run with:
    python -m backend.seed

Uses INSERT OR IGNORE where a UNIQUE constraint exists (SPECIALTY.name).
For DOCTOR, DOCTOR_SPECIALTY, and DOCTOR_AVAILABILITY, existence is checked
with SELECT before inserting so re-runs are safe.
"""

import sys
import os

# Allow running as `python -m backend.seed` from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import get_db, init_db


# ---------------------------------------------------------------------------
# Seed definitions
# ---------------------------------------------------------------------------

SPECIALTIES = [
    {"name": "General Practice",  "description": "General health consultations and preventive care"},
    {"name": "Dermatology",       "description": "Skin, hair, and nail conditions"},
    {"name": "Orthopedics",       "description": "Bone, joint, and musculoskeletal conditions"},
]

# (first_name, last_name, slot_duration_minutes, specialty_name)
DOCTORS = [
    ("Priya",  "Sharma", 30, "General Practice"),
    ("Rajesh", "Kumar",  30, "Dermatology"),
    ("Anita",  "Patel",  45, "Orthopedics"),
    ("Suresh", "Nair",   30, "Orthopedics"),
]

# (doctor_first, doctor_last, day_of_week, start_time, end_time)
# day_of_week: 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
AVAILABILITY = [
    # Dr. Priya Sharma — 09:00–17:00, Mon–Fri
    ("Priya",  "Sharma", 0, "09:00", "17:00"),
    ("Priya",  "Sharma", 1, "09:00", "17:00"),
    ("Priya",  "Sharma", 2, "09:00", "17:00"),
    ("Priya",  "Sharma", 3, "09:00", "17:00"),
    ("Priya",  "Sharma", 4, "09:00", "17:00"),
    # Dr. Rajesh Kumar — 10:00–16:00, Mon–Fri
    ("Rajesh", "Kumar",  0, "10:00", "16:00"),
    ("Rajesh", "Kumar",  1, "10:00", "16:00"),
    ("Rajesh", "Kumar",  2, "10:00", "16:00"),
    ("Rajesh", "Kumar",  3, "10:00", "16:00"),
    ("Rajesh", "Kumar",  4, "10:00", "16:00"),
    # Dr. Anita Patel — 09:00–13:00, Mon–Fri
    ("Anita",  "Patel",  0, "09:00", "13:00"),
    ("Anita",  "Patel",  1, "09:00", "13:00"),
    ("Anita",  "Patel",  2, "09:00", "13:00"),
    ("Anita",  "Patel",  3, "09:00", "13:00"),
    ("Anita",  "Patel",  4, "09:00", "13:00"),
    # Dr. Suresh Nair — 14:00–18:00, Mon–Fri
    ("Suresh", "Nair",   0, "14:00", "18:00"),
    ("Suresh", "Nair",   1, "14:00", "18:00"),
    ("Suresh", "Nair",   2, "14:00", "18:00"),
    ("Suresh", "Nair",   3, "14:00", "18:00"),
    ("Suresh", "Nair",   4, "14:00", "18:00"),
]


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed(db) -> None:
    db.execute("BEGIN")
    try:
        _seed_specialties(db)
        _seed_doctors(db)
        _seed_availability(db)
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def _seed_specialties(db) -> None:
    for s in SPECIALTIES:
        db.execute(
            "INSERT OR IGNORE INTO SPECIALTY (name, description) VALUES (?, ?)",
            (s["name"], s["description"]),
        )


def _seed_doctors(db) -> None:
    for first, last, slot_mins, specialty_name in DOCTORS:
        # Upsert doctor by full name
        existing = db.execute(
            "SELECT id FROM DOCTOR WHERE first_name = ? AND last_name = ?",
            (first, last),
        ).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO DOCTOR (first_name, last_name, slot_duration_minutes) VALUES (?, ?, ?)",
                (first, last, slot_mins),
            )
            doctor_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            doctor_id = existing[0]

        # Link doctor to specialty
        specialty = db.execute(
            "SELECT id FROM SPECIALTY WHERE name = ?", (specialty_name,)
        ).fetchone()
        if specialty is None:
            raise ValueError(f"Specialty not found: {specialty_name}")
        specialty_id = specialty[0]

        db.execute(
            "INSERT OR IGNORE INTO DOCTOR_SPECIALTY (doctor_id, specialty_id) VALUES (?, ?)",
            (doctor_id, specialty_id),
        )


def _seed_availability(db) -> None:
    for first, last, dow, start, end in AVAILABILITY:
        doctor = db.execute(
            "SELECT id FROM DOCTOR WHERE first_name = ? AND last_name = ?",
            (first, last),
        ).fetchone()
        if doctor is None:
            raise ValueError(f"Doctor not found for availability: {first} {last}")
        doctor_id = doctor[0]

        exists = db.execute(
            "SELECT 1 FROM DOCTOR_AVAILABILITY "
            "WHERE doctor_id = ? AND day_of_week = ? AND start_time = ? AND end_time = ?",
            (doctor_id, dow, start, end),
        ).fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO DOCTOR_AVAILABILITY "
                "(doctor_id, day_of_week, start_time, end_time) VALUES (?, ?, ?, ?)",
                (doctor_id, dow, start, end),
            )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    db = get_db()
    init_db(db)
    seed(db)

    # Summary
    specialties = db.execute("SELECT COUNT(*) FROM SPECIALTY WHERE is_active = 1").fetchone()[0]
    doctors = db.execute("SELECT COUNT(*) FROM DOCTOR WHERE is_active = 1").fetchone()[0]
    availability = db.execute("SELECT COUNT(*) FROM DOCTOR_AVAILABILITY WHERE is_active = 1").fetchone()[0]

    print(f"Seed complete:")
    print(f"  {specialties} active specialties")
    print(f"  {doctors} active doctors")
    print(f"  {availability} availability rows")


if __name__ == "__main__":
    main()