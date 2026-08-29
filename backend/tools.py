"""Agent tool implementations (Phase A.2).

Six tools the agent (Phase A.3) will call, each returning JSON-serializable
data only — never free text or partial prose. Tools that wrap the existing,
already-tested scoring engine (`score_airport`, `rank_airports`,
`compare_airports`) are thin passthroughs over `scoring/scorer.py` — no
scoring logic is reimplemented here.

Note on `get_airport_profile`/`resolve_airport`'s "city" field: the dataset
(`data/airports_dataset.csv`) has no `city` column, only `name` and `state`
(verified against the CSV header, not assumed). `CITY_BY_IATA` below is a
small hardcoded lookup table (alongside `ALIASES`) built by hand from the
80 in-scope airports' well-known metro areas, so `resolve_airport` can match
informal city references ("Boston", "Portland") and disambiguate real
collisions (PDX vs PWM, both "Portland"; IAD vs DCA, both "Washington").
"""

import difflib
import re
import time
from functools import lru_cache
from typing import Optional

import pandas as pd
import requests

from scoring import scorer
from scoring.data_loader import load_dataset
from scoring.weights import REGIONS

# --- Informal-name lookup tables (hand-built from the 80 in-scope airports) ---

CITY_BY_IATA: dict[str, str] = {
    "ATL": "Atlanta", "DFW": "Dallas-Fort Worth", "DEN": "Denver", "ORD": "Chicago",
    "LAX": "Los Angeles", "JFK": "New York", "CLT": "Charlotte", "LAS": "Las Vegas",
    "MCO": "Orlando", "MIA": "Miami", "PHX": "Phoenix", "SEA": "Seattle",
    "SFO": "San Francisco", "EWR": "Newark", "IAH": "Houston", "BOS": "Boston",
    "MSP": "Minneapolis", "FLL": "Fort Lauderdale", "LGA": "New York", "DTW": "Detroit",
    "PHL": "Philadelphia", "SLC": "Salt Lake City", "BWI": "Baltimore", "IAD": "Washington",
    "SAN": "San Diego", "DCA": "Washington", "TPA": "Tampa", "BNA": "Nashville",
    "AUS": "Austin", "HNL": "Honolulu", "MDW": "Chicago", "DAL": "Dallas",
    "PDX": "Portland", "STL": "St. Louis", "RDU": "Raleigh", "HOU": "Houston",
    "SMF": "Sacramento", "MSY": "New Orleans", "SJU": "San Juan", "MCI": "Kansas City",
    "SJC": "San Jose", "SAT": "San Antonio", "RSW": "Fort Myers", "SNA": "Santa Ana",
    "OAK": "Oakland", "IND": "Indianapolis", "CLE": "Cleveland", "PIT": "Pittsburgh",
    "CVG": "Cincinnati", "CMH": "Columbus", "PBI": "West Palm Beach", "JAX": "Jacksonville",
    "ONT": "Ontario", "OGG": "Kahului", "BUR": "Burbank", "BDL": "Hartford",
    "CHS": "Charleston", "MKE": "Milwaukee", "ANC": "Anchorage", "ABQ": "Albuquerque",
    "OMA": "Omaha", "BUF": "Buffalo", "BOI": "Boise", "RIC": "Richmond",
    "ORF": "Norfolk", "MEM": "Memphis", "RNO": "Reno", "SDF": "Louisville",
    "OKC": "Oklahoma City", "SRQ": "Sarasota", "ELP": "El Paso", "GRR": "Grand Rapids",
    "GEG": "Spokane", "LGB": "Long Beach", "KOA": "Kona", "PVD": "Providence",
    "PWM": "Portland", "BTV": "Burlington", "MHT": "Manchester", "HVN": "New Haven",
}

# Informal/abbreviated references that wouldn't fuzzy-match cleanly against
# CITY_BY_IATA/name (e.g. "LA" is too short to fuzzy-match "Los Angeles"
# reliably, and several of these disambiguate a metro area with multiple
# in-scope airports down to the one most people mean).
ALIASES: dict[str, str] = {
    "la": "LAX",
    "los angeles": "LAX",
    "santa ana": "SNA",
    "orange county": "SNA",
    "john wayne": "SNA",
    "anchorage": "ANC",
    "sf": "SFO",
    "san fran": "SFO",
    "vegas": "LAS",
    "philly": "PHL",
    "dulles": "IAD",
    "reagan": "DCA",
    "reagan national": "DCA",
    "national airport": "DCA",
    "maui": "OGG",
    "nola": "MSY",
    "ohare": "ORD",
    "o'hare": "ORD",
}

