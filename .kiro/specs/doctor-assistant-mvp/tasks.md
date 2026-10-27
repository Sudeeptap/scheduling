# Implementation Plan: Doctor's Assistant MVP

## Overview

Implement the Doctor's Assistant chatbot for Super Clinic end-to-end: React + TypeScript + Vite frontend, Python FastAPI backend, OpenAI Responses API with function calling, and an SQLite database. Tasks follow the ordering constraints: config → schema → models/tools → services → dispatcher → conversation → endpoint → frontend → manual verification.

## Tasks

- [ ] 1. Project scaffolding and environment setup
  - Create `backend/` directory with a `requirements.txt` pinning: `fastapi`, `uvicorn[standard]`, `openai`, `pydantic`, `tzdata` (cross-platform IANA timezone database; `zoneinfo` is built-in for Python 3.9+)
  - Do NOT add `pytest` or `hypothesis` — automated tests are deferred per the steering file
  - Scaffold the Vite + React + TypeScript frontend: `npm create vite@latest frontend -- --template react-ts`
  - Create `.env.example` at the repo root with the following contents:
    ```
    OPENAI_API_KEY=your-openai-api-key-here
    OPENAI_MODEL=gpt-4o
    DATABASE_URL=./clinic.db
    CLINIC_TIMEZONE=Asia/Kolkata
    ```
  - `CLINIC_TIMEZONE` is required and must be a valid IANA timezone identifier (e.g. `Asia/Kolkata`, `America/New_York`, `Europe/London`). The application will refuse to start if this is missing or invalid. Offset strings like `UTC+5:30` are not valid IANA identifiers.
  - _Requirements: 11.1, 11.2, 11.4_

- [ ] 2. Database schema and seed data
  - [ ] 2.1 Implement `backend/database.py`
    - Define `get_db()` that returns a `sqlite3.Connection` reading `DATABASE_URL` from env (defaulting to `./clinic.db`)
    - Implement `init_db()` that runs all `CREATE TABLE IF NOT EXISTS` and `CREATE UNIQUE INDEX IF NOT EXISTS` DDL from the design (SPECIALTY, DOCTOR, DOCTOR_SPECIALTY, DOCTOR_AVAILABILITY, PATIENT, APPOINTMENT, CHAT_SESSION)
    - Enable WAL mode and foreign-key enforcement on every new connection
    - Store all appointment and session timestamp columns as `TEXT` in timezone-aware ISO 8601 UTC format with a `Z` suffix (e.g. `2026-10-15T04:30:00Z`). Never store naive datetime strings in these columns.
    - _Requirements: 8.1, 8.2, 8.3, 11.2_

  - [ ] 2.2 Create `backend/seed.py`
    - Insert at least 3 specialties (e.g. General Practice, Dermatology, Orthopedics) with `is_active=1`
    - Insert at least 4 doctors spread across those specialties with weekly `DOCTOR_AVAILABILITY` rows covering Mon–Fri, with `start_time` and `end_time` stored as `HH:MM` text
    - Make the script idempotent using `INSERT OR IGNORE`
    - _Requirements: 8.1, 8.2, 8.3_

