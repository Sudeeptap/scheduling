# Requirements Document

## Introduction

The Doctor's Assistant is a conversational AI chatbot for Super Clinic that allows patients to book, query, and cancel doctor appointments through natural language. It is powered by the OpenAI Responses API with function calling, backed by a FastAPI Python server and an SQLite database. A React + TypeScript frontend presents the chat interface. The system resolves natural language queries (symptoms, doctor names, relative dates) into structured database operations, presents appointment options, collects patient details, and confirms bookings while maintaining slot integrity under concurrent access.

---

## Glossary

- **Chatbot**: The end-to-end Doctor's Assistant system, including frontend, backend, and AI layer.
- **Conversation_Service**: The FastAPI component that manages per-session conversation threads and relays messages to the OpenAI Responses API.
- **Tool_Dispatcher**: The FastAPI component that receives `tool_call` requests from the OpenAI model and routes them to the appropriate internal service.
- **Scheduling_Service**: The internal service responsible for doctor search, specialty lookup, and availability computation.
- **Appointment_Service**: The internal service responsible for creating, cancelling, and updating appointment records.
- **OpenAI_Model**: The GPT-4o model accessed via the OpenAI Responses API, responsible for natural language understanding and tool call generation.
- **Patient**: A person interacting with the Chatbot to book or query an appointment.
- **Doctor**: A medical professional registered in the clinic's database with one or more specialties and a weekly availability schedule.
- **Slot**: A contiguous block of time of duration equal to a doctor's `slot_duration_minutes`, derived from the doctor's availability schedule and not already occupied by a `confirmed` appointment.
- **Booking_Reference**: A unique identifier assigned to a confirmed appointment, formatted as `SC-YYYY-NNNNN`.
- **Session**: A stateful conversation identified by a `session_id`, persisting the full message thread for the duration of the interaction.
- **DB**: The SQLite database storing doctors, specialties, availability schedules, patients, appointments, and chat sessions.
- **Clinic_Timezone**: The IANA timezone identifier (e.g. `Asia/Kolkata`, `America/New_York`) configured via the `CLINIC_TIMEZONE` environment variable. All patient-facing date and time values are expressed in this timezone. Appointment timestamps are stored in UTC in DB and converted to Clinic_Timezone for display.

---

## Requirements

### Requirement 1: Natural Language Message Processing

**User Story:** As a Patient, I want to send free-text messages to the Chatbot, so that I can interact without learning any command syntax.

#### Acceptance Criteria

1. WHEN a Patient sends a POST request to `/chat` with a non-empty `message` string of 1–2000 characters and a `session_id`, THE Conversation_Service SHALL forward the message and the full session thread to the OpenAI_Model for processing.
2. THE Conversation_Service SHALL inject the current date and time expressed in Clinic_Timezone into the system prompt on every turn, so that relative expressions such as "tomorrow" or "next Monday" can be resolved correctly.
3. WHEN the OpenAI_Model returns a plain-text response with no tool calls, THE Conversation_Service SHALL return that text to the Patient as the `/chat` response.
4. WHEN a turn completes, THE Conversation_Service SHALL persist the updated message thread to the `CHAT_SESSION` record in DB before returning the response to the Patient.
5. IF a `session_id` is not found in DB, THEN THE Conversation_Service SHALL create a new `CHAT_SESSION` record with status `active` before processing the first message.
6. IF the `message` field is absent, empty, or exceeds 2000 characters, THEN THE Conversation_Service SHALL return an error response indicating the invalid input without forwarding the message to the OpenAI_Model.
7. IF the OpenAI_Model returns an error, THEN THE Conversation_Service SHALL return an HTTP 500 error response to the Patient and SHALL NOT update the `CHAT_SESSION` record in DB.
8. WHEN the OpenAI_Model returns one or more tool calls, THE Conversation_Service SHALL execute each tool call against the backend services, collect the results, and return each result to the OpenAI_Model in a follow-up request using the matching `tool_call_id`, continuing this loop until the model returns a plain-text response.

---

### Requirement 2: Doctor Search by Name

**User Story:** As a Patient, I want to ask for a specific doctor by name, so that I can book with my preferred doctor.

#### Acceptance Criteria

