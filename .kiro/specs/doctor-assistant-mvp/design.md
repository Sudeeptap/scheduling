# Design Document

## Overview

The Doctor's Assistant is an MVP conversational booking system for Super Clinic. Patients interact through a browser-based chat interface powered by a React + TypeScript + Vite frontend. Messages are handled by a Python FastAPI backend that maintains a stateful conversation thread and delegates structured operations to the OpenAI Responses API (GPT-4o) via function calling. The model issues tool calls to search for doctors, look up specialties, check availability, and book appointments. All clinic data and chat state are stored in a SQLite database.

**Diagram references:**

- System architecture: `docs/01-system-architecture.mmd`
- Booking conversation flow: `docs/02-booking-flow.mmd`
- End-to-end sequence: `docs/03-sequence-diagram.mmd`
- Entity-relationship model: `docs/04-er-diagram.mmd`

**Diagram/requirements conflicts noted (no diagrams were altered):**

| # | Conflict | Resolution for MVP |
|---|----------|--------------------|
| 1 | `docs/01-system-architecture.mmd` labels the database as PostgreSQL | MVP uses **SQLite**. PostgreSQL-specific types (`timestamptz`, `jsonb`) are replaced with `TEXT` (ISO 8601 strings and JSON strings respectively). |
| 2 | `docs/01-system-architecture.mmd` shows a `cancel_appointment` tool | `cancel_appointment` is **deferred** for MVP. The tool schema is not registered with the model and the endpoint is not implemented. |
| 3 | `docs/04-er-diagram.mmd` uses `jsonb` for `CHAT_SESSION.thread_history` and `timestamptz` for timestamps | SQLite stores both as `TEXT`; see Data Models section. |
| 4 | `CHAT_SESSION.status` in the ER diagram lists three values (`active`, `completed`, `expired`) | MVP uses only `active` and `completed`. |
| 5 | `APPOINTMENT.status` in the ER diagram lists `confirmed`, `cancelled`, `rescheduled` | MVP only creates appointments with status `confirmed`. Cancellation is deferred. |

---

## Architecture

The system follows a layered, single-process architecture. All components run inside a single FastAPI application process. There is no message queue, no background worker, and no async task dispatch — every `/chat` request is handled synchronously from receipt to response.

```
Browser (React/Vite)
        │  POST /chat { message, session_id }
        ▼
FastAPI Application
  ├── POST /chat route  (main.py)
  ├── Conversation_Service  (conversation.py)
  │     • Loads / creates CHAT_SESSION
  │     • Injects system prompt (clinic name + UTC datetime + tool usage instructions)
  │     • Submits thread to OpenAI Responses API
  │     • Runs tool-call loop until plain-text response
  │     • Persists updated thread to CHAT_SESSION
  ├── Tool_Dispatcher  (dispatcher.py)
  │     • Validates tool call parameters
  │     • Routes each tool call to the correct internal service
  │     • Returns JSON-serialisable result keyed by tool_call_id
  ├── Scheduling_Service  (scheduling.py)
  │     • search_doctor — name-based fuzzy match
  │     • suggest_specialty — returns active specialties; model selects
  │     • get_availability — computes free slots from DOCTOR_AVAILABILITY minus confirmed APPOINTMENT rows
  └── Appointment_Service  (appointment.py)
        • book_appointment — atomic check-then-insert transaction
        • Patient upsert by (first_name, last_name, date_of_birth, phone)
        • booking_reference generation: SC-YYYY-NNNNN
        ▼
SQLite Database (database.py)
  Tables: DOCTOR, SPECIALTY, DOCTOR_SPECIALTY, DOCTOR_AVAILABILITY,
          PATIENT, APPOINTMENT, CHAT_SESSION
```

### Tool-Call Loop

The Conversation_Service runs the tool-call loop entirely within a single HTTP request:

