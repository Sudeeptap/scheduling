"""
backend/database.py

SQLite connection management and schema initialisation for the Doctor's Assistant MVP.

- All timestamp columns store UTC strings in ISO 8601 Z-suffix format: 2026-10-15T04:30:00Z
- WAL mode and foreign-key enforcement are enabled on every connection
- Callers manage transactions explicitly (isolation_level = None)
"""

import os
import sqlite3


def get_db() -> sqlite3.Connection:
    """Return a configured SQLite connection.

    Reads DATABASE_URL from the environment (defaults to ./clinic.db).
    Enables WAL journal mode and foreign-key enforcement.
    Sets isolation_level=None so callers control transactions explicitly.
    """
    db_path = os.environ.get("DATABASE_URL", "./clinic.db")
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS SPECIALTY (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS DOCTOR (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name            TEXT NOT NULL,
    last_name             TEXT NOT NULL,
    slot_duration_minutes INTEGER NOT NULL DEFAULT 30,
    is_active             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS DOCTOR_SPECIALTY (
    doctor_id    INTEGER NOT NULL REFERENCES DOCTOR(id),
    specialty_id INTEGER NOT NULL REFERENCES SPECIALTY(id),
    PRIMARY KEY (doctor_id, specialty_id)
);

CREATE TABLE IF NOT EXISTS DOCTOR_AVAILABILITY (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id   INTEGER NOT NULL REFERENCES DOCTOR(id),
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS PATIENT (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    phone         TEXT NOT NULL,
    email         TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_identity
    ON PATIENT (first_name, last_name, date_of_birth, phone);

CREATE TABLE IF NOT EXISTS APPOINTMENT (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_reference    TEXT NOT NULL UNIQUE,
    doctor_id            INTEGER NOT NULL REFERENCES DOCTOR(id),
    patient_id           INTEGER NOT NULL REFERENCES PATIENT(id),
    appointment_datetime TEXT NOT NULL,
    end_datetime         TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'confirmed'
                             CHECK (status IN ('confirmed')),
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_appointment_slot
    ON APPOINTMENT (doctor_id, appointment_datetime, status);

CREATE TABLE IF NOT EXISTS CHAT_SESSION (
    session_id      TEXT PRIMARY KEY,
    thread_history  TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed')),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_active_at  TEXT
);
"""


def init_db(db: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not exist.

    Safe to call on an existing database - uses CREATE TABLE/INDEX IF NOT EXISTS.
    executescript() issues an implicit COMMIT before running, so no manual
    transaction wrapping is needed here.
    """
    db.executescript(_SCHEMA_SQL)