1. WHEN the OpenAI_Model issues a `search_doctor` tool call with a `doctor_name` parameter containing between 1 and 100 non-whitespace characters, THE Tool_Dispatcher SHALL invoke the Scheduling_Service to perform a case-insensitive partial-name match against the doctor records.
2. IF one or more doctors match the provided name, THEN THE Scheduling_Service SHALL return up to 20 matching results, each containing the doctor's `id`, full name, specialty list, and `slot_duration_minutes`, to the Tool_Dispatcher.
3. IF no doctor matches the provided name, THEN THE Scheduling_Service SHALL return an empty result, and THE OpenAI_Model SHALL inform the Patient that the doctor was not found and offer to search by specialty instead.
4. IF the `doctor_name` parameter is absent, empty, or contains only whitespace characters, THEN THE Tool_Dispatcher SHALL return an error response indicating an invalid search term without invoking the Scheduling_Service.

---

### Requirement 3: Specialty Identification from Symptoms

**User Story:** As a Patient, I want to describe my symptoms in plain language, so that the Chatbot can identify the right medical specialty for me.

#### Acceptance Criteria

1. WHEN the OpenAI_Model issues a `suggest_specialty` tool call with a non-empty `symptom_description` parameter, THE Tool_Dispatcher SHALL invoke the Scheduling_Service to return all active specialties (where `is_active = true`) from DB.
2. IF the `symptom_description` parameter is absent or contains only whitespace, THEN THE Tool_Dispatcher SHALL return an error response indicating an invalid symptom description without invoking the Scheduling_Service.
3. WHEN the Scheduling_Service returns the active specialty list, THE OpenAI_Model SHALL select exactly one specialty from the returned list that best matches the Patient's described symptoms; THE OpenAI_Model SHALL NOT infer a specialty that is absent from the returned list.
4. IF the OpenAI_Model cannot match the described symptoms to any specialty in the returned list, THEN THE OpenAI_Model SHALL inform the Patient that the symptoms do not correspond to any available specialty and ask whether the Patient needs further assistance.
5. WHEN the OpenAI_Model identifies a specialty, THE Scheduling_Service SHALL query DB for all active doctors (where `is_active = true`) associated with that specialty.
6. IF no active doctors are found for the identified specialty, THEN THE OpenAI_Model SHALL inform the Patient that the clinic does not currently have a specialist for that condition and ask whether the Patient needs further assistance.
7. WHEN active doctors are found for the identified specialty, THE OpenAI_Model SHALL present up to 20 doctors to the Patient, each identified by full name and specialty, and ask which one the Patient would like to see.

---

### Requirement 4: Availability Check and Slot Computation

**User Story:** As a Patient, I want to see available time slots for a doctor on a given date, so that I can choose a convenient appointment time.

#### Acceptance Criteria

1. WHEN the OpenAI_Model issues a `get_availability` tool call with a valid `doctor_id` and a valid `date`, THE Scheduling_Service SHALL return the available slots for that date by excluding all time ranges already occupied by appointments with status `confirmed` from the doctor's schedule defined in `DOCTOR_AVAILABILITY`.
2. WHEN the OpenAI_Model issues a `get_availability` tool call with a valid `doctor_id` and a valid `date`, THE Scheduling_Service SHALL return available slots as a list of ISO 8601 datetime strings each representing the start time of a free slot, where each slot has a duration equal to `slot_duration_minutes` (between 1 and 480 minutes inclusive).
3. IF the requested `date` falls outside the doctor's working days as defined in `DOCTOR_AVAILABILITY`, or the requested `date` is earlier than the current date in Clinic_Timezone, THEN THE Scheduling_Service SHALL return an empty slot list for that date.
4. WHEN the `get_availability` tool call includes `find_next_available: true`, THE Scheduling_Service SHALL scan forward from the requested date, skipping dates that fall outside the doctor's working days, up to 30 calendar days, and return a list containing the single earliest free slot found.
5. IF no free slot is found within 30 calendar days of the requested date, THEN THE Scheduling_Service SHALL return an empty slot list, and THE OpenAI_Model SHALL relay a message to the Patient indicating that no availability was found within the next 30 days.
6. IF the `get_availability` tool call specifies a `doctor_id` that does not exist in the system, THEN THE Scheduling_Service SHALL return an error response indicating the doctor was not found, without returning any slot data.
7. IF the `get_availability` tool call specifies a `date` that is not a valid calendar date in ISO 8601 format (YYYY-MM-DD), THEN THE Scheduling_Service SHALL return an error response indicating the date parameter is invalid, without returning any slot data.