# Fuzzy-match tuning: a candidate needs at least this ratio to be considered
# a plausible match at all; among plausible candidates, the top one must beat
# the runner-up by at least this margin to be treated as a confident single
# match rather than an ambiguous one.
_FUZZY_MIN_RATIO = 0.55
_FUZZY_CONFIDENCE_MARGIN = 0.15

# Descriptive suffix words that don't help identify a specific airport (e.g.
# "Boston Logan airport" vs. just "Boston") and only dilute the fuzzy-match
# ratio against short city names. Stripped as a fallback pass, not from the
# query the user actually sees applied first — see resolve_airport.
_NOISE_WORDS = re.compile(r"\b(airport|international|regional|intl)\b", re.IGNORECASE)

_BBOX_DEGREES = 0.15  # ~15km bounding box around the airport for OpenSky queries
_TRAFFIC_CACHE_TTL_SECONDS = 600  # 10 minutes
_traffic_cache: dict[str, tuple[float, dict]] = {}


@lru_cache(maxsize=1)
def _dataset() -> pd.DataFrame:
    return load_dataset()


def _to_json_safe(value):
    """Convert a single pandas/numpy scalar to a plain JSON-serializable value."""
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _airport_summary(iata: str, dataset: pd.DataFrame) -> dict:
    row = dataset.loc[iata]
    return {
        "iata": iata,
        "name": str(row["name"]),
        "city": CITY_BY_IATA.get(iata, str(row["name"])),
    }


def _normalize_region(region: str) -> str:
    key = region.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in REGIONS:
        raise ValueError(f"Unknown region: {region!r}. Known regions: {sorted(REGIONS)}")
    return key


def _strip_noise_words(query: str) -> str:
    """Drop descriptive suffix words (see _NOISE_WORDS) and collapse whitespace."""
    return re.sub(r"\s+", " ", _NOISE_WORDS.sub("", query)).strip()


def _match_query(query: str, dataset: pd.DataFrame) -> Optional[dict]:
    """Try to resolve `query` against `dataset`, trying alias/exact/fuzzy in
    order. Returns None (not a not_found dict) if nothing plausible matched,
    so callers can retry with a different form of the query before giving up.
    """
    q_lower = query.lower()
    if q_lower in ALIASES:
        return _airport_summary(ALIASES[q_lower], dataset)

    exact_matches = sorted(
        {
            iata
            for iata in dataset.index
            if q_lower == CITY_BY_IATA.get(iata, "").lower()
            or q_lower == str(dataset.loc[iata, "name"]).lower()
        }
    )
    if len(exact_matches) == 1:
        return _airport_summary(exact_matches[0], dataset)
    if len(exact_matches) > 1:
        return {"ambiguous": True, "candidates": [_airport_summary(i, dataset) for i in exact_matches]}

    scored = []
    for iata in dataset.index:
        city = CITY_BY_IATA.get(iata, "")
        name = str(dataset.loc[iata, "name"])
        ratio = max(
            difflib.SequenceMatcher(None, q_lower, city.lower()).ratio(),
            difflib.SequenceMatcher(None, q_lower, name.lower()).ratio(),
        )
        scored.append((ratio, iata))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    plausible = [(ratio, iata) for ratio, iata in scored if ratio >= _FUZZY_MIN_RATIO]
    if not plausible:
        return None

    if len(plausible) == 1:
        return _airport_summary(plausible[0][1], dataset)

    top_ratio, second_ratio = plausible[0][0], plausible[1][0]
    if top_ratio - second_ratio >= _FUZZY_CONFIDENCE_MARGIN:
        return _airport_summary(plausible[0][1], dataset)

    candidates = [iata for _, iata in plausible[:5]]
    return {"ambiguous": True, "candidates": [_airport_summary(i, dataset) for i in candidates]}


def resolve_airport(query: str) -> dict:
    """Resolve a free-text airport reference to an in-scope IATA code.

    Tries, in order: exact IATA code, the informal-alias table, an exact
    case-insensitive match on city/name, then fuzzy matching on city/name. If
    none of those match, retries the same pipeline once more with common
    descriptive noise words (e.g. "airport", "international") stripped from
    the query — this handles longer free-text phrases like "Boston Logan
    airport" that would otherwise dilute the fuzzy-match ratio against a
    short city name like "Boston".
    Returns one of:
      - {"iata", "name", "city"} for a single confident match
      - {"ambiguous": True, "candidates": [...]} when multiple airports are
        equally plausible (e.g. "Portland" -> PDX and PWM)
      - {"not_found": True, "in_scope": False} when nothing plausible matches
        within the 80-airport scope
    """
    dataset = _dataset()
    query = query.strip()
    if not query:
        return {"not_found": True, "in_scope": False}

    q_upper = query.upper()
    if q_upper in dataset.index:
        return _airport_summary(q_upper, dataset)

    result = _match_query(query, dataset)
    if result is not None:
        return result

    cleaned = _strip_noise_words(query)
    if cleaned and cleaned.lower() != query.lower():
        result = _match_query(cleaned, dataset)
        if result is not None:
            return result

    return {"not_found": True, "in_scope": False}


