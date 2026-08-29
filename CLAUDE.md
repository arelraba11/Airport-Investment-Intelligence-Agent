# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Phases A (backend + agent) and B (chat UI) are both complete and checkpointed — see PLAN.md for the
full phase-by-phase build log, intermediate checks, and the formal checkpoint write-ups (including a
consolidated re-verification of the Phase B checkpoint). Only Phase C (DESIGN.md, README.md, clean-clone
verification, polish) remains; `README.md` and `DESIGN.md` are currently empty. Do not restart or
duplicate work already marked done in PLAN.md without a reason — check there first before assuming a
piece of the system doesn't exist yet.

## Commands

```bash
source venv/bin/activate
pip install -r requirements.txt          # backend/data/scoring deps
cp .env.example .env                     # then fill in ANTHROPIC_API_KEY

# Build the unified dataset (must run from data/ — it uses paths relative to raw/)
cd data && python build_dataset.py

# Run backend tests (from repo root)
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_build_dataset.py::test_required_airports_present -v
python -m pytest tests/test_scoring.py::test_bos_outranks_hvn_after_percentile_normalizing_all_components -v

# Run the API (from repo root; requires data/airports_dataset.csv to exist and .env set)
uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install
npm run dev          # Vite dev server on http://localhost:5173, CORS-permitted by the backend
npm run lint          # oxlint
npm run build
```

There is no Python lint/format tooling configured; the frontend has `oxlint` via `npm run lint`.

## Architecture overview

Data pipeline (`data/build_dataset.py`) → unified CSV (`data/airports_dataset.csv`) → deterministic
scoring engine (`scoring/`) → agent tools (`backend/tools.py`, thin wrappers over `scoring/`) → manual
Claude tool-use loop (`backend/agent.py`) behind `POST /chat` (`backend/main.py`) → React chat UI
(`frontend/`). The dividing line that matters most: **every number the agent ever states is computed by
deterministic Python in `scoring/`, never by the LLM** — the LLM's job is tool selection and
natural-language explanation only.

## Data pipeline architecture (`data/build_dataset.py`)

Merges three public data sources into one row-per-airport CSV at `data/airports_dataset.csv`:

- **OurAirports** (`data/raw/airports.csv`, `runways.csv`) — auto-downloaded from
  `davidmegginson/ourairports-data` on GitHub if not already present in `data/raw/`.
- **FAA commercial-service enplanements** — three pre-supplied xlsx workbooks in `data/raw/` covering
  CY22–CY25(prelim), each keyed by `Locid` (IATA code). These files are not modified or re-downloaded.
- **BTS T-100 domestic segment traffic** — a pre-supplied pipe-delimited `.asc` file (~450K rows, 12
  months of data) in `data/raw/`, streamed line-by-line rather than loaded into a DataFrame.

Key design points that aren't obvious from a single function:

- **Scope is a documented, non-arbitrary decision**: top-75 airports nationally by FAA CY24 rank, unioned
  with every New England airport ranked ≤150 (`SCOPE_SIZE`, `NEW_ENGLAND_RANK_CUTOFF` in
  `build_dataset.py`). Top-75 alone leaves only 2 New England airports in scope, which isn't enough to
  answer New England-specific investment questions — the wider NE cutoff exists specifically to fix that,
  while still excluding essential-air-service strips with negligible traffic.
- **IATA code drift**: OurAirports has renamed Palm Beach Intl (`KPBI`) to reflect a new name/IATA code
  (`DJT`), but the FAA files still use the historical `PBI` code. `IATA_ALIASES` maps FAA Locids to
  OurAirports `ident` values as a fallback join key — check this table first if a known airport goes
  missing after an OurAirports data refresh.
