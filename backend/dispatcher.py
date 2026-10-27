"""
backend/dispatcher.py -- Tool_Dispatcher  (Task 8)

Validates tool call arguments and routes each tool call to the correct
internal service.  Returns JSON-serialisable dicts in all cases.

Supported tools (cancel_appointment is deferred and NOT handled here):
  search_doctor
  search_doctors_by_specialty
  suggest_specialty
  book_appointment
  get_availability
"""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.scheduling import (
    get_availability,
    search_doctor,
    search_doctors_by_specialty,
    suggest_specialty,
    get_availability,
)
from backend.appointment import book_appointment


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def dispatch(
    tool_name: str,
    tool_args: dict[str, Any],
    db: sqlite3.Connection,
    clinic_tz: str,
) -> dict[str, Any]:
    """Validate arguments then route to the correct service function.

    Args:
        tool_name:  Name of the tool as returned by the OpenAI model.
        tool_args:  Arguments dict from the model's tool call.
        db:         Open SQLite connection (row_factory = sqlite3.Row).
        clinic_tz:  IANA timezone string e.g. "Asia/Kolkata".

    Returns:
        A JSON-serialisable dict.  On validation failure:
            {"error": "invalid_param", "detail": "<human-readable reason>"}
        On unknown tool:
            {"error": "unknown_tool", "tool_name": "<name>"}
        Otherwise the result dict from the service function.

    Internal exceptions are not caught here -- the Conversation_Service
    layer is responsible for error boundaries around the full turn.
    """
    handlers = {
        "search_doctor":    _search_doctor,
        "suggest_specialty": _suggest_specialty,
        "get_availability": _get_availability,
        "book_appointment": _book_appointment,
        "search_doctors_by_specialty": _search_doctors_by_specialty,
    }

    handler = handlers.get(tool_name)
    if handler is None:
        return {"error": "unknown_tool", "tool_name": tool_name}

    return handler(tool_args, db, clinic_tz)


# ---------------------------------------------------------------------------
# Per-tool handlers (validate then call service)
# ---------------------------------------------------------------------------

def _search_doctor(
    args: dict[str, Any], db: sqlite3.Connection, clinic_tz: str
) -> dict[str, Any]:
    doctor_name = (args.get("doctor_name") or "").strip()
    if not doctor_name:
        return {"error": "invalid_param", "detail": "doctor_name must not be empty"}
    if len(doctor_name) > 100:
        return {"error": "invalid_param", "detail": "doctor_name must be at most 100 characters"}

    results = search_doctor(doctor_name, db)
    return {"doctors": results}

def _search_doctors_by_specialty(args, db, clinic_tz):
    specialty_name = (args.get("specialty_name") or "").strip()

    if not specialty_name:
        return {
            "error": "invalid_param",
            "detail": "specialty_name must not be empty",
        }

    doctors = search_doctors_by_specialty(specialty_name, db)
    return {"doctors": doctors}    


def _suggest_specialty(
    args: dict[str, Any], db: sqlite3.Connection, clinic_tz: str
) -> dict[str, Any]:
    symptom = (args.get("symptom_description") or "").strip()
    if not symptom:
        return {
            "error": "invalid_param",
            "detail": "symptom_description must not be empty",
        }

    results = suggest_specialty(symptom, db)
    return {"specialties": results}


def _get_availability(
    args: dict[str, Any], db: sqlite3.Connection, clinic_tz: str
) -> dict[str, Any]:
    # doctor_id: must be present and coercible to int
    raw_id = args.get("doctor_id")
    if raw_id is None:
        return {"error": "invalid_param", "detail": "doctor_id is required"}
    try:
        doctor_id = int(raw_id)
    except (TypeError, ValueError):
        return {"error": "invalid_param", "detail": "doctor_id must be an integer"}

    # date: must be a non-empty string
    date_str = (args.get("date") or "").strip()
    if not date_str:
        return {"error": "invalid_param", "detail": "date is required (YYYY-MM-DD)"}

    find_next = bool(args.get("find_next_available", False))

    return get_availability(doctor_id, date_str, find_next, db, clinic_tz)


def _book_appointment(
    args: dict[str, Any], db: sqlite3.Connection, clinic_tz: str
) -> dict[str, Any]:
    # doctor_id
    raw_id = args.get("doctor_id")
    if raw_id is None:
        return {"error": "invalid_param", "detail": "doctor_id is required"}
    try:
        doctor_id = int(raw_id)
    except (TypeError, ValueError):
        return {"error": "invalid_param", "detail": "doctor_id must be an integer"}

    # appointment_datetime
    appt_dt = (args.get("appointment_datetime") or "").strip()
    if not appt_dt:
        return {
            "error": "invalid_param",
            "detail": "appointment_datetime is required (UTC ISO 8601 with Z suffix)",
        }

    # patient sub-object
    patient = args.get("patient")
    if not isinstance(patient, dict):
        return {"error": "invalid_param", "detail": "patient must be an object"}

    required_patient_fields = ("first_name", "last_name", "date_of_birth", "phone")
    missing = [f for f in required_patient_fields if not (patient.get(f) or "").strip()]
    if missing:
        return {
            "error": "invalid_param",
            "detail": f"patient is missing required fields: {', '.join(missing)}",
        }

    return book_appointment(doctor_id, appt_dt, patient, db, clinic_tz)