# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This is an early-stage "Airport Investment Intelligence Agent." Only the data pipeline exists so far
(`data/build_dataset.py`, committed as "Day 1 AM"). `README.md` and `DESIGN.md` are present but empty.
`scoring/` is an empty directory — presumably where airport scoring/ranking logic will live once the
agent layer is built. `requirements.txt` includes `fastapi`, `uvicorn`, `anthropic`, and `python-dotenv`
in addition to the data-pipeline deps (`pandas`, `openpyxl`), signalling that a FastAPI service backed by
the Anthropic API is the intended next layer on top of the dataset — but no such code exists yet.

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