- **Runway join is two-hop**: `runways.csv` joins on `airport_ident` (OurAirports' ICAO-style `ident`),
  not on IATA code directly. The pipeline first builds an IATA→`ident` map from `airports.csv`, then joins
  runways through that map (including through `IATA_ALIASES` for the PBI/DJT case).
- **BTS field layout is empirically validated, not just documented**: `BTS_FIELDS` in the script encodes
  the 28-column layout of the undocumented `.asc` format, validated against known real-world great-circle
  distances (e.g. JFK–LAX, BOS–LAX, ANC–SEA) rather than an official schema doc. Only `CLASS == 'F'`
  (scheduled passenger service) rows are aggregated; `L`/`G`/`P` rows are excluded on purpose.
- **`data_completeness`** is `"full"` only when CY22 enplanements, at least one runway, and at least one
  BTS route all resolved for that airport — otherwise `"partial"`. This is a deliberate per-row quality
  flag for downstream consumers, not a filter (all in-scope airports are still written to the CSV).

`tests/test_build_dataset.py` asserts against the *output CSV*, not the pipeline internals — it requires
`data/airports_dataset.csv` to already exist (i.e. `build_dataset.py` must have been run first).

## Scoring engine architecture (`scoring/`)

Pure, deterministic Python — zero LLM calls. `weights.py` (constants), `data_loader.py`
(`load_dataset()` → DataFrame indexed by `iata`), `formulas.py` (one pure function per component,
each returns `float | None`), `scorer.py` (`score_airport`, `rank_airports`, `compare_airports`
orchestration, dataset cached via `lru_cache`). `rank_airports.py` at repo root is a manual
sanity-check CLI, not part of the agent.

Key design points that aren't obvious from a single function:

- **All 4 `investment_score` components are percentile-normalized across the in-scope dataset**
  (`rank(pct=True) * 100`), not just `growth_score`. This was a bug fix, not the original design — a
  regression test pins it (see below). Any new scoring component must be percentile-normalized the same
  way before joining the weighted sum, or it will silently reintroduce that bug.
- **`investment_score()` separates percentile components from human-readable raw values**: the
  `components` dict (0-100 percentiles) is what feeds the weighted sum; a sibling `raw_values` dict
  (`congestion_capacity_utilization_pct`, `growth_cagr_pct`, `longhaul_share_pct`) carries the
  pre-percentile numbers, consumed by the agent layer (`backend/prompts.py` hard rule 5) for
  component-by-component explanations — never used in the score itself.
- **Missing-component handling re-normalizes weights, not the score**: if a component is `None`,
  it's excluded from the weighted sum and the remaining weights are rescaled to sum to 1.0, rather
  than treating the missing component as 0. `confidence` is `"high"` (all 4 components present +
  `data_completeness == "full"`), `"partial"` (≥2 present), or `"insufficient_data"` (<2 present).
- **`unmet_demand_score` is a documented heuristic, not a measured quantity**: `growth*0.6 +
  congestion*0.4`, both already percentile-normalized. No source data has a real "unmet demand"
  field — this exists to give the agent something defensible to point to for "why is demand
  outrunning capacity here" questions.
- **Regions are structured as a lookup table** (`REGIONS` in `weights.py`), not hardcoded into
  `rank_airports()`, so adding a region later doesn't require rewriting the function.

`tests/test_scoring.py` includes a regression test,
`test_bos_outranks_hvn_after_percentile_normalizing_all_components`, that pins the fixed behavior
described above — if it starts failing, don't "fix" it by tuning `WEIGHTS`, treat it as a real
methodology regression.

## Backend + agent architecture (`backend/`)

`main.py` → `agent.py` → `tools.py` → `scoring/`, plus `sessions.py` and `prompts.py`:

- **`main.py`** — FastAPI app. `GET /health` reads the live CSV row count (never hardcoded). `POST /chat`
  takes `{message, session_id?}`, mints a `session_id` (uuid4) if absent, and delegates the entire turn to
  `agent.run_agent_turn`. CORS is locked to `http://localhost:5173` (the Vite dev origin). Only an
  unexpected failure of the Anthropic API call itself propagates as a 500 — every tool-level failure is
  already caught and recovered inside the agent loop.
- **`sessions.py`** — an in-memory `dict[session_id, list[Message]]`, process-local and non-persistent by
  design: session history is lost on backend restart (confirmed behavior, not a bug — a real store like
  Redis/DB would be needed to survive restarts or scale past one worker).
- **`tools.py`** — 6 tools, each returning JSON-serializable data only, never prose:
  `resolve_airport`, `get_airport_profile`, `score_airport`, `rank_airports`, `compare_airports`,
  `get_live_traffic`. The 4 scoring-backed tools are thin passthroughs over `scoring/scorer.py` — no
  scoring logic is reimplemented here. `resolve_airport` matches, in order: exact IATA code → hardcoded
  `ALIASES` table (informal names like "LA", "vegas", short enough that fuzzy matching would be
  unreliable) → exact case-insensitive match against `CITY_BY_IATA`/`name` → fuzzy match
  (`difflib.SequenceMatcher`, `_FUZZY_MIN_RATIO`/`_FUZZY_CONFIDENCE_MARGIN` tune confident-match vs.
  ambiguous-match), returning `{ambiguous: true, candidates: [...]}` for a real collision (e.g. "Portland"
  → PDX vs. PWM) or `{not_found: true, in_scope: false}` for nothing plausible. `CITY_BY_IATA` is a
  hand-built table (the dataset has no `city` column) alongside `ALIASES` — a third hardcoded special-case
  table beyond the two already noted in "Locked-in decisions" below. `get_live_traffic` queries OpenSky
  for a bounding box around the airport's lat/lon (5s timeout, 10-minute in-memory cache per IATA code)
  and never raises — any failure degrades to `{available: false, note: "live data unavailable"}`.
- **`agent.py`** — the manual tool-use loop (`run_agent_turn`), deliberately not using the Anthropic Tool
  Runner beta or any agent framework. Sends session history + `SYSTEM_PROMPT` + the 6 tool JSON-schema
  defs to `client.messages.create`; on `stop_reason == "tool_use"`, executes every returned tool_use block
  (each wrapped in `_execute_tool`, which catches `AirportNotFoundError`/`ValueError`/`TypeError`/anything
  else and turns it into an `is_error: true` tool_result rather than raising), appends results, and loops.
  Stops on `stop_reason != "tool_use"` or after `MAX_TOOL_CALLS = 8` total tool calls in one turn (the
  pending tool_use blocks get a synthetic error tool_result so history stays API-valid, then a
  user-visible "hit my limit" message is returned without another API call). `messages =
  sessions.get_history(session_id)` is the same list object backing the session store, so every
  `tool_use`/`tool_result`/final-text append during the loop persists automatically — follow-up turns see
  full prior context, not just user-facing text.
- **`prompts.py`** — `SYSTEM_PROMPT`, the only place agent behavior is tuned (no code changes needed to
  adjust tone/rules). Hard rules worth knowing before changing tool behavior: never state a number without
  a tool call; ask rather than guess on `ambiguous` resolver results; state scope boundaries explicitly on
  `not_found`/`in_scope: false`; always surface the three documented assumptions (230K/runway/year
  capacity, 2,500-mile long-haul threshold, unmet-demand formula) inline whenever their component is
  discussed; explain scores component-by-component using `raw_values`; decline off-topic requests without
  engaging them.

## Frontend architecture (`frontend/`)

Vite + React (plain JS, no TypeScript). `App.jsx` owns all state: `messages[]` (`role` is `'user' |
'assistant' | 'error'`), `isLoading`, and `sessionId` (minted once via `crypto.randomUUID()` and
overwritten from the backend's response — the frontend never generates a session_id the backend has to
use, it just seeds the first request). `isSendingRef` is a synchronous guard against double-send races
that `isLoading` state alone wouldn't catch (React state updates aren't synchronous).