1. Append the patient's message to the thread.
2. Submit the full thread + tool schemas to the OpenAI Responses API.
3. If the response contains **tool calls**: dispatch each call synchronously, collect results keyed by `tool_call_id`, append all results to the thread, go to step 2.
4. If the response is a **plain-text message**: persist the updated thread to `CHAT_SESSION.thread_history` and return the text to the caller.

The loop terminates when the model returns a plain-text response. The model is instructed in the system prompt to always conclude a turn with a plain-text reply to the patient.

---

## Components and Interfaces

### 1. POST /chat Endpoint (`main.py`)

**Request body** (Pydantic):

```python
class ChatRequest(BaseModel):
    session_id: str          # UUID v4, generated client-side
    message: str             # 1–2000 characters, non-empty
```

**Response body** (Pydantic):

```python
class ChatResponse(BaseModel):
    session_id: str
    reply: str               # Plain-text response from the model
```

**Error responses:**

| HTTP Status | Condition |
|-------------|-----------|
| 400 | `message` absent / empty / > 2000 chars, or `session_id` absent / empty |
| 500 | Unhandled internal error or OpenAI API error |

### 2. Conversation_Service (`conversation.py`)

**Key responsibilities:**

- Load existing `CHAT_SESSION` by `session_id`, or create a new row with status `active`.
- Build the system prompt: clinic name ("Super Clinic"), current UTC datetime (ISO 8601), and instructions for tool usage.
- Maintain the full OpenAI message array: system, user, assistant, tool results.
- Run the tool-call loop (see Architecture section).
- Persist the updated thread to `CHAT_SESSION.thread_history` after every turn (before returning).

**System prompt template (injected on every turn):**

```
You are the Doctor's Assistant at Super Clinic.
Current date and time: {datetime} ({clinic_timezone}).
Your job is to help patients book appointments with doctors.
Use the provided tools to search for doctors, check availability, and book appointments.
Always end your response with a plain-text message to the patient.
Never reveal internal tool results or database IDs directly.
```

> `{datetime}` is the current time converted to `Clinic_Timezone` (read from `CLINIC_TIMEZONE` env var). The system prompt always reflects the clinic's local time so relative expressions like "today" and "tomorrow" resolve correctly.

### 3. Tool_Dispatcher (`dispatcher.py`)

Routes tool calls by name. Returns a JSON-serialisable dict for each call. Parameter validation happens here before invoking a service.

| Tool Name | Routes To | Validates |
|-----------|-----------|-----------|
| `search_doctor` | Scheduling_Service | `doctor_name`: 1–100 non-whitespace chars |
| `suggest_specialty` | Scheduling_Service | `symptom_description`: non-empty, non-whitespace |
| `get_availability` | Scheduling_Service | `doctor_id`: exists; `date`: ISO 8601 YYYY-MM-DD |
| `book_appointment` | Appointment_Service | All patient fields + doctor_id + datetime |

Unknown tool names return `{"error": "unknown_tool", "tool_name": "<name>"}`.

### 4. Scheduling_Service (`scheduling.py`)

**`search_doctor(doctor_name: str) -> list[dict]`**

- Case-insensitive `LIKE '%name%'` query on `DOCTOR.first_name || ' ' || DOCTOR.last_name` where `is_active = true`.
- Returns up to 20 results: `id`, `full_name`, `specialties`, `slot_duration_minutes`.

**`suggest_specialty(symptom_description: str) -> list[dict]`**

- Returns all rows from `SPECIALTY` where `is_active = true`.
- The model selects the best match from the returned list; the service does not perform NLP.
- After model selection: service returns active doctors for that specialty (up to 20).

**`get_availability(doctor_id: int, date: str, find_next_available: bool = False) -> dict`**