---

### Requirement 5: Alternate Slot and Doctor Suggestion

**User Story:** As a Patient, I want the Chatbot to suggest alternatives when my preferred slot or doctor is unavailable, so that I can still book an appointment without starting over.

#### Acceptance Criteria

1. WHEN the Scheduling_Service returns an empty slot list for a requested doctor and date, THE OpenAI_Model SHALL call `get_availability` with `find_next_available: true` to search for the doctor's next available slot within 30 calendar days.
2. WHEN the next available slot for the requested doctor is found within 30 days, THE OpenAI_Model SHALL present it to the Patient stating the date and time, and ask whether the Patient accepts the alternative.
3. WHEN the Patient declines the alternative slot, THE OpenAI_Model SHALL call `search_doctor` with the doctor's specialty to retrieve up to 5 other active doctors in the same specialty, excluding the original doctor, and present them to the Patient.
4. IF `search_doctor` returns no other active doctors in the same specialty, THEN THE OpenAI_Model SHALL inform the Patient that no alternative doctors are available and ask whether the Patient needs further assistance.
5. WHEN the Patient declines all alternative doctors and slots, THE OpenAI_Model SHALL end the conversation politely without creating an appointment record.

---

### Requirement 6: Patient Detail Collection and Validation

**User Story:** As a Patient, I want to provide my personal details once per booking, so that the clinic has the information needed to manage my appointment.

#### Acceptance Criteria

1. WHEN a slot is tentatively selected, THE OpenAI_Model SHALL request the Patient's first name, last name, date of birth, and phone number before proceeding to booking confirmation.
2. WHEN patient details are provided, THE OpenAI_Model SHALL validate that first name and last name are non-empty strings of at most 50 characters each, date of birth is a valid calendar date between 1900-01-01 and the current date (exclusive), and phone number contains 10 to 15 digits optionally prefixed with a country code and may include spaces, hyphens, or parentheses as separators.
3. IF any required detail is missing or invalid, THEN THE OpenAI_Model SHALL re-prompt the Patient for only the missing or invalid fields, stating which fields need correction.
4. WHEN all patient details are valid, THE OpenAI_Model SHALL present a full appointment summary — including doctor name, date, time, patient name, and DOB — and ask the Patient to confirm or cancel.

---

### Requirement 7: Appointment Booking

**User Story:** As a Patient, I want to confirm and book an appointment, so that a slot is reserved for me and I receive a reference number.

#### Acceptance Criteria

1. WHEN the Patient confirms the appointment summary, THE OpenAI_Model SHALL issue a `book_appointment` tool call with `doctor_id`, `appointment_datetime`, and the validated patient details.
2. WHEN the Appointment_Service receives a `book_appointment` call, THE Appointment_Service SHALL execute an atomic database transaction that inserts the `APPOINTMENT` record and inserts or retrieves the `PATIENT` record; the transaction SHALL verify the slot is still unbooked before inserting.
3. WHEN the booking transaction succeeds, THE Appointment_Service SHALL return a unique `Booking_Reference` in the format `SC-YYYY-NNNNN`, where `YYYY` is the four-digit booking year and `NNNNN` is a zero-padded numeric sequence from 00001 to 99999 scoped per year.
4. WHEN the Appointment_Service returns a `Booking_Reference`, THE Appointment_Service SHALL have already committed the `APPOINTMENT` record to DB; THE OpenAI_Model SHALL present the `Booking_Reference` to the Patient only after receiving confirmation of the committed record.
5. WHEN the Appointment_Service returns a `Booking_Reference`, THE OpenAI_Model SHALL present the Patient with a confirmation message containing the `Booking_Reference`, the doctor's name, and the confirmed appointment date and time.
6. IF the booking transaction fails because the requested slot was taken by a concurrent request, THEN THE Appointment_Service SHALL return a `SLOT_TAKEN` error, and THE OpenAI_Model SHALL inform the Patient and automatically re-invoke `get_availability` for the same doctor to offer the next chronologically available slot.
7. THE Appointment_Service SHALL set the confirmed appointment's status to `confirmed` upon successful booking, making that slot unavailable for all subsequent availability queries.

