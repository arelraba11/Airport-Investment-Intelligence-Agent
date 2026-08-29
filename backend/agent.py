"""Tool-use agent loop (Phase A.3).

Sends session history + the system prompt (prompts.py) + tool definitions
(TOOLS below, wrapping the 6 functions in tools.py) to the Claude API,
executes any requested tool calls, feeds tool_results back, and repeats
until stop_reason == "end_turn" or MAX_TOOL_CALLS total tool calls have run
in this turn. Every tool error is wrapped as an is_error tool_result so the
agent can recover instead of the whole request crashing — only an
unexpected failure of the Anthropic API call itself propagates, to be
turned into a 500 by main.py.
"""

import json

import anthropic
from anthropic.types import ContentBlock
from dotenv import load_dotenv

from backend import sessions
from backend import tools as tool_impls
from backend.prompts import SYSTEM_PROMPT
from scoring.scorer import AirportNotFoundError

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096
MAX_TOOL_CALLS = 8

client = anthropic.Anthropic()

TOOLS = [
    {
        "name": "resolve_airport",
        "description": (
            "Resolve a free-text airport reference (city name, airport name, or informal "
            "alias like 'LA', 'Vegas', 'Santa Ana') to an in-scope IATA code. Call this "
            "FIRST whenever the user refers to an airport by anything other than an exact "
            "3-letter IATA code, before calling any other airport tool. Returns either a "
            "single confident match ({iata, name, city}), an ambiguous result "
            "({ambiguous: true, candidates: [...]}) that you must ask the user to "
            "disambiguate rather than guessing, or a not-found result "
            "({not_found: true, in_scope: false}) meaning the airport is outside the "
            "80-airport in-scope dataset."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text airport reference, e.g. 'Boston', 'LA', 'Anchorage', or an IATA code like 'BOS'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_airport_profile",
        "description": (
            "Get the raw dataset row for a single in-scope airport by IATA code: "
            "enplanements, runway count, flight counts, state, and other source fields. "
            "Use this for factual/data questions about a specific airport that don't "
            "require a computed investment score. Use resolve_airport first if you don't "
            "already have a confirmed IATA code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iata": {"type": "string", "description": "3-letter IATA airport code, e.g. 'BOS'."}
            },
            "required": ["iata"],
        },
    },
    {
        "name": "score_airport",
        "description": (
            "Compute the deterministic investment_score (0-100) for a single in-scope "
            "airport, broken into its 4 percentile-normalized components (congestion, "
            "growth, longhaul_mix, unmet_demand) plus raw_values (capacity utilization %, "
            "growth CAGR %, long-haul share %) for plain-language explanation. This is the "
            "ONLY authoritative source for an investment score — never estimate or invent "
            "one yourself. Use resolve_airport first if you don't already have a confirmed "
            "IATA code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iata": {"type": "string", "description": "3-letter IATA airport code, e.g. 'BOS'."}
            },
            "required": ["iata"],
        },
    },
    {
        "name": "rank_airports",
        "description": (
            "Rank in-scope airports by investment_score, either within a named region "
            "(e.g. 'New England'), across an explicit list of IATA codes, or across all "
            "80 in-scope airports if neither is given. Use this for 'which airports are "
            "strong candidates' or 'top N' style questions rather than calling "
            "score_airport repeatedly yourself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "string",
                    "description": "Optional region name, e.g. 'New England'. Case/spacing-insensitive.",
                },
                "iata_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional explicit list of IATA codes to rank instead of a region.",
                },
                "top_n": {
                    "type": "integer",
                    "description": "Maximum number of airports to return. Defaults to 10.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "compare_airports",
        "description": (
            "Directly compare 2 or more specific in-scope airports side by side: overall "
            "score, all 4 component breakdowns, and raw values for each. Use this for "
            "'compare X and Y' style questions rather than calling score_airport "
            "separately for each airport."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iata_list": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of 2 or more IATA codes to compare.",
                }
            },
            "required": ["iata_list"],
        },
    },
    {
        "name": "get_live_traffic",
        "description": (
            "Best-effort LIVE aircraft count currently near an airport, from the OpenSky "
            "Network — not historical FAA/BTS data, and not part of the deterministic "
            "score. May return {available: false} if live data can't be fetched right now; "
            "treat that as a graceful degradation and tell the user live data is currently "
            "unavailable rather than treating it as an error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iata": {"type": "string", "description": "3-letter IATA airport code."}
            },
            "required": ["iata"],
        },
    },
]

TOOL_FUNCTIONS = {
    "resolve_airport": tool_impls.resolve_airport,
    "get_airport_profile": tool_impls.get_airport_profile,
    "score_airport": tool_impls.score_airport,
    "rank_airports": tool_impls.rank_airports,
    "compare_airports": tool_impls.compare_airports,
    "get_live_traffic": tool_impls.get_live_traffic,
}


def _execute_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """Run a tool by name. Returns (content_str, is_error) — never raises."""
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return f"Unknown tool: {name!r}", True
    try:
        result = func(**tool_input)
        return json.dumps(result), False
    except (AirportNotFoundError, ValueError, TypeError) as exc:
        return f"Error calling {name}: {exc}", True
    except Exception as exc:  # noqa: BLE001 — deliberately broad: any tool failure must not crash the turn
        return f"Unexpected error calling {name}: {exc}", True


def _extract_text(content_blocks: list[ContentBlock]) -> str:
    """Concatenate the text of every text block, ignoring tool_use/other block types."""
    return "".join(block.text for block in content_blocks if block.type == "text")


def run_agent_turn(session_id: str, user_message: str) -> str:
    """Run one full user turn: append the message, loop tool calls, return the reply text.

    The session's message history (backend.sessions) is mutated in place as the
    Claude API's own message list, so follow-up turns on the same session_id
    carry full context (including prior tool_use/tool_result blocks), not just
    user-facing text.
    """
    sessions.append_message(session_id, "user", user_message)
    messages = sessions.get_history(session_id)  # same list object — mutations persist

    tool_calls_used = 0

    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            reply = _extract_text(response.content)
            messages.append({"role": "assistant", "content": response.content})
            return reply

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})

        if tool_calls_used + len(tool_use_blocks) > MAX_TOOL_CALLS:
            # Resolve the pending tool_use blocks so history stays valid for the
            # next turn, then stop without calling the API again.
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": b.id,
                            "content": "Tool-call limit reached for this turn.",
                            "is_error": True,
                        }
                        for b in tool_use_blocks
                    ],
                }
            )
            limit_message = (
                f"I hit my limit of {MAX_TOOL_CALLS} tool calls for this turn before I could "
                "finish answering. Could you narrow the question (e.g. ask about fewer "
                "airports at once, or ask a more specific follow-up)?"
            )
            messages.append({"role": "assistant", "content": limit_message})
            return limit_message

        tool_results = []
        for block in tool_use_blocks:
            content_str, is_error = _execute_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content_str,
                    "is_error": is_error,
                }
            )
        tool_calls_used += len(tool_use_blocks)

        messages.append({"role": "user", "content": tool_results})
