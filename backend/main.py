"""FastAPI app: POST /chat and GET /health.

Phase A.1 (Backend Skeleton) only — /chat currently echoes the message back
and stores the exchange in session history. The real tool-use agent loop
(agent.py, Phase A.3) is wired in later.
"""

import csv
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import sessions

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
def health():
    return {"status": "ok", "airports_loaded": _count_airports()}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())

    sessions.append_message(session_id, "user", request.message)
    reply = f"Echo: {request.message}"
    sessions.append_message(session_id, "assistant", reply)

    return ChatResponse(reply=reply, session_id=session_id)
