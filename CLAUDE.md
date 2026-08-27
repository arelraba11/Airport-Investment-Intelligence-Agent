# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is an early-stage "Airport Investment Intelligence Agent." The data pipeline
(`data/build_dataset.py`, "Day 1 AM") and the deterministic scoring engine (`scoring/` +
`rank_airports.py`, "Day 1 PM") both exist and are tested. `README.md` and `DESIGN.md` are present but
empty. `requirements.txt` includes `fastapi`, `uvicorn`, `anthropic`, and `python-dotenv` in addition to
the data/scoring deps (`pandas`, `openpyxl`, `pytest`), signalling that a FastAPI service backed by the
Anthropic API is the intended next layer on top of the scoring engine — but no such code exists yet.

## Commands

```bash
source venv/bin/activate
pip install -r requirements.txt

# Build the unified dataset (must run from data/ — it uses paths relative to raw/)
cd data && python build_dataset.py

# Run tests (from repo root)
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_build_dataset.py::test_required_airports_present -v
```

There is no lint/format tooling configured in this repo.

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
  (`rank(pct=True) * 100`), not just `growth_score`. This was a bug fix, not the original design —
  see "Progress log" below. Any new scoring component must be percentile-normalized the same way
  before joining the weighted sum, or it will silently reintroduce that bug.
- **`investment_score()` separates percentile components from human-readable raw values**: the
  `components` dict (0-100 percentiles) is what feeds the weighted sum; a sibling `raw_values` dict
  (`congestion_capacity_utilization_pct`, `growth_cagr_pct`, `longhaul_share_pct`) carries the
  pre-percentile numbers for the agent layer to use in plain-language explanations later — it is
  never used in the score itself.
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

## Assignment context

This project is a take-home exercise for a Forward Deployed Engineer role (Deloitte Digital). The brief:

> Build an AI agent that helps an airport-modernization investment firm identify which US airports are
> strong candidates for terminal/capacity expansion, based on flight and passenger capacity growth.

Four example questions the agent must answer well:
1. Which airports in New England are strong candidates for terminal expansion?
2. Compare LA and Santa Ana airport congestion levels.
3. What is the percentage of long-haul flights out of Anchorage airport?
4. What is the unmet flight demand in SFO airport and why?

Hard requirements: (a) deterministic scoring/ranking logic, not LLM-invented numbers, (b) a chat interface
supporting follow-up questions, (c) explicit communication of assumptions/uncertainty/scope. Deliverables:
source code + a short DESIGN.md covering scoring methodology, key tradeoffs, and where/how AI is used.
Explicitly de-prioritize completeness/polish in favor of clear, well-reasoned, well-scoped work.

## 4-day work plan

- **Day 1 AM — data pipeline.** ✅ DONE. See "Data pipeline architecture" above.
- **Day 1 PM — deterministic scoring engine (`scoring/`).** ✅ DONE. See "Scoring engine architecture"
  and "Progress log" below.
- **Day 2 — agent + API.** Not started. FastAPI backend, Claude API tool-use loop (custom, no agent
  framework — deliberate choice, see "Locked-in decisions"), tools wrapping `scoring/` functions
  (`get_airport_profile`, `score_airport`, `rank_airports`, `compare_airports`, `get_longhaul_stats`,
  `get_live_traffic` via OpenSky, `resolve_airport` for free-text like "LA" → LAX), in-memory session
  state for conversational follow-ups.
- **Day 3 — chat UI.** Not started. React + Vite, single chat screen, visually distinct
  "assumptions/uncertainty" callouts in responses, voice as a strict 2-hour-timeboxed bonus only.
- **Day 4 — DESIGN.md + polish.** Not started. Scoring methodology, key tradeoffs, where/how AI is used,
  known limitations, README with clean-clone instructions, final sanity pass on all 4 example questions.

Guiding principles carried through every day: clarity over completeness; every score comes from
deterministic code, never invented by the LLM; every assumption gets documented in code *and* in
DESIGN.md; no unplanned features mid-build — park ideas instead of chasing them.

## Progress log

**Day 1 AM (done, committed as "Day 1 AM: unified airport dataset"):**
`data/build_dataset.py` built and validated — 80 airports, 100% `data_completeness == "full"`,
`tests/test_build_dataset.py` (5 tests) passing. BTS field layout empirically validated against 3 known
real-world routes before trusting it.

**Day 1 PM (done, committed as "Day 1 PM: deterministic scoring engine + percentile-normalization fix"):**
Built `scoring/` (weights.py, data_loader.py, formulas.py, scorer.py) + `rank_airports.py` CLI +
`tests/test_scoring.py` (16 tests, all passing; full suite 21/21) via TDD. Manual sanity-check surfaced
and fixed a real methodology bug: `congestion_score` and `longhaul_mix_score` now percentile-normalize
their raw values across the scope, same as `growth_score` already did — previously their much narrower
natural spread let `growth` dominate the weighted sum regardless of assigned weight. Regression test
`test_bos_outranks_hvn_after_percentile_normalizing_all_components` passes against the real
implementation. `score_airport()` now also returns a `raw_values` dict (capacity utilization %, CAGR %,
longhaul share %) for human-readable explanations later — not used in the weighted sum itself. New
England ranking now: BOS(72.8) > PVD(57.1) > HVN(45.7)=PWM(45.7) > BDL(41.4) > BTV(18.2) > MHT(6.6).

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
- **No agent framework** (no LangChain/LangGraph/etc.) — a custom Claude API tool-use loop, chosen
  deliberately so the mechanics are fully transparent and explainable in the design doc, and to avoid
  extra dependencies under time pressure. Worth a paragraph in DESIGN.md's tradeoffs section.
- **Stack**: Python + FastAPI backend, React + Vite frontend, flat CSV (not a DB) for the dataset —
  chosen for one-day build speed, not as a production recommendation.
- **IATA_ALIASES** (`{"PBI": "KPBI"}`) and the New England state list (`ME, NH, VT, MA, RI, CT`) are the
  only two hardcoded "special case" tables in the codebase — check both first if a new region or a
  renamed/reclassified airport causes unexpected behavior.