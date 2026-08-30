"""FastAPI app: POST /chat and GET /health.

/chat runs the full tool-use agent loop (agent.py, Phase A.3) over the
session's message history. Any exception raised by the Anthropic API call
itself (as opposed to a tool call, which agent.py already catches and
recovers from) is an unexpected failure, not a normal conversational path —
it is returned as an explicit JSON 500 (with the traceback logged) rather
than left to propagate, because a raised exception would bypass the CORS
middleware and reach the browser as an unreadable opaque failure instead
of a distinguishable server error.
"""

import csv
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.agent import run_agent_turn

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "airports_dataset.csv"

# The Vite dev server origin — the only origin needed for local development,
# so the app runs unconfigured out of the box.
DEFAULT_CORS_ORIGINS = "http://localhost:5173"


def _cors_origins() -> list[str]:
    """Browser origins allowed to call this API, from $CORS_ORIGINS.

    Comma-separated, e.g. "http://localhost:5173,http://192.168.1.50:5173".
    Falls back to the Vite dev origin when unset or blank. Reads the
    environment directly rather than loading dotenv again: importing
    backend.agent above already ran load_dotenv(), which is what puts a
    root .env into os.environ before this is called.
    """
    raw = os.getenv("CORS_ORIGINS") or DEFAULT_CORS_ORIGINS
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    # A value that parses to nothing (blank, or just commas/spaces) would
    # otherwise allow no origin at all — fall back rather than silently
    # breaking every browser request.
    return origins or [DEFAULT_CORS_ORIGINS]


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


def _count_airports() -> int:
    with open(DATASET_PATH, newline="") as f:
        return sum(1 for _ in csv.DictReader(f))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "airports_loaded": _count_airports()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid.uuid4())

    try:
        reply = run_agent_turn(session_id, request.message)
    except Exception:
        # See module docstring: return the 500 explicitly so it passes
        # through the CORS middleware and the browser can read the status.
        logging.getLogger("uvicorn.error").exception("Agent turn failed")
        return JSONResponse(
            status_code=500,
            content={"detail": "Agent request failed — see server logs."},
        )

    return ChatResponse(reply=reply, session_id=session_id)
