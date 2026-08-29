"""Tool-use agent loop (Phase A.3 — not yet implemented).

Will send session history + the system prompt (prompts.py) + tool
definitions (tools.py) to the Claude API, execute any requested tool calls,
feed `tool_result`s back, and repeat until `stop_reason == "end_turn"` or an
8-tool-call cap is hit. Every tool error will be wrapped as an `is_error`
tool_result so the agent can recover instead of crashing. See PLAN.md
section A.3 for the full spec.
"""
