"""FastAPI app: POST /chat and GET /health.

/chat runs the full tool-use agent loop (agent.py, Phase A.3) over the
session's message history. Any exception raised by the Anthropic API call
itself (as opposed to a tool call, which agent.py already catches and
recovers from) propagates here as a 500 — that's an unexpected failure,
not a normal conversational path.
"""

import csv
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.agent import run_agent_turn

DATASET_PATH = Path(__file__).resolve().parent.parent / "data" / "airports_dataset.csv"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
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

    reply = run_agent_turn(session_id, request.message)

    return ChatResponse(reply=reply, session_id=session_id)