---

### Requirement 8: Clinic Data Configuration

**User Story:** As a Clinic Administrator, I want doctor and availability data to be stored in the database, so that the Chatbot always reflects the current schedule.

#### Acceptance Criteria

1. THE DB SHALL store each Doctor with at least: first name and last name (each a non-empty string of at most 100 characters), slot duration in minutes (an integer between 5 and 480 inclusive), and active status.
2. THE DB SHALL store each specialty with a unique name and active status, linked to doctors via a many-to-many join table.
3. THE DB SHALL store each doctor's weekly availability as one or more `DOCTOR_AVAILABILITY` rows, each specifying day of week (0 = Monday, 6 = Sunday), a start time, and an end time, where start time must be earlier than end time.
4. THE Scheduling_Service SHALL compute available slots at query time from `DOCTOR_AVAILABILITY` rows and confirmed appointments.
5. WHEN a `DOCTOR_AVAILABILITY` row is marked inactive (`is_active = false`), THE Scheduling_Service SHALL exclude that row when computing free slots.
6. WHEN a Doctor record is marked inactive (`is_active = false`), THE Scheduling_Service SHALL exclude all availability rows for that doctor and return no slots for that doctor in any availability query.

---

### Requirement 9: Chat Session Persistence

**User Story:** As a Patient, I want my conversation to remain coherent across multiple messages, so that I do not have to repeat context within a single booking session.

#### Acceptance Criteria

1. THE Conversation_Service SHALL store the full ordered message thread (user turns, assistant turns, tool calls, tool results) in the `thread_history` JSON column of `CHAT_SESSION`.
2. WHEN a Patient sends a follow-up message with an existing `session_id`, THE Conversation_Service SHALL retrieve the stored thread and append the new message before calling the OpenAI_Model.
3. IF a `session_id` is provided that does not exist in DB, THEN THE Conversation_Service SHALL create a new `CHAT_SESSION` record with status `active` for that `session_id` before processing the message.

---

### Requirement 10: Frontend Chat Interface

**User Story:** As a Patient, I want a browser-based chat interface, so that I can interact with the Chatbot without installing any software.

#### Acceptance Criteria

1. THE Frontend SHALL present a scrollable conversation history that displays each message attributed to either the Patient or the Chatbot.
2. THE Frontend SHALL display a loading indicator and disable the message input field WHILE a Chatbot response is pending, re-enabling the input field when the response is received.
3. IF the `/chat` API call returns a non-2xx HTTP status, THEN THE Frontend SHALL display an inline error message without clearing the conversation history and SHALL re-enable the message input field so the Patient can retry.
4. THE Frontend SHALL not include the OpenAI API key in any client-side code or HTTP request.
5. THE Frontend SHALL maintain the `session_id` for the duration of the browser session and include it in every `/chat` request.

---

### Requirement 11: API Security and Configuration

**User Story:** As a Developer, I want secrets to be managed via environment variables, so that API keys are never exposed in source code or version control.

#### Acceptance Criteria

1. THE Backend SHALL read the OpenAI API key exclusively from an environment variable named `OPENAI_API_KEY` and SHALL NOT hardcode it in any source file.
2. THE Backend SHALL read the SQLite database file path from an environment variable named `DATABASE_URL`, defaulting to `./clinic.db` if the variable is not set.
3. IF `OPENAI_API_KEY` is not set at startup, THEN THE Backend SHALL write an error message to the application log indicating the missing variable and terminate the process without binding to any port.
4. THE Backend SHALL read the clinic timezone from an environment variable named `CLINIC_TIMEZONE` whose value must be a valid IANA timezone identifier.
5. IF `CLINIC_TIMEZONE` is not set at startup or its value is not a valid IANA timezone identifier, THEN THE Backend SHALL write an error message to the application log indicating the missing or invalid variable and terminate the process without binding to any port.
6. THE Backend SHALL return HTTP 400 for requests with missing or empty `message` or `session_id` fields, with an error body that identifies each missing or empty field by name.
7. THE Backend SHALL return HTTP 500 with a generic error message for unhandled internal errors, without exposing stack traces or internal state to the caller.