- Validates that `doctor_id` exists and `date` is a valid ISO 8601 date not in the past. The 'not in the past' check is performed relative to the current date in `Clinic_Timezone`.
- Loads `DOCTOR_AVAILABILITY` rows for the doctor where `is_active = true` and `day_of_week` matches the requested date.
- Subtracts confirmed appointments to produce a list of free slot start times.
- Note: returned slot start times are ISO 8601 strings in UTC; the model is instructed to present them in `Clinic_Timezone` to the patient.
- If `find_next_available = true`: scans forward day-by-day, skipping non-working days, for up to 30 calendar days, returning the single earliest free slot.
- Returns: `{"available_slots": ["2026-10-15T10:00:00", ...]}` or `{"available_slots": []}`.

### 5. Appointment_Service (`appointment.py`)

**`book_appointment(doctor_id, appointment_datetime, patient_details) -> dict`**

> `appointment_datetime` is stored in DB as UTC (ISO 8601). The `booking_reference` year component (`YYYY`) uses the clinic-local year derived from `Clinic_Timezone`, so a booking made at 23:30 UTC on Dec 31 that is Jan 1 in clinic time gets the new year's prefix.

Executes an atomic SQLite transaction:

```sql
BEGIN IMMEDIATE;
-- 1. Patient upsert: find existing or insert new
SELECT id FROM PATIENT
  WHERE first_name = ? AND last_name = ? AND date_of_birth = ? AND phone = ?;
-- If not found: INSERT INTO PATIENT ...

-- 2. Slot integrity check
SELECT COUNT(*) FROM APPOINTMENT
  WHERE doctor_id = ? AND appointment_datetime = ? AND status = 'confirmed';
-- If count > 0: ROLLBACK and return SLOT_TAKEN error

-- 3. Generate booking_reference
SELECT COALESCE(MAX(CAST(SUBSTR(booking_reference, 9) AS INTEGER)), 0) + 1
  FROM APPOINTMENT
  WHERE booking_reference LIKE 'SC-YYYY-%';
-- Format as SC-{year}-{sequence:05d}

-- 4. Insert appointment
INSERT INTO APPOINTMENT (booking_reference, doctor_id, patient_id, appointment_datetime,
                          end_datetime, status)
  VALUES (?, ?, ?, ?, ?, 'confirmed');
COMMIT;
```

Returns `{"booking_reference": "SC-2026-00042"}` on success, or `{"error": "SLOT_TAKEN"}` on conflict.

### 6. OpenAI Tool Schemas (`tools.py`)

Four tools are registered with the model for MVP. `cancel_appointment` is excluded.

```python
TOOLS = [
    {
        "type": "function",
        "name": "search_doctor",
        "description": "Search for a doctor by name. Returns up to 20 matching doctors.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string", "description": "Partial or full doctor name"}
            },
            "required": ["doctor_name"]
        }
    },
    {
        "type": "function",
        "name": "suggest_specialty",
        "description": "Return all active medical specialties for the model to match against patient symptoms.",
        "parameters": {
            "type": "object",
            "properties": {
                "symptom_description": {"type": "string"}
            },
            "required": ["symptom_description"]
        }
    },
    {
        "type": "function",
        "name": "get_availability",
        "description": "Get available appointment slots for a doctor on a given date.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "integer"},
                "date": {"type": "string", "description": "ISO 8601 date, e.g. 2026-10-15"},
                "find_next_available": {
                    "type": "boolean",
                    "description": "If true, scan forward up to 30 days for the next free slot",
                    "default": false
                }
            },
            "required": ["doctor_id", "date"]
        }
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": "Book a confirmed appointment for a patient.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "integer"},
                "appointment_datetime": {"type": "string", "description": "ISO 8601 datetime"},
                "patient": {
                    "type": "object",
                    "properties": {
                        "first_name": {"type": "string"},
                        "last_name": {"type": "string"},
                        "date_of_birth": {"type": "string", "description": "YYYY-MM-DD"},
                        "phone": {"type": "string"}
                    },
                    "required": ["first_name", "last_name", "date_of_birth", "phone"]
                }
            },
            "required": ["doctor_id", "appointment_datetime", "patient"]
        }
    }
]
```

### 7. Frontend (`frontend/src/`)

Three React components, one API helper:

| File | Responsibility |
|------|----------------|
| `ChatWindow.tsx` | Root component. Holds message list state, `session_id` (UUID v4, generated once on mount, stored in `sessionStorage`), loading flag. Renders `MessageBubble` list + `InputBar`. |
| `MessageBubble.tsx` | Renders a single message with `role` styling (patient vs. assistant). |
| `InputBar.tsx` | Controlled textarea + submit button. Disabled while `loading = true`. Shows inline error if API returns non-2xx. |
| `api/chat.ts` | `sendMessage(sessionId, message)` — POSTs to `/chat`, returns `reply` string. No OpenAI key included. |

The `session_id` is initialised once per browser session using `crypto.randomUUID()` and stored in `sessionStorage` so it persists across page navigations within the tab but not across new tabs.

---

## Data Models

### SQLite Schema (MVP adaptations from ER diagram)

> The ER diagram (`docs/04-er-diagram.mmd`) defines the canonical entity model. The following DDL adapts it to SQLite constraints: `timestamptz` → `TEXT` (ISO 8601), `jsonb` → `TEXT` (JSON string), `varchar(n)` → `TEXT`.

```sql
CREATE TABLE IF NOT EXISTS SPECIALTY (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1  -- 1=true, 0=false
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
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Mon, 6=Sun
    start_time  TEXT NOT NULL,   -- HH:MM
    end_time    TEXT NOT NULL,   -- HH:MM; must be > start_time (enforced in app layer)
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS PATIENT (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,  -- YYYY-MM-DD
    phone         TEXT NOT NULL,
    email         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_patient_identity
    ON PATIENT (first_name, last_name, date_of_birth, phone);

CREATE TABLE IF NOT EXISTS APPOINTMENT (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_reference    TEXT NOT NULL UNIQUE,           -- SC-YYYY-NNNNN
    doctor_id            INTEGER NOT NULL REFERENCES DOCTOR(id),
    patient_id           INTEGER NOT NULL REFERENCES PATIENT(id),
    appointment_datetime TEXT NOT NULL,                  -- ISO 8601 datetime
    end_datetime         TEXT NOT NULL,                  -- ISO 8601 datetime
    status               TEXT NOT NULL DEFAULT 'confirmed'
                             CHECK (status IN ('confirmed')),  -- cancelled deferred
    notes                TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_appointment_slot
    ON APPOINTMENT (doctor_id, appointment_datetime, status);

> Timestamps stored in UTC. Convert to `Clinic_Timezone` for all patient-facing display.

CREATE TABLE IF NOT EXISTS CHAT_SESSION (
    session_id      TEXT PRIMARY KEY,
    thread_history  TEXT NOT NULL DEFAULT '[]',  -- JSON array of OpenAI message objects
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed')),  -- expired deferred
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_active_at  TEXT
);
```

### Pydantic Models (`models.py`)

```python
class PatientDetails(BaseModel):
    first_name: str     # max 50 chars
    last_name: str      # max 50 chars
    date_of_birth: str  # YYYY-MM-DD, validated: 1900-01-01 to today (exclusive)
    phone: str          # 10–15 digits, optional separators: spaces, hyphens, parens, country code

class ChatRequest(BaseModel):
    session_id: str
    message: str        # 1–2000 chars

class ChatResponse(BaseModel):
    session_id: str
    reply: str
```

### booking_reference Generation

The sequence is derived at insert time within the same transaction:

```python
year = datetime.utcnow().year
row = db.execute(
    "SELECT COALESCE(MAX(CAST(SUBSTR(booking_reference, 9) AS INTEGER)), 0) + 1 "
    "FROM APPOINTMENT WHERE booking_reference LIKE ?",
    (f"SC-{year}-%",)
).fetchone()
sequence = row[0]
booking_reference = f"SC-{year}-{sequence:05d}"
```

This runs inside `BEGIN IMMEDIATE` so no concurrent transaction can observe the same sequence value.

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Confirmed appointments always block slots

