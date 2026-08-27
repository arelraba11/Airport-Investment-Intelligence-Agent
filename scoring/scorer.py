"""Orchestration on top of scoring/formulas.py: look up airports, rank them,
compare them side by side. No LLM calls here either — pure pandas/Python.
"""

from functools import lru_cache

from scoring.data_loader import load_dataset
from scoring.formulas import investment_score
from scoring.weights import REGIONS

RAW_METRIC_COLUMNS = [
    "state",
    "faa_rank_cy24",
    "runway_count",
    "longest_runway_ft",
    "enplanements_cy22",
    "enplanements_cy23",
    "enplanements_cy24",
    "enplanements_cy25_prelim",
    "bts_total_departures_12mo",
    "bts_total_passengers_12mo",
    "bts_total_routes",
    "bts_longhaul_routes",
    "longhaul_share_pct",
    "data_completeness",
]


class AirportNotFoundError(Exception):
    """Raised when an IATA code isn't present in the dataset."""


@lru_cache(maxsize=1)
def _dataset():
    return load_dataset()


def score_airport(iata: str) -> dict:
    dataset = _dataset()
    if iata not in dataset.index:
        raise AirportNotFoundError(f"Unknown IATA code: {iata!r}")

    airport = dataset.loc[iata]
    result = investment_score(airport, dataset)
    result["iata"] = iata
    result["name"] = airport["name"]
    result["data_year"] = "CY24"
    return result


def rank_airports(
    region: str | None = None,
    iata_list: list[str] | None = None,
    top_n: int = 10,
) -> list[dict]:
    dataset = _dataset()

    if iata_list is not None:
        candidates = iata_list
    elif region is not None:
        states = REGIONS[region]
        candidates = dataset[dataset["state"].isin(states)].index.tolist()
    else:
        candidates = dataset.index.tolist()

    scored = [score_airport(iata) for iata in candidates]
    scored.sort(
        key=lambda r: (r["investment_score"] is None, -(r["investment_score"] or 0))
    )

    top = scored[:top_n]
    for position, result in enumerate(top, start=1):
        result["rank"] = position
    return top


def compare_airports(iata_list: list[str]) -> dict:
    if len(iata_list) < 2:
        raise ValueError("compare_airports requires at least 2 IATA codes")

    dataset = _dataset()
    result = {}
    for iata in iata_list:
        entry = score_airport(iata)
        airport = dataset.loc[iata]
        entry["raw_metrics"] = airport[RAW_METRIC_COLUMNS].to_dict()
        result[iata] = entry
    return result
