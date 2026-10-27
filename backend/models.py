"""backend/models.py — Pydantic request/response models."""
import re
from datetime import date, datetime
from pydantic import BaseModel, field_validator

_PHONE_RE = re.compile(r'^\+?[\d\s\-()]{7,20}$')

class PatientDetails(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str   # YYYY-MM-DD
    phone: str

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, v: str, info) -> str:
        v = v.strip()
        if not v:
            raise ValueError(f"{info.field_name} must not be empty")
        if len(v) > 50:
            raise ValueError(f"{info.field_name} must be at most 50 characters")
        return v

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: str) -> str:
        try:
            dob = date.fromisoformat(v)
        except ValueError:
            raise ValueError("date_of_birth must be YYYY-MM-DD")
        if dob <= date(1900, 1, 1):
            raise ValueError("date_of_birth must be after 1900-01-01")
        if dob >= date.today():
            raise ValueError("date_of_birth must be in the past")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        digits = re.sub(r'[\s\-()+ ]', '', v)
        if not digits.isdigit() or not (10 <= len(digits) <= 15):
            raise ValueError("phone must contain 10-15 digits (spaces/hyphens/parens allowed)")
        return v


class ChatRequest(BaseModel):
    session_id: str
    message: str

    @field_validator("session_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id must not be empty")
        return v

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        if len(v) > 2000:
            raise ValueError("message must not exceed 2000 characters")
        return v


class ChatResponse(BaseModel):
    session_id: str
    reply: str