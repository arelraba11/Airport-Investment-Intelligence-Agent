"""Request-validation tests for the /chat request body.

These exercise the ChatRequest model directly rather than going through an
HTTP client: FastAPI's TestClient needs httpx, which isn't a dependency of
this project, and the model is where the validation actually lives. A
ValidationError here is exactly what FastAPI turns into a structured 422.
"""

import pytest
from pydantic import ValidationError

from backend.main import ChatRequest


def test_chat_request_rejects_empty_message():
    """An empty message used to reach the Anthropic API and come back as an
    opaque 500 ("user messages must have non-empty content"). It must be
    rejected at the request boundary instead, as a 422."""
    with pytest.raises(ValidationError):
        ChatRequest(message="")


@pytest.mark.parametrize("blank", ["   ", "\t", "\n", " \t\n "])
def test_chat_request_rejects_whitespace_only_message(blank):
    """Whitespace-only input is just as empty to the API as "" is."""
    with pytest.raises(ValidationError):
        ChatRequest(message=blank)


def test_chat_request_keeps_message_with_surrounding_whitespace():
    """Only fully-blank input is rejected. A padded but real message must be
    accepted *and* passed through unchanged — the validator rejects, it does
    not rewrite what the user sent."""
    padded = "  What is BOS's score?  "
    assert ChatRequest(message=padded).message == padded


def test_chat_request_still_requires_message_field():
    """No regression: a body with no "message" key at all is still invalid,
    the same way it was before blank-message validation was added."""
    with pytest.raises(ValidationError):
        ChatRequest(session_id="abc")
