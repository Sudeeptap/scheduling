"""backend/tools.py — OpenAI tool schemas for the Responses API."""

TOOLS = [
    {
        "type": "function",
        "name": "search_doctor",
        "description": "Search for a doctor by name. Returns up to 20 matching active doctors.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_name": {
                    "type": "string",
                    "description": "Partial or full doctor name to search for"
                }
            },
            "required": ["doctor_name"]
        }
    },
    {
        "type": "function",
        "name": "suggest_specialty",
        "description": (
            "Return all active medical specialties so the model can match them against "
            "the patient's described symptoms. The model selects the best match."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "symptom_description": {
                    "type": "string",
                    "description": "Patient's description of their symptoms or condition"
                }
            },
            "required": ["symptom_description"]
        }
    },
    {
        "type": "function",
        "name": "get_availability",
        "description": (
            "Get available appointment slots for a doctor on a given date. "
            "Returns UTC ISO 8601 slot start times. "
            "Always present times to the patient in the clinic's local timezone."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {
                    "type": "integer",
                    "description": "Doctor ID from search_doctor result"
                },
                "date": {
                    "type": "string",
                    "description": "Date to check in YYYY-MM-DD format (clinic local date)"
                },
                "find_next_available": {
                    "type": "boolean",
                    "description": (
                        "If true, scan forward up to 30 calendar days from the given date "
                        "and return the single earliest available slot"
                    )
                }
            },
            "required": ["doctor_id", "date"]
        }
    },
    {
        "type": "function",
        "name": "book_appointment",
        "description": (
            "Book a confirmed appointment for a patient. "
            "Only call this after the patient has explicitly confirmed the appointment summary. "
            "appointment_datetime must be one of the UTC slots returned by get_availability."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "integer"},
                "appointment_datetime": {
                    "type": "string",
                    "description": "UTC ISO 8601 datetime of the appointment slot (e.g. 2026-10-15T04:30:00Z)"
                },
                "patient": {
                    "type": "object",
                    "description": "Patient details collected and validated during the conversation",
                    "properties": {
                        "first_name": {"type": "string"},
                        "last_name":  {"type": "string"},
                        "date_of_birth": {
                            "type": "string",
                            "description": "YYYY-MM-DD"
                        },
                        "phone": {"type": "string"}
                    },
                    "required": ["first_name", "last_name", "date_of_birth", "phone"]
                }
            },
            "required": ["doctor_id", "appointment_datetime", "patient"]
        }
    },
    
{
    "type": "function",
    "name": "search_doctors_by_specialty",
    "description": (
        "Find active doctors who belong to a specific medical specialty. "
        "Use this when a patient asks which doctors are available for "
        "a specialty such as Dermatology or General Practice."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "specialty_name": {
                "type": "string",
                "description": "The exact medical specialty name to search for"
            }
        },
        "required": ["specialty_name"]
    }
},

]