- **`components/MessageList.jsx`** — renders bubbles per role (`error` reuses the same `message {role}`
  class pattern for styling), renders assistant content through `react-markdown` + `remark-gfm` (needed
  because `compare_airports`-style replies use Markdown pipe tables), and auto-scrolls via a `bottomRef`
  sentinel + `useEffect` keyed on `[messages, isLoading]`.
- **`components/MessageInput.jsx`** — a `<textarea rows={1}>` (not `<input>`, to support Shift+Enter for
  newlines) that auto-grows up to `max-height:150px`; plain Enter submits, Shift+Enter inserts a newline.
- **`components/AssumptionsPanel.jsx`** — collapsible (`useState(true)`, expanded by default), rendering
  the same 3 assumptions the system prompt is instructed to surface, so the UI and the agent's own text
  never disagree on what's assumed vs. measured.
- **`components/SuggestedQuestions.jsx`** — the 4 assignment example questions as chips, shown only when
  `messages.length === 0` (chosen over "always visible" as the simpler of the two options considered).

`handleSend` in `App.jsx` is the only place that talks to the backend (`fetch` to
`http://localhost:8000/chat`, hardcoded — no env-based URL config exists). Any non-2xx or network failure
is caught and appended as an `error`-role message instead of throwing, and `isLoading`/`isSendingRef` are
always reset in a `finally` block — the input is never left stuck disabled after a failed request, and
recovery needs no page reload once the backend comes back.