*For any* doctor and any datetime for which a `confirmed` appointment exists, every subsequent call to `get_availability` for that doctor and that date SHALL return a slot list that does not include that datetime.

**Validates: Requirements 4.1, 7.7**

### Property 2: booking_reference uniqueness within a year

*For any* sequence of successful `book_appointment` calls in the same calendar year, all returned `booking_reference` values SHALL be distinct strings matching the pattern `SC-{YYYY}-{NNNNN}` where the numeric suffix is unique.

**Validates: Requirements 7.3**

### Property 3: Tool-call loop termination

*For any* valid patient message and any tool call sequence the model may generate, the Conversation_Service tool-call loop SHALL terminate with a plain-text assistant response; it SHALL NOT loop indefinitely or return a tool call as the final response.

**Validates: Requirements 1.3, 1.8**

### Property 4: Patient upsert is idempotent

*For any* combination of (first_name, last_name, date_of_birth, phone), inserting or upserting the same patient details any number of times SHALL result in exactly one `PATIENT` row with that identity, and SHALL always return the same `patient_id`.

**Validates: Requirements 7.2**

### Property 5: Booking reference is never returned before DB commit

*For any* successful `book_appointment` call, the `/chat` endpoint SHALL only include the `booking_reference` in the response text after the `APPOINTMENT` row has been committed to the database; a booking reference SHALL NOT appear in any response whose corresponding DB transaction was rolled back or never executed.

**Validates: Requirements 7.4, 7.5**

### Property 6: Patient detail validation rejects all invalid inputs

*For any* set of patient details where at least one field violates the validation rules (first_name or last_name empty or > 50 chars, date_of_birth not a valid date in range 1900-01-01 to today, or phone not matching the accepted digit/separator pattern), the validation layer SHALL reject the input and identify exactly which fields failed.

**Validates: Requirements 6.2, 6.3**

### Property 7: Chat thread grows monotonically per turn

*For any* sequence of valid messages sent with the same `session_id`, the `thread_history` stored in `CHAT_SESSION` after each turn SHALL contain all previous messages in their original order, and the thread length SHALL increase by at least two entries (one user turn, one assistant turn) per turn.

**Validates: Requirements 1.4, 9.1, 9.2**

---

## Error Handling

### Input Validation Errors (HTTP 400)

| Condition | Response |
|-----------|----------|
| `message` absent, empty, or > 2000 chars | 400 with field name in error body |
| `session_id` absent or empty | 400 with field name in error body |
| Tool call parameter invalid (caught in dispatcher) | Tool result `{"error": "invalid_param", "detail": "..."}` returned to model; model informs patient |

### Service Errors

| Condition | Handling |
|-----------|----------|
| Doctor not found (`search_doctor`) | Returns empty list; model tells patient |
| No doctors for specialty | Returns empty list; model tells patient |
| `doctor_id` not found (`get_availability`) | Returns `{"error": "doctor_not_found"}` |
| Invalid date format (`get_availability`) | Returns `{"error": "invalid_date"}` |
| No availability in 30-day window | Returns `{"available_slots": []}` |
| `SLOT_TAKEN` (concurrent booking) | Appointment_Service returns `{"error": "SLOT_TAKEN"}`; model re-invokes `get_availability` and offers next slot |

### OpenAI API Errors

- Any error from the OpenAI Responses API causes the Conversation_Service to **not** update `CHAT_SESSION.thread_history` and return HTTP 500 with a generic message.
- Stack traces and internal state are never exposed in the HTTP response body.

### Startup Validation

If `OPENAI_API_KEY` is not set at process start, or if `CLINIC_TIMEZONE` is not set or is not a valid IANA timezone identifier, the backend logs an error identifying the missing/invalid variable and exits before binding to any port. Use the `zoneinfo` standard library (Python 3.9+) to validate the timezone identifier. This check runs before FastAPI initialises the server.

---

## Testing Strategy