def get_airport_profile(iata: str) -> dict:
    """Return the raw dataset row for an in-scope IATA code as plain JSON.

    Returns {"not_found": True, "in_scope": False} (same shape as
    resolve_airport's not-found case) if the code isn't one of the 80
    in-scope airports.
    """
    dataset = _dataset()
    code = iata.strip().upper()
    if code not in dataset.index:
        return {"not_found": True, "in_scope": False}

    row = dataset.loc[code]
    profile = {"iata": code, "city": CITY_BY_IATA.get(code, str(row["name"]))}
    profile.update({column: _to_json_safe(row[column]) for column in dataset.columns})
    return profile


def score_airport(iata: str) -> dict:
    """Thin wrapper around scoring.scorer.score_airport.

    Returns the overall investment_score, its 4 percentile-normalized
    components, raw_values for human-readable explanations, and confidence.
    Raises scoring.scorer.AirportNotFoundError for an out-of-scope code —
    left to the agent loop's tool-error handling (Phase A.3), not caught here.
    """
    return scorer.score_airport(iata.strip().upper())


def rank_airports(
    region: Optional[str] = None,
    iata_list: Optional[list[str]] = None,
    top_n: int = 10,
) -> list[dict]:
    """Thin wrapper around scoring.scorer.rank_airports.

    `region` is matched case/spacing-insensitively against scoring.weights.REGIONS
    (e.g. "New England" -> "new_england"). Raises ValueError for an unknown region.
    """
    region_key = _normalize_region(region) if region else None
    codes = [code.strip().upper() for code in iata_list] if iata_list else None
    return scorer.rank_airports(region=region_key, iata_list=codes, top_n=top_n)


def compare_airports(iata_list: list[str]) -> dict:
    """Thin wrapper around scoring.scorer.compare_airports.

    Returns, per IATA code, the overall score, 4 component breakdowns,
    raw_values, and raw_metrics — sanitized to plain Python types for JSON.
    """
    codes = [code.strip().upper() for code in iata_list]
    result = scorer.compare_airports(codes)
    for entry in result.values():
        entry["raw_metrics"] = {k: _to_json_safe(v) for k, v in entry["raw_metrics"].items()}
    return result


def get_live_traffic(iata: str) -> dict:
    """Best-effort live aircraft count near an airport, via OpenSky Network.

    Queries a bounding box (+/- _BBOX_DEGREES) around the airport's lat/lon,
    with a 5s timeout and a 10-minute in-memory cache per IATA code. Never
    raises: any failure (bad code, missing coordinates, timeout, non-200,
    network error) degrades to {"available": False, "note": "live data
    unavailable"} so the agent can carry on without live data.
    """
    code = iata.strip().upper()
    now = time.time()

    cached = _traffic_cache.get(code)
    if cached is not None and now - cached[0] < _TRAFFIC_CACHE_TTL_SECONDS:
        return cached[1]

    dataset = _dataset()
    if code not in dataset.index:
        return {"available": False, "note": "live data unavailable"}

    row = dataset.loc[code]
    lat, lon = row.get("lat"), row.get("lon")
    if pd.isna(lat) or pd.isna(lon):
        return {"available": False, "note": "live data unavailable"}

    params = {
        "lamin": lat - _BBOX_DEGREES,
        "lamax": lat + _BBOX_DEGREES,
        "lomin": lon - _BBOX_DEGREES,
        "lomax": lon + _BBOX_DEGREES,
    }
    try:
        response = requests.get("https://opensky-network.org/api/states/all", params=params, timeout=5)
        if response.status_code != 200:
            result = {"available": False, "note": "live data unavailable"}
        else:
            states = response.json().get("states") or []
            result = {
                "available": True,
                "iata": code,
                "aircraft_nearby": len(states),
                "source": "OpenSky Network",
                "bounding_box_degrees": _BBOX_DEGREES,
            }
    except (requests.RequestException, ValueError):
        result = {"available": False, "note": "live data unavailable"}

    _traffic_cache[code] = (now, result)
    return result
