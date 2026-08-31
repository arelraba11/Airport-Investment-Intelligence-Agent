"""In-memory session store: session_id -> list of chat messages.

Process-local and non-persistent by design — sessions are lost on server
restart. Good enough for a single-process dev/demo backend; would need a
real store (Redis, DB) to survive restarts or scale to multiple workers.
"""

from typing import TypedDict


class Message(TypedDict):
    role: str
    content: str


_sessions: dict[str, list[Message]] = {}


def get_history(session_id: str) -> list[Message]:
    return _sessions.setdefault(session_id, [])


def append_message(session_id: str, role: str, content: str) -> None:
    get_history(session_id).append({"role": role, "content": content})