> Per the project steering file, the initial MVP skips automated test setup. The testing strategy below defines the intended approach for post-MVP quality work, and the correctness properties above are written to be implemented as property-based tests at that stage.

### Unit Tests (pytest)

Focus on pure logic that does not require a running server or live OpenAI calls:

- `scheduling.py` — slot computation: given a set of `DOCTOR_AVAILABILITY` rows and `APPOINTMENT` rows, verify the correct free slots are returned for a given date.
- `appointment.py` — `booking_reference` generation format and sequence increment logic.
- `models.py` — Pydantic validation for `PatientDetails` (name length, DOB range, phone pattern).
- `dispatcher.py` — parameter validation for each tool call.

### Property-Based Tests (Hypothesis, minimum 100 iterations each)

Each property test references a Correctness Property from this document.

**Feature: doctor-assistant-mvp, Property 1: Confirmed appointments always block slots**

Generate random (doctor_id, datetime) pairs, insert a confirmed appointment, then call the slot computation function and assert the booked datetime is absent from the result.

**Feature: doctor-assistant-mvp, Property 2: booking_reference uniqueness within a year**

Generate random sequences of booking insertions for the same year within a `BEGIN IMMEDIATE` transaction. Assert all returned references are distinct and match `SC-{YYYY}-{NNNNN}` with a strictly increasing suffix.

**Feature: doctor-assistant-mvp, Property 3: Tool-call loop termination**

Generate random sequences of mock tool call responses (of varying length), with the final item always being a text response. Assert the loop exits after consuming the sequence and returns the text. Additionally, verify that a mock that never returns text causes the loop to respect a maximum iteration guard.

**Feature: doctor-assistant-mvp, Property 4: Patient upsert is idempotent**

Generate random `PatientDetails` structs and call the patient upsert function multiple times with the same data. Assert only one row exists and the returned `patient_id` is consistent across all calls.

**Feature: doctor-assistant-mvp, Property 5: Booking reference is never returned before DB commit**

Simulate a forced rollback after the sequence number is computed but before `COMMIT`. Assert no booking reference is returned and no row is present in `APPOINTMENT`.

**Feature: doctor-assistant-mvp, Property 6: Patient detail validation rejects all invalid inputs**

Generate random `PatientDetails` structs with at least one invalid field (using Hypothesis strategies for boundary strings, invalid dates, invalid phone patterns). Assert that validation fails for all invalid inputs and the error identifies the correct field(s). Also assert that valid inputs pass without error.

**Feature: doctor-assistant-mvp, Property 7: Chat thread grows monotonically per turn**

Generate sequences of 2–10 valid messages with the same `session_id` (using mocked OpenAI responses). After each turn, read `CHAT_SESSION.thread_history` and assert: (a) all prior messages are still present in order, (b) the thread length increased by at least 2 per turn.

### Integration Tests (pytest + TestClient)

Use FastAPI `TestClient` with an in-memory SQLite database and mocked OpenAI responses:

- Successful booking end-to-end (matches Scenario 1 in `docs/03-sequence-diagram.mmd`).
- Alternate slot suggestion when no availability (matches Scenario 2 in `docs/03-sequence-diagram.mmd`).
- `SLOT_TAKEN` concurrent booking race (simulate with two sequential requests hitting the same slot).
- HTTP 400 on missing or invalid `message` / `session_id`.
- HTTP 500 on OpenAI API failure.

### Frontend Tests

- `InputBar` is disabled while `loading = true` and re-enabled on response.
- Inline error is displayed without clearing conversation history on non-2xx response.
- `session_id` is generated once on mount and reused across messages.

### Manual Verification (MVP)

Per the steering file, the primary MVP verification is manual:

1. Run the full booking scenario (Scenario 1 from `docs/03-sequence-diagram.mmd`).
2. Run the alternate slot/doctor scenario (Scenario 2).
3. Verify the booking reference appears in the DB after booking confirmation.
4. Verify the frontend shows a loading state and handles error responses.