- [ ] 3. Configuration module (`backend/config.py`)
  - Read `OPENAI_API_KEY`, `OPENAI_MODEL`, `DATABASE_URL`, and `CLINIC_TIMEZONE` from environment at import time
  - Validate `OPENAI_API_KEY` is non-empty
  - Validate `CLINIC_TIMEZONE` is a valid IANA identifier using `zoneinfo.ZoneInfo(CLINIC_TIMEZONE)` — catch `zoneinfo.ZoneInfoNotFoundError` and treat it as invalid
  - If either `OPENAI_API_KEY` or `CLINIC_TIMEZONE` is missing or invalid, log a descriptive error identifying the specific variable and call `sys.exit(1)` before FastAPI binds to any port
  - `DATABASE_URL` defaults to `./clinic.db` if not set
  - `OPENAI_MODEL` defaults to `gpt-4o` if not set (configurable via `.env` without code changes)
  - Export a `settings` object with `api_key`, `model`, `database_url`, and `clinic_timezone` attributes
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 4. Pydantic models (`backend/models.py`)
  - Implement `PatientDetails`, `ChatRequest`, and `ChatResponse`
    - `PatientDetails`: `first_name` and `last_name` are non-empty strings of at most 50 characters each; `date_of_birth` is a valid calendar date in YYYY-MM-DD format between 1900-01-01 and today (exclusive); `phone` contains 10–15 digits with an optional country code prefix and optional separators (spaces, hyphens, parentheses)
    - `ChatRequest`: `session_id` is a non-empty string; `message` is 1–2000 characters
    - `ChatResponse`: `session_id` string, `reply` string
  - Add validator logic for all rules; raise `ValueError` naming each failing field
  - _Requirements: 6.2, 6.3, 11.6_

- [ ] 5. OpenAI tool schemas (`backend/tools.py`)
  - Define `TOOLS` as a list containing exactly four tool schemas: `search_doctor`, `suggest_specialty`, `get_availability`, `book_appointment`
  - Match the schemas from the design exactly, including required fields, types, and descriptions
  - Do NOT include `cancel_appointment` — it is deferred for MVP
  - _Requirements: 2.1, 3.1, 4.1, 7.1_

- [ ] 6. Scheduling_Service (`backend/scheduling.py`)
  - [ ] 6.1 Implement `search_doctor(doctor_name: str, db) -> list[dict]`
    - Case-insensitive `LIKE '%name%'` on `first_name || ' ' || last_name` where `is_active=1`
    - Return up to 20 results, each with `id`, `full_name`, `specialties`, and `slot_duration_minutes`
    - Return an empty list when no match is found
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 6.2 Implement `suggest_specialty(symptom_description: str, db) -> list[dict]`
    - Return all rows from `SPECIALTY` where `is_active=1`
    - Return an empty list if none exist
    - _Requirements: 3.1, 3.5_

  - [ ] 6.3 Implement `get_availability(doctor_id: int, date: str, find_next_available: bool, db, clinic_tz: str) -> dict`
    - Validate `doctor_id` exists — return `{"error": "doctor_not_found"}` if not
    - Validate `date` is a valid ISO 8601 YYYY-MM-DD string — return `{"error": "invalid_date"}` if not
    - Treat a date as "in the past" relative to the current date in `clinic_tz` using `zoneinfo.ZoneInfo(clinic_tz)` to get today's local date
    - Load active `DOCTOR_AVAILABILITY` rows for the doctor matching `day_of_week`; subtract confirmed appointments to compute free slots
    - Return free slots as timezone-aware UTC ISO 8601 strings with a `Z` suffix: `{"available_slots": ["2026-10-15T04:30:00Z", ...]}`. Use timezone-aware datetime arithmetic throughout; never compare or subtract naive and aware datetimes.
    - Return `{"available_slots": []}` when the date is in the past, not a working day, or all slots are booked
    - When `find_next_available=True`, scan forward day-by-day skipping non-working days up to 30 calendar days; return a list containing only the single earliest free slot found
    - Exclude inactive doctors and inactive availability rows in all queries
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.4, 8.5, 8.6_
    - **Consistency note:** The slot boundaries, overlap rules, and timezone conversion used here must be identical to those used in Task 7 (`appointment.py`). Consider extracting shared slot logic into a `backend/slots.py` utility module to avoid duplication.

