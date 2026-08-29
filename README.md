# Airport Investment Intelligence Agent

## 1. What this is

An AI agent that helps an airport-modernization investment firm identify which US airports are
strong candidates for terminal/capacity expansion. It combines public aviation data (OurAirports,
FAA enplanements, BTS T-100 traffic) with a deterministic Python scoring engine and a conversational
chat interface — the LLM explains and answers follow-up questions, but never computes a number
itself. Built for the Deloitte Digital Forward Deployed Engineer take-home assignment. See
[DESIGN.md](DESIGN.md) for scoring methodology, architecture, and key tradeoffs.

## 2. Prerequisites

- Python 3 (tested with 3.14; anything reasonably recent should work — no version-specific syntax
  is used)
- Node.js + npm (tested with Node v22, npm v10; frontend is a standard Vite + React 19 app)
- An Anthropic API key (`ANTHROPIC_API_KEY`)

## 3. Environment variables

Set this up **before** starting the backend in step 4 below — the backend will start and `/health`
will look fine without it, but every `/chat` request will fail with a bare 500 error until it's set.

Copy `.env.example` to `.env` **at the project root** and fill in your key:

```bash
cp .env.example .env
# then edit .env: ANTHROPIC_API_KEY=sk-ant-...
```

`backend/agent.py` loads this via `python-dotenv`'s `load_dotenv()`, which resolves relative to the
current working directory — so run `uvicorn` from the repo root (as in step 4 below) for the key to
be picked up automatically.

## 4. Setup & run

`data/airports_dataset.csv` — the built output of the data pipeline — ships pre-built and
**is tracked in this git repository**, so a clean clone can go straight from installing dependencies
to running the app, with **zero downloads beyond `pip install`/`npm install`**. Rebuilding the
dataset from raw sources (step 3 below) is optional and only needed if you want to regenerate it.

Run from the repo root, in order:

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv && source venv/bin/activate

# 2. Install backend/data/scoring dependencies
pip install -r requirements.txt

# 3. (OPTIONAL — skip this to use the pre-built dataset already in the repo) Rebuild the dataset;
#    see "Rebuilding the dataset from scratch" below before running this
cd data && python build_dataset.py && cd ..

# 4. Start the backend (from the repo root; keep this running) — requires .env, see section 3 above
uvicorn backend.main:app --port 8000

# 5. In a second terminal: install and start the frontend
cd frontend && npm install && npm run dev
```

Then open the URL Vite prints (`http://localhost:5173`).

### Rebuilding the dataset from scratch (optional)

Skip this section entirely unless you specifically want to regenerate `data/airports_dataset.csv`
(e.g. to pick up newer FAA/BTS data). `data/raw/` itself is not tracked in this git repository (see
`.gitignore`) — running step 3 without first populating it will fail on the FAA/BTS files below.

`build_dataset.py` merges three public sources:

- **OurAirports** (`data/raw/airports.csv`, `runways.csv`) — auto-downloaded automatically from
  `https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/` if not already present;
  no manual step needed for these two.
- **FAA commercial-service enplanements** — three CY22–CY25(prelim) workbooks, from the FAA's
  Passenger Boarding (Enplanement) data portal (`faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger`).
  Must be placed manually in `data/raw/` as `cy23-commercial-service-enplanements.xlsx`,
  `arp-cy2024-commercial-service-enplanements.xlsx`, and
  `arp-cy2025-commercial-service-enplanements-preliminary.xlsx` — `build_dataset.py` has no URL or
  auto-download logic for these, only fixed local filenames.
- **BTS T-100 Domestic Segment traffic** — one pipe-delimited `.asc` extract from the BTS TranStats
  T-100 Domestic Segment database (`transtats.bts.gov`), covering 12 months of route-level traffic.
  Must be placed manually in `data/raw/` as `db28seg.dd.wac.202409.202508.asc` — same as above, no
  auto-download.

These three FAA/BTS files were pre-supplied for this assignment rather than scripted; a general
downloader for them was deliberately not built (scope/time tradeoff — see DESIGN.md).

## 5. Example questions

Try these once both servers are running (also available as suggested-question chips in the UI):

1. Which airports in New England are strong candidates for terminal expansion?
2. Compare LA and Santa Ana airport congestion levels.
3. What is the percentage of long-haul flights out of Anchorage airport?
4. What is the unmet flight demand in SFO airport and why?

## 6. Repo structure

```
data/       Data pipeline (build_dataset.py) that merges OurAirports + FAA + BTS sources
            into data/airports_dataset.csv
scoring/    Deterministic scoring engine (weights, formulas, ranking) — zero LLM calls
backend/    FastAPI app: agent tool-use loop, chat endpoint, sessions, system prompt
frontend/   React + Vite chat UI
tests/      pytest suite for the dataset and scoring engine
DESIGN.md   Scoring methodology, architecture, tradeoffs, and where/how AI is used
```
