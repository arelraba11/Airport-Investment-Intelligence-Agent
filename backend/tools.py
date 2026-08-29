"""Agent tool definitions and implementations (Phase A.2 — not yet implemented).

Will hold the 6 tools the agent calls, each returning JSON only, never free
text: resolve_airport, get_airport_profile, score_airport, rank_airports,
compare_airports, get_live_traffic. Tools wrapping existing Day 1 code
(get_airport_profile, score_airport, rank_airports, compare_airports) are
thin passthroughs over scoring/ — no new logic inside them. See PLAN.md
section A.2 for the full spec.
"""