## Assignment context

This project is a take-home exercise for a Forward Deployed Engineer role (Deloitte Digital). The brief:

> Build an AI agent that helps an airport-modernization investment firm identify which US airports are
> strong candidates for terminal/capacity expansion, based on flight and passenger capacity growth.

Four example questions the agent must answer well (used verbatim as the frontend's suggested-question
chips, and as the required end-to-end test set in PLAN.md):
1. Which airports in New England are strong candidates for terminal expansion?
2. Compare LA and Santa Ana airport congestion levels.
3. What is the percentage of long-haul flights out of Anchorage airport?
4. What is the unmet flight demand in SFO airport and why?

Hard requirements: (a) deterministic scoring/ranking logic, not LLM-invented numbers, (b) a chat interface
supporting follow-up questions, (c) explicit communication of assumptions/uncertainty/scope. Deliverables:
source code + a short DESIGN.md covering scoring methodology, key tradeoffs, and where/how AI is used.
Explicitly de-prioritize completeness/polish in favor of clear, well-reasoned, well-scoped work.

## Locked-in decisions (do not silently change without flagging it)

- **Scope**: top-75 US airports nationally by FAA CY24 enplanement rank, ∪ every New England airport
  ranked ≤150 nationally (see "Data pipeline architecture" above for why).
- **Score weights** (`scoring/weights.py`): congestion 35%, growth 25%, longhaul_mix 15%, unmet_demand
  25%. `unmet_demand_score = growth*0.6 + congestion*0.4` (a documented heuristic, not a measured
  quantity — there's no real "unmet demand" field in any source). All 4 components must be
  percentile-normalized before combining (see "Scoring engine architecture" above) — combining a raw
  and a percentile-normalized value re-breaks the weights.
- **Long-haul threshold**: ≥2500 miles (great-circle), applied when building `longhaul_share_pct` in the
  data pipeline, not re-derived in scoring.
- **`RUNWAY_CAPACITY_PER_YEAR = 230,000`** movements/runway/year — a rough, low-confidence industry-proxy
  assumption, not a measured figure. Must be called out explicitly in DESIGN.md.
- **No agent framework** (no LangChain/LangGraph/etc., no Anthropic Tool Runner beta) — a custom Claude
  API tool-use loop (`backend/agent.py`), chosen deliberately so the mechanics are fully transparent and
  explainable in the design doc, and to avoid extra dependencies under time pressure. Worth a paragraph in
  DESIGN.md's tradeoffs section.
- **Stack**: Python + FastAPI backend, React + Vite frontend (plain JS, not TypeScript), flat CSV (not a
  DB) for the dataset, in-memory (not persistent) session store — all chosen for build speed within a
  short take-home window, not as production recommendations.
- **Model**: `claude-sonnet-5` (`backend/agent.py` `MODEL` constant).
- **`IATA_ALIASES`** (data pipeline, `{"PBI": "KPBI"}`), the New England state list (`ME, NH, VT, MA, RI,
  CT`), and `backend/tools.py`'s `ALIASES`/`CITY_BY_IATA` tables are the hardcoded "special case" tables
  in the codebase — check these first if a new region, a renamed/reclassified airport, or an
  unrecognized informal airport reference causes unexpected behavior.