- [ ] 7. Appointment_Service (`backend/appointment.py`)
  - Implement `book_appointment(doctor_id: int, appointment_datetime: str, patient_details: dict, db, clinic_tz: str) -> dict`
    - Open a `BEGIN IMMEDIATE` transaction
    - Upsert patient: `SELECT id FROM PATIENT WHERE first_name=? AND last_name=? AND date_of_birth=? AND phone=?`; `INSERT` if not found
    - Verify slot is unbooked: check for any confirmed appointment where `appointment_datetime` < requested `end_datetime` AND `end_datetime` > requested `appointment_datetime` (overlap check, not just exact-match); `ROLLBACK` and return `{"error": "SLOT_TAKEN"}` if overlap exists.
    - Verify the doctor is active (`is_active=1`); `ROLLBACK` and return `{"error": "DOCTOR_INACTIVE"}` if not.
    - Verify `appointment_datetime` is in the future relative to the current time in `clinic_tz` (i.e. convert `appointment_datetime` from UTC to clinic-local time and compare against `datetime.now(ZoneInfo(clinic_tz))`); `ROLLBACK` and return `{"error": "SLOT_IN_PAST"}` if not.
    - Verify the slot aligns with the doctor's configured working hours: the `appointment_datetime` (in clinic-local time) must fall within an active `DOCTOR_AVAILABILITY` row for that day-of-week and must align exactly to a slot boundary (i.e. `(start_minutes_from_midnight - availability_start_minutes) % slot_duration_minutes == 0`); `ROLLBACK` and return `{"error": "SLOT_NOT_IN_SCHEDULE"}` if not.
    - Generate `booking_reference` as `SC-{year}-{sequence:05d}` where `year` is the clinic-local year derived by converting `appointment_datetime` (UTC) to `clinic_tz`
    - `INSERT` into `APPOINTMENT` with `status='confirmed'`; compute `end_datetime` from `slot_duration_minutes`; store both as timezone-aware UTC strings with a `Z` suffix (e.g. `2026-10-15T04:30:00Z`)
    - Use `datetime.timezone.utc` (or `zoneinfo.ZoneInfo('UTC')`) for all UTC datetime objects; never create naive datetime objects for storage or comparison.
    - `COMMIT` and return `{"booking_reference": "SC-YYYY-NNNNN"}` only after a successful `COMMIT`
    - Never return a booking reference if the transaction was rolled back
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_
  - **Consistency note:** The slot boundaries, overlap rules, and timezone conversion used here must be identical to those used in Task 6.3 (`scheduling.py`). Consider extracting shared slot logic into a `backend/slots.py` utility module to avoid duplication.

- [ ] 8. Tool_Dispatcher (`backend/dispatcher.py`)
  - Implement `dispatch(tool_name: str, tool_args: dict, db, clinic_tz: str) -> dict`
    - Route each tool call to the correct service function
    - Validate parameters before invoking any service, per the design validation table:
      - `search_doctor`: `doctor_name` must be 1–100 non-whitespace chars
      - `suggest_specialty`: `symptom_description` must be non-empty and non-whitespace
      - `get_availability`: `doctor_id` must be present; `date` must be a non-empty string
      - `book_appointment`: all patient fields, `doctor_id`, and `appointment_datetime` must be present
    - Return `{"error": "invalid_param", "detail": "<description>"}` for any parameter violation without invoking the service
    - Return `{"error": "unknown_tool", "tool_name": "<name>"}` for unrecognised tool names
  - _Requirements: 2.1, 2.4, 3.1, 3.2, 4.6, 4.7, 7.1_

- [ ] 9. Conversation_Service (`backend/conversation.py`)
  - Implement `ConversationService` class with `handle_turn(session_id: str, message: str, db) -> str`
    - Load existing `CHAT_SESSION` by `session_id`; if not found, `INSERT` a new row with `status='active'` and empty `thread_history` (`[]`)
    - Build system prompt injecting the current datetime in `Clinic_Timezone` (format: `{datetime} ({clinic_tz})`) and the clinic name ("Super Clinic"), per the design template
    - Append the user message to the thread array
    - Tool-call loop:
      1. Submit the full thread + `TOOLS` to `openai.responses.create` using `settings.model` (never hardcode a model name)
      2. If the response contains tool calls: dispatch each via `Tool_Dispatcher` using the matching `tool_call_id`, append all tool result messages, go to step 1
      3. If the response is a plain-text message: persist the updated `thread_history` to `CHAT_SESSION` and return the text
    - Persist `thread_history` to DB only after the model returns plain text — not on intermediate tool-call turns
    - Update `CHAT_SESSION.last_active_at` to the current UTC datetime as a `Z`-suffixed ISO 8601 string (e.g. `datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')`) on every successful turn
    - On OpenAI error: do NOT update `thread_history`; propagate the exception so the endpoint returns HTTP 500
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 1.8, 9.1, 9.2, 9.3_

