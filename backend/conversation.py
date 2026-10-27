"""
backend/conversation.py -- Conversation_Service  (Task 9)

Implements ConversationService.handle_turn() which:
  1. Loads or creates a CHAT_SESSION row
  2. Injects a system prompt with the current clinic-local datetime
  3. Runs the Responses API tool-call loop until the model returns plain text
  4. Persists the full thread only after a final plain-text response
  5. Propagates OpenAI errors without touching the persisted thread
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

import openai

from backend.config import settings
from backend.dispatcher import dispatch
from backend.tools import TOOLS

logger = logging.getLogger(__name__)

# Safety cap: stop the tool loop after this many tool-call rounds per turn.
# Prevents runaway loops if the model keeps calling tools without finishing.
_MAX_TOOL_ROUNDS = 20


_SYSTEM_PROMPT_TEMPLATE = """\
You are the Doctor's Assistant at Super Clinic.
Current date and time: {datetime} ({clinic_tz}).

Your job is to help patients find doctors and book appointments.

TOOL USAGE RULES:

TOOL USAGE RULES:
1. When a patient asks for a doctor by name, or a partial name such as "Dr Sharma",
   call search_doctor with the name they provided. Do not claim a doctor cannot
   be found until you have checked the tool results.

2. When a patient asks which doctors are available for a specialty, call
   search_doctors_by_specialty with the specialty name they requested.
   Use the returned doctors to answer. Do not say you cannot search by specialty
   if the tool is available.

3. When a patient describes a health concern and needs help choosing a specialty,
   call suggest_specialty with their description. Do not diagnose the patient.
   After identifying a suitable specialty, use search_doctors_by_specialty to
   find doctors in that specialty.

4. When a patient asks for available appointment times, call get_availability.

5. When a patient wants to book an appointment, collect the required patient
   details and appointment preferences. Summarize the appointment and obtain
   explicit confirmation before calling book_appointment.

6. Never invent doctors, specialties, available slots, or booking references.

7. If a tool returns no matching doctors, explain that no matching active doctor
   was found and ask whether the patient would like to try another specialty or
   doctor name.


When presenting appointment times, always use the clinic local timezone
({clinic_tz}), never UTC.
Never reveal internal database IDs, raw tool results, or UTC timestamps.
Never claim a booking is complete unless book_appointment returns a booking_reference.
Always respond with a clear, patient-facing message.
"""



class ConversationService:
    """Stateful conversation manager backed by CHAT_SESSION in SQLite."""

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        self._client = openai.OpenAI(api_key=settings.api_key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def handle_turn(self, session_id: str, message: str) -> str:
        """Process one patient message and return the assistant reply.

        Args:
            session_id: Stable identifier for the conversation session.
            message:    The patient's latest message text.

        Returns:
            The assistant's plain-text reply string.

        Raises:
            openai.OpenAIError (or subclass) on API failure -- caller maps to HTTP 500.
            Any unexpected exception is propagated unchanged.
        """
        db = self._db

        # 1. Load or create session -----------------------------------------
        row = db.execute(
            "SELECT thread_history FROM CHAT_SESSION WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            db.execute(
                "INSERT INTO CHAT_SESSION (session_id, thread_history, status) "
                "VALUES (?, '[]', 'active')",
                (session_id,),
            )
            thread: list = []
        else:
            thread = json.loads(row["thread_history"])

        # 2. Build system prompt with clinic-local datetime -------------------
        now_local = datetime.now(settings.tz)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            datetime=now_local.strftime("%Y-%m-%d %H:%M"),
            clinic_tz=settings.clinic_timezone,
        )

        # 3. Append user message to thread ------------------------------------
        thread.append({"role": "user", "content": message})

        # 4. Tool-call loop ---------------------------------------------------
        # We keep a local working copy of the input list.  The Responses API
        # takes `input` (the full conversation) and returns `output` (new items).
        # After each round we append the output items to the thread so context
        # accumulates correctly.
        input_messages = [{"role": "system", "content": system_prompt}] + thread
        reply_text: str | None = None

        for _round in range(_MAX_TOOL_ROUNDS):
            response = self._client.responses.create(
                model=settings.model,
                input=input_messages,
                tools=TOOLS,
            )

            # Separate tool calls from text items in this response
            tool_calls = []
            text_parts: list[str] = []

            for item in response.output:
                if item.type == "function_call":
                    tool_calls.append(item)
                elif item.type == "message":
                    for content_part in item.content:
                        if content_part.type == "output_text":
                            text_parts.append(content_part.text)

            if not tool_calls:
                # Model returned a final text response -- done
                reply_text = "\n".join(text_parts).strip()
                # Append the assistant message to the thread
                thread.append({"role": "assistant", "content": reply_text})
                break

            # Dispatch all tool calls and collect results
            tool_result_items: list[dict] = []
            for tc in tool_calls:
                try:
                    args = json.loads(tc.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}

                result = dispatch(tc.name, args, db, settings.clinic_timezone)

                tool_result_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": json.dumps(result),
                    }
                )

            # Append tool calls and their results to the thread for context
            for tc in tool_calls:
                thread.append(
                    {
                        "type": "function_call",
                        "call_id": tc.call_id,
                        "name": tc.name,
                        "arguments": tc.arguments,
                    }
                )
            for tri in tool_result_items:
                thread.append(tri)

            # Rebuild input for next round: system prompt + full thread
            input_messages = [{"role": "system", "content": system_prompt}] + thread

        else:
            # Loop exhausted without a text response
            reply_text = (
                "I'm sorry, I wasn't able to complete your request in time. "
                "Please try again."
            )
            thread.append({"role": "assistant", "content": reply_text})

        # 5. Persist thread only after a successful complete turn -------------
        now_utc_z = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        db.execute(
            "UPDATE CHAT_SESSION "
            "SET thread_history = ?, last_active_at = ? "
            "WHERE session_id = ?",
            (json.dumps(thread), now_utc_z, session_id),
        )

        return reply_text