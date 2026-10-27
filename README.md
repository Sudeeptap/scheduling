# Doctor's Assistant — Super Clinic

A conversational AI chatbot that lets patients book appointments with clinic doctors through natural-language chat. Built as an MVP using the OpenAI Responses API with function calling, FastAPI, SQLite, and React + TypeScript.

---

## How it works

The patient types a message in the browser. The FastAPI backend maintains the conversation thread and sends it to the OpenAI Responses API. The model issues tool calls (search doctor, check availability, book appointment) that the backend dispatches to the database. The model formats the results into a plain-text reply and returns it to the patient. Conversation history is persisted in SQLite between messages.

```
Browser (React)  ──POST /chat──►  FastAPI  ──►  OpenAI Responses API
                                     │              │
                                   SQLite  ◄──tool calls──┘
```

Supported conversation flows:
- Book an appointment with a named doctor
- Get a doctor recommendation by describing symptoms
- Handle no-availability: offer next available slot or alternative doctor
- Double-booking protection via SQLite `BEGIN IMMEDIATE` transactions

---

## Project structure

```
scheduling/
├── backend/
│   ├── main.py           FastAPI app and /chat endpoint
│   ├── config.py         Environment variable validation (exits on bad config)
│   ├── conversation.py   OpenAI Responses API tool-call loop
│   ├── dispatcher.py     Routes tool calls to service functions
│   ├── scheduling.py     Doctor search, specialty lookup, slot availability
│   ├── appointment.py    Atomic booking transaction
│   ├── slots.py          Shared slot-boundary and timezone utilities
│   ├── models.py         Pydantic request/response models
│   ├── tools.py          OpenAI function schemas
│   ├── database.py       SQLite connection management and schema
│   ├── seed.py           Demo data (doctors, specialties, availability)
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/chat.ts            API helper (no OpenAI key in browser)
│       ├── components/
│       │   ├── ChatWindow.tsx     Root chat component, session management
│       │   ├── MessageBubble.tsx  Single message display
│       │   └── InputBar.tsx       Text input with loading and error states
│       ├── App.tsx
│       └── index.css
├── docs/                          Architecture and sequence diagrams (.mmd)
├── .env.example                   Environment variable template
└── clinic.db                      SQLite database (auto-created on first run)
```

---

## Prerequisites

- Python 3.9 or later
- Node.js 18 or later and npm
- An OpenAI API key with access to the Responses API

---

## Setup

### 1. Clone and configure

```bash
git clone <repo-url>
cd scheduling

cp .env.example .env
```

Edit `.env` and fill in the required values:

```env
# Required
OPENAI_API_KEY=sk-...          # Your OpenAI API key
CLINIC_TIMEZONE=Asia/Kolkata   # IANA timezone for the clinic

# Optional (these defaults work for local development)
OPENAI_MODEL=gpt-4o
DATABASE_URL=./clinic.db
```

`CLINIC_TIMEZONE` must be a valid IANA timezone identifier (e.g. `Asia/Kolkata`, `America/New_York`, `Europe/London`). Offset strings like `UTC+5:30` are rejected at startup.

### 2. Install backend dependencies

```bash
pip install -r backend/requirements.txt
```

### 3. Seed the database

This creates the schema and inserts demo doctors. It is safe to run multiple times.

```bash
python -m backend.seed
```

Expected output:
```
Seed complete:
  3 active specialties
  4 active doctors
  20 availability rows
```

Demo doctors:

| Doctor | Specialty | Slot | Hours (Mon–Fri) |
|---|---|---|---|
| Dr. Priya Sharma | General Practice | 30 min | 09:00–17:00 |
| Dr. Rajesh Kumar | Dermatology | 30 min | 10:00–16:00 |
| Dr. Anita Patel | Orthopedics | 45 min | 09:00–13:00 |
| Dr. Suresh Nair | Orthopedics | 30 min | 14:00–18:00 |

### 4. Install frontend dependencies

```bash
cd frontend
npm install
cd ..
```

---

## Running locally

Open two terminals from the repo root.

**Terminal 1 — backend:**

```bash
# Load environment variables (PowerShell)
Get-Content .env | ForEach-Object {
  if ($_ -match '^([^#=][^=]*)=(.*)$') {
    [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
  }
}
uvicorn backend.main:app --reload

# Load environment variables (bash/zsh)
export $(grep -v '^#' .env | xargs)
uvicorn backend.main:app --reload
```

The API starts at `http://localhost:8000`. The startup log will confirm the database path and exit immediately if any required variable is missing or invalid.

**Terminal 2 — frontend:**

```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser. The Vite dev server proxies `/chat` to the backend automatically.

---

## API

### `POST /chat`

**Request:**
```json
{ "session_id": "uuid-v4-string", "message": "Can I see Dr Sharma tomorrow?" }
```

**Response:**
```json
{ "session_id": "uuid-v4-string", "reply": "Dr. Priya Sharma is available..." }
```

**Errors:**
- `422` — missing or invalid request fields
- `500` — OpenAI API error or unhandled internal error (generic message, no stack trace)

The OpenAI API key is never sent to the browser or included in any frontend code.

---

## Example conversations

**Book by doctor name:**
```
You:       Can I see Dr Sharma tomorrow?
Assistant: Dr. Priya Sharma is available tomorrow (Monday). Here are some open slots:
           09:00, 09:30, 10:00... Which time works for you?
You:       10 AM please.
Assistant: I'd need a few details to confirm your booking. What is your full name,
           date of birth, and phone number?
You:       Arjun Mehta, 15 May 1988, +91 98765 43210
Assistant: To confirm: Dr. Priya Sharma on Monday 4 Jan at 10:00 AM for Arjun Mehta.
           Shall I go ahead?
You:       Yes
Assistant: Done! Your booking reference is SC-2027-00001.
```

**By symptoms:**
```
You:       I have a skin rash that won't go away.
Assistant: For skin conditions you would need a dermatologist. We have Dr. Rajesh Kumar
           (Dermatology, Mon–Fri 10:00–16:00). Would you like to book with him?
```

**No availability fallback:**
```
You:       I want to see Dr Nair today.
Assistant: Dr. Suresh Nair has no slots available today. His next available slot is
           tomorrow at 14:00. Would that work, or would you like to see Dr. Anita Patel
           instead?
```

---

## Architecture notes

- **Tool-call loop** — the backend runs the Responses API loop synchronously per `/chat` request. No background workers or queues.
- **Only confirmed appointments block slots** — no pending/hold state.
- **Concurrency** — SQLite `BEGIN IMMEDIATE` prevents two concurrent requests from booking the same slot.
- **Timestamps** — all stored as UTC ISO 8601 with a `Z` suffix. Displayed to patients in `CLINIC_TIMEZONE`.
- **Session history** — the full OpenAI message thread is stored in `CHAT_SESSION.thread_history` as JSON. Written only after a successful turn.

---

## Deferred features (post-MVP)

- Appointment cancellation
- Session expiry
- Admin UI for managing doctors and availability
- PostgreSQL migration
- Authentication

---

## Diagrams

The `docs/` folder contains Mermaid diagrams for:
- `01-system-architecture.mmd` — component overview
- `02-booking-flow.mmd` — booking conversation flowchart
- `03-sequence-diagram.mmd` — end-to-end message sequence
- `04-er-diagram.mmd` — database entity relationships