- [ ] 10. FastAPI entry point (`backend/main.py`)
  - Import `settings` from `config.py` at module level — this triggers startup validation and exits the process if `OPENAI_API_KEY` or `CLINIC_TIMEZONE` is missing or invalid
  - Add a `@asynccontextmanager` lifespan handler that calls `init_db()` on startup
  - Implement `POST /chat`: validate `ChatRequest` → call `ConversationService.handle_turn` → return `ChatResponse`
  - Return HTTP 400 with named field errors when `ChatRequest` validation fails (field names in the error body)
  - Return HTTP 500 with a generic message for unhandled exceptions; never expose stack traces or internal state in the response body
  - Enable CORS for localhost during development
  - _Requirements: 1.1, 1.6, 1.7, 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 11. React frontend
  - [ ] 11.1 Implement `frontend/src/api/chat.ts`
    - Export `sendMessage(sessionId: string, message: string): Promise<string>` that POSTs `{ session_id, message }` to `/chat` and returns the `reply` string
    - Throw a typed error on non-2xx responses; include the HTTP status in the error
    - Never include the OpenAI API key in any client-side code or HTTP request
    - _Requirements: 10.4_

  - [ ] 11.2 Implement `frontend/src/components/MessageBubble.tsx`
    - Accept `role: 'patient' | 'assistant'` and `text: string` props
    - Render with distinct visual styling per role (e.g. left/right alignment, different background colours)
    - _Requirements: 10.1_

  - [ ] 11.3 Implement `frontend/src/components/InputBar.tsx`
    - Controlled `<textarea>` and submit `<button>`
    - Accept `onSubmit`, `loading: boolean`, and optional `error: string | null` props
    - Disable both the textarea and button while `loading=true`; re-enable when `loading=false`
    - Display `error` as an inline error message below the input without clearing the textarea value
    - _Requirements: 10.2, 10.3_

  - [ ] 11.4 Implement `frontend/src/components/ChatWindow.tsx`
    - Generate `session_id` once on mount via `crypto.randomUUID()` and store in `sessionStorage`; retrieve on subsequent renders
    - Maintain `messages`, `loading`, and `error` state
    - On submit: set `loading=true`, clear `error`, call `sendMessage`, append the user message and the reply to `messages`, set `loading=false`
    - On non-2xx error from `sendMessage`: set `error` (inline, without clearing history), set `loading=false`
    - Render a scrollable list of `MessageBubble` components and the `InputBar`
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

