"""
backend/main.py -- FastAPI application entry point  (Task 10)

Startup order:
  1. Import settings (triggers env-var validation; exits if invalid)
  2. Lifespan handler calls init_db() before first request
  3. POST /chat validates ChatRequest, runs ConversationService, returns ChatResponse

Run with:
    uvicorn backend.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

# Import settings first -- exits process if OPENAI_API_KEY or CLINIC_TIMEZONE invalid
from backend.config import settings  # noqa: F401 (side-effect import required by design)
from backend.conversation import ConversationService
from backend.database import get_db, init_db
from backend.models import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: initialise DB schema before serving requests
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = get_db()
    try:
        init_db(db)
        logger.info("Database initialised at %s", settings.database_url)
    finally:
        db.close()
    yield


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="Doctor's Assistant", version="1.0.0", lifespan=lifespan)

# CORS: allow the Vite dev server (port 5173) and any localhost origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """Handle one patient message and return the assistant reply."""
    db = get_db()
    try:
        svc = ConversationService(db)
        reply = svc.handle_turn(body.session_id, body.message)
        return ChatResponse(session_id=body.session_id, reply=reply)
    except openai.OpenAIError as exc:
        logger.error("OpenAI API error for session %s: %s", body.session_id, exc)
        raise  # re-raised; caught by the generic handler below and mapped to 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(ValidationError)
async def _validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    """Pydantic body-validation failures -> HTTP 400 with field details."""
    fields = [
        {"field": ".".join(str(loc) for loc in e["loc"]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": fields})


@app.exception_handler(Exception)
async def _generic_error(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled errors -> HTTP 500, no internal details exposed."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )