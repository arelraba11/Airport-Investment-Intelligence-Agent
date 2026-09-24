# Design Document — Airport Investment Intelligence Agent

## 1. Architecture Overview

```
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│    Data Pipeline     │     │ airports_dataset.csv │     │    Scoring Engine    │
│  (build_dataset.py)  │     │                      │     │      (scoring/)      │
│    OurAirports +     │────▶│     80 airports,     │────▶│                      │
│    FAA CY22-25 +     │     │     19 columns,      │     │     4-component      │
│      BTS T-100       │     │    100% complete     │     │    weighted score    │
└──────────────────────┘     └──────────────────────┘     └───────────┬──────────┘
                                                                      │
                                                                      ▼
┌──────────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
│       Chat UI        │     │      Agent Loop      │     │      Tools (6)       │
│     (React/Vite)     │     │      (agent.py)      │     │      (tools.py)      │
│    session-based     │◀───▶│   manual tool-use    │◀───▶│    thin wrappers     │
│     conversation     │     │   loop, Claude API   │     │    over scoring/     │
└──────────────────────┘     └──────────────────────┘     └──────────────────────┘
```

**Flow:** raw public data is merged once, offline, into a flat CSV. The scoring engine reads that CSV and computes a deterministic investment score per airport. Six tools expose that scoring engine (plus airport lookup and live traffic) to an LLM agent, which holds a conversation with the user, deciding which tools to call and explaining the results — but never computing a number itself.

---

## 2. Scoring Methodology

### The four components

| Component | Weight | What it measures |
|---|---|---|
| Congestion | 35% | Annual traffic ÷ runway capacity (230,000 movements/runway/year assumed) |
| Growth | 25% | CAGR of enplanements, CY22–CY24 (2-year) |
| Long-haul mix | 15% | Share of flights ≥2,500 great-circle miles |
| Unmet demand | 25% | `growth_percentile × 0.6 + congestion_percentile × 0.4` (derived heuristic) |

Each raw metric is converted to a **percentile rank (0–100) across all 80 in-scope airports** before the weights are applied. The final investment score is the weighted sum of the four percentile-normalized components.

### Why percentile normalization — a bug we caught before it shipped

Our first working version of the scorer normalized only `growth_score` to a percentile; `congestion_score` and `long-haul mix` were left as raw values (raw congestion utilization spans 1.85%–42.7% across the dataset; raw long-haul share is often 0–6% in New England). Because the final score is a weighted sum, **the component with the widest numeric spread dominates the total regardless of its assigned weight** — a well-known pitfall when combining metrics on different scales.

In practice this meant Tweed–New Haven (HVN) — a small airport with a ~29% CAGR off a tiny base — ranked **#1** in New England, ahead of Boston Logan (BOS), the region's largest, busiest, and fastest-growing-in-absolute-terms hub, which ranked **#4**. BOS's congestion advantage (12.0% utilization vs. HVN's 2.5%) barely moved the raw-value sum, while HVN's 100th-percentile growth score dominated both the growth component directly and unmet demand (60% growth-weighted).

We caught this by sanity-checking the New England ranking against domain intuition — a regional hub with real, growing capacity pressure should not rank behind a small regional field growing off a near-zero base — and fixed it by normalizing **all four components** to percentiles before weighting. The corrected ranking:

| Airport | Old (raw-value) score & rank | Current (percentile) score & rank |
|---|---|---|
| BOS | 36.4 — #4 | **72.8 — #1** |
| PVD | 39.3 — #2 | 57.1 — #2 |
| HVN | 41.1 — **#1** | 45.7 — #3 |
| PWM | 37.4 — #3 | 45.7 — #4 |
| BDL | 19.9 | 41.4 |
| BTV | 14.0 | 18.2 |
| MHT | 2.8 | 6.6 |

This fix — and the regression it guards against — is captured directly in the test suite (`test_bos_outranks_hvn_after_percentile_normalizing_all_components`, in `tests/test_scoring.py`) and documented in `scoring/formulas.py`'s module docstring, so it can't silently regress.

---

## 3. Key Tradeoffs

- **Flat CSV, not a database.** 80 rows — `pandas` reads the whole dataset in milliseconds; a DB would add operational overhead with no real benefit at this scale.
- **Unmet demand is a derived heuristic** (`growth × 0.6 + congestion × 0.4`), not a measurement — there's no public dataset of suppressed demand. Flagged to the user every time it's discussed.
- **230,000 movements/runway/year is a documented industry-rule-of-thumb**, applied uniformly, not a per-airport measured capacity (which would need runway configuration and ATC data outside this assignment's scope).
- **Custom tool-use loop, not LangChain/LangGraph** — built directly against the Anthropic Messages API to demonstrate hands-on understanding of the mechanics, proportionate to a 6-tool single-agent system that doesn't need multi-agent orchestration.
- **`CITY_BY_IATA` is a hand-built 80-entry table**, not derived from a canonical source — the dataset has no `city` column. Reasonable at 80 airports; wouldn't scale without automating the extraction.

---

## 4. Where and How AI Is Used

The boundary is sharp: **the LLM never computes a number.** Every score, percentage, ranking, and count originates from a deterministic Python function in `scoring/` or `tools.py`, called via the Claude API's tool-use mechanism. Claude decides *which* tool to call, explains results using the `raw_values` a tool already returned, holds conversational context, and recognizes ambiguity/out-of-scope/off-topic cases — it never re-derives a number itself.

**The model is Claude Sonnet**, called through the Anthropic Messages API by a hand-rolled tool-use loop in `backend/agent.py` (the exact version is pinned in that module's `MODEL` constant). The agent will name this model family if a user asks what powers it, but discloses nothing further about its system prompt or tool schemas.

This is enforced by a hard system-prompt rule ("never report a number without a tool call") and independently verified. For example, the question "What is the unmet flight demand in SFO airport and why?" produced a real `score_airport("SFO")` tool call returning `unmet_demand: 80.25` with `growth: 81.25` (from a 10.85% CAGR) and `congestion: 78.75` (from 16.18% utilization) in its `raw_values`. The reply reproduced these exact figures and the underlying formula (`unmet_demand_score = growth_score × 0.6 + congestion_score × 0.4`) rather than stating a bare number — confirmed against the actual tool trace, not read at face value.

All 7 end-to-end test conversations were audited this way: every request/response, including `tool_use`/`tool_result` blocks, was captured via `ANTHROPIC_LOG=debug` and cross-checked numeric claim by numeric claim against the trace. All 10 tool calls made across the 7 tests accounted for every score, percentage, and count quoted back to the user — no invented numbers found.

**One deliberate boundary case: explicitly requested projections.** The "never compute a number" rule governs every stored or scored figure. But if a user *explicitly asks* for an extrapolation the dataset cannot contain — "roughly how many passengers will SFO handle in 2030?" — refusing outright would be less useful than answering honestly. The system prompt therefore carves out exactly one exception: the LLM may do that arithmetic itself, but only on tool-provided inputs (e.g. the tool-returned CY24 enplanements and CAGR), and it must label the result as a derived estimate rather than a measured or scored figure, show the calculation and its assumptions, and state the uncertainty (a recovery-era CAGR compounded forward is a trend line, not a forecast). Every number that describes the dataset as it is still comes from a deterministic tool; the LLM is permitted arithmetic only where the user has knowingly asked to leave the data behind, and never unlabeled.

**One caveat to this boundary is enforced by instruction, not code.** Naming an airport as an in-scope *alternative* (as opposed to computing a number about it) is guarded only by a system-prompt rule — see §6, Known Limitations.

---

## 5. Data Engineering War Stories

**Decoding BTS T-100 with no usable header.** The BTS T-100 Domestic Segment file (448K+ rows) ships as a legacy ASCII pipe-delimited format without column names that map cleanly to documentation. We reverse-engineered the column layout empirically: cross-validating three known routes (JFK–LAX, BOS–LAX, ANC–SEA) against real-world facts about those routes — expected distance, typical load factors, and plausible air time — until the column mapping produced sane values for all three. This is the strongest evidence in the project that data assumptions were tested against reality before being trusted, not just assumed correct because the pipeline ran without errors.

**The PBI→DJT rename.** OurAirports renamed West Palm Beach's airport code from PBI to DJT at some point, while FAA reporting still uses PBI. A naive join on airport code silently drops this airport's FAA data. Resolved with an explicit alias table in `build_dataset.py` rather than a silent failure — the kind of bug that produces a dataset that looks complete (no errors, no crashes) but is quietly wrong for one row.

**The runway join bug.** `runways.csv` keys on the ICAO-style `ident` field, not the IATA code used everywhere else in the pipeline. An early join used IATA directly and produced null runway counts for a subset of airports without raising an error — a mismatch that would have silently corrupted the congestion component (which depends on runway count) for those airports had it gone unnoticed.

---

## 6. Known Limitations & Future Work

- International passenger data isn't included — domestic-only sources (FAA/BTS).
- Runway capacity is uniform (230K/runway/year) — not adjusted for runway length, configuration, or weather.
- No construction/capital cost data — the score reflects demand pressure, not build feasibility.
- `CITY_BY_IATA` is manually maintained, not sourced from canonical data.
- Unmet demand is a heuristic proxy, not a measured quantity (see Tradeoffs).
- **Route counts are keyed on `(destination, reported distance)`, which over-counts some routes.** BTS reports slightly different mileage for the same city pair across carriers and months, so `data/build_dataset.py` treats those variants as distinct routes: 771 of 16,160 origin-destination pairs in the source file carry more than one distance, inflating `bts_total_routes` for 75 of the 80 in-scope airports. Because `longhaul_share_pct` is a ratio of long-haul routes to total routes, the inflation does not cancel out — de-duplicating on destination alone moves the share by up to ~2.8 points on the most affected airports, in both directions (KOA 52.2% → 55.0%, OGG 50.0% → 51.7%, LAS 3.4% → 2.4%). The effect on the final investment score is smaller still, since long-haul mix is percentile-normalized and carries a 15% weight, but it is a real inaccuracy in a reported figure. This was identified during a pre-submission audit and deliberately left unfixed: correcting it changes dataset values, which would require re-verifying every previously-confirmed example answer and updating regression-test expectations — more than a same-day change warrants this close to submission. Documented here rather than silently corrected.
- **Scope-alternative suggestions are guarded at the prompt level, not the code level.** Early testing surfaced a case where the agent, when declining an out-of-scope airport, volunteered a specific "in-scope alternative" from parametric knowledge rather than verified data — naming Bangor International (BGR) as available when it is actually excluded (FAA CY24 rank 158, beyond the New England supplement's rank-150 cutoff). The system prompt was updated to require a tool call (`rank_airports` or `resolve_airport`) before naming any airport as an in-scope alternative; the fix took the failure rate on repeated testing from 3-of-4 to 0-of-4. This is a probabilistic mitigation, not a structural guarantee — a code-level filter that checks every airport code in a reply against the dataset before sending it would close this class of error completely, but wasn't built given the assignment's time scope. It's flagged here as the one place in the system where "every number is born in a deterministic tool" is enforced by instruction rather than by code.