- [ ] 12. Manual verification
  - [ ] 12.1 Startup and environment validation
    - Start the backend with `uvicorn backend.main:app --reload`
    - Confirm it starts successfully with all required env vars set
    - Remove `OPENAI_API_KEY` from env; confirm it exits immediately with a clear log message identifying the missing variable
    - Set `CLINIC_TIMEZONE=UTC+5:30` (invalid IANA identifier); confirm it exits immediately with a clear log message
    - Set `CLINIC_TIMEZONE=Asia/Kolkata` (valid); confirm it starts successfully
    - _Requirements: 11.1, 11.3, 11.4, 11.5_

  - [ ] 12.2 Manual scenario 1 — successful booking
    - Start backend and frontend; open the chat in a browser
    - Ask to book a specific doctor for a date; provide patient details when prompted; confirm the appointment summary
    - Verify the booking reference (format `SC-YYYY-NNNNN`) appears in the chat response
    - Verify the `APPOINTMENT` row exists in SQLite with `status='confirmed'` and `appointment_datetime` stored as a `Z`-suffixed UTC string (e.g. `2026-10-15T04:30:00Z`), not as a naive or offset string.
    - Verify the displayed time in the chat is shown in the clinic's timezone
    - _Requirements: 7.3, 7.4, 7.5_

  - [ ] 12.3 Manual scenario 2 — alternative slot and doctor suggestions
    - Request a doctor who has no availability on today's date; verify the chatbot automatically calls `get_availability` with `find_next_available=true` and presents the next available slot
    - Decline the suggested slot; verify the chatbot offers alternative doctors in the same specialty
    - Decline all alternatives; verify the chatbot ends the conversation politely without creating an appointment
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ] 12.4 Manual invalid input check
    - Submit an empty message from the frontend; verify HTTP 400 is returned with the `message` field name in the error body
    - Provide an invalid date of birth during booking (e.g. a future date); verify the chatbot re-prompts for only the invalid field by name
    - _Requirements: 1.6, 6.2, 6.3_

  - [ ] 12.5 Manual booking conflict check
    - Book a slot successfully; open a new browser tab and attempt to book the same doctor at the same datetime
    - Verify the second attempt receives a `SLOT_TAKEN` response and the chatbot automatically offers the next available slot
    - Verify only one `APPOINTMENT` row exists for that doctor and datetime
    - _Requirements: 7.6_

  - [ ] 12.6 Manual inactive doctor check
    - Attempt to book an appointment with a doctor whose `is_active` flag has been set to `0` in the database. Verify the chatbot does not offer that doctor in search results or availability, and that the booking transaction returns `DOCTOR_INACTIVE` if attempted directly.
    - _Requirements: 8.6_

  - [ ] 12.7 Manual past-slot check
    - Attempt to book a slot that is in the past relative to the clinic's current time (e.g. yesterday at 10:00 AM clinic time). Verify the booking is rejected with a `SLOT_IN_PAST` error and no `APPOINTMENT` row is created.
    - _Requirements: 4.3_

## Notes

- All tasks are required for MVP; none are marked optional
- `OPENAI_MODEL` defaults to `gpt-4o` but can be overridden in `.env` without any code changes — all backend components read the model name from `settings.model`
- `CLINIC_TIMEZONE` must be a valid IANA timezone identifier (e.g. `Asia/Kolkata`, `America/New_York`, `Europe/London`). UTC offset strings like `UTC+5:30` are not valid and will cause the application to exit at startup.
- Automated tests are deferred per the project steering file. The Correctness Properties defined in `design.md` describe what to test when that work is picked up; use `pytest` and `hypothesis` at that stage.
- All datetime comparisons use timezone-aware objects. The `Z` suffix on UTC strings is mandatory; naive datetime strings must not be stored or compared against aware datetimes.
- Slot start times are stored and returned as UTC ISO 8601 strings; the OpenAI model is instructed via the system prompt to present times in `Clinic_Timezone` to the patient.
- The `booking_reference` year component uses the clinic-local year (derived from `appointment_datetime` converted to `clinic_tz`), not UTC year, so a late-night UTC booking that falls on a new day in clinic time receives the correct year prefix.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "3"] },
    { "id": 1, "tasks": ["2.2", "4", "5"] },
    { "id": 2, "tasks": ["6.1", "6.2", "6.3"] },
    { "id": 3, "tasks": ["7"] },
    { "id": 4, "tasks": ["8"] },
    { "id": 5, "tasks": ["9"] },
    { "id": 6, "tasks": ["10"] },
    { "id": 7, "tasks": ["11.1", "11.2", "11.3"] },
    { "id": 8, "tasks": ["11.4"] },
    { "id": 9, "tasks": ["12.1", "12.2", "12.3", "12.4", "12.5", "12.6", "12.7"] }
  ]
}
```
