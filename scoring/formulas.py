"""Pure, deterministic scoring functions. No LLM calls, no I/O.

Every function takes a single airport's data (a pandas Series, indexable by
column name) and returns a float in [0, 100], or None when a required input
is missing — never a fabricated number.

All four investment_score components are percentile-normalized across
`full_dataset` before being combined. This is deliberate: components have
wildly different natural scales (e.g. raw congestion utilization sits in the
~1.85-42.7% band across the current 80-airport scope, while raw longhaul share
and growth CAGR occupy entirely different bands), so combining raw values in a
weighted sum
would let the widest-spread component dominate the final score's variance
regardless of its assigned weight in weights.py. Percentile-normalizing every
component onto the same 0-100 scale is what makes WEIGHTS actually control
each component's influence, rather than being decorative.
"""

from typing import Callable

import pandas as pd

from scoring.weights import RUNWAY_CAPACITY_PER_YEAR, WEIGHTS


def _is_missing(value: object) -> bool:
    return value is None or pd.isna(value)


def _raw_congestion_ratio(airport: pd.Series) -> float | None:
    """Fraction of estimated annual runway capacity consumed by departures,
    capped at 1.0. Not itself the congestion_score — see module docstring —
    but exposed for human-readable explanations (e.g. "~18% of capacity").
    """
    runway_count = airport["runway_count"]
    if _is_missing(runway_count):
        return None
    capacity = runway_count * RUNWAY_CAPACITY_PER_YEAR
    if capacity == 0:
        return None
    departures = airport["bts_total_departures_12mo"]
    if _is_missing(departures):
        return None
    return min(departures / capacity, 1.0)


def _raw_cagr(airport: pd.Series) -> float | None:
    cy22 = airport["enplanements_cy22"]
    cy24 = airport["enplanements_cy24"]
    if _is_missing(cy22) or cy22 == 0 or _is_missing(cy24):
        return None
    return (cy24 / cy22) ** (1 / 2) - 1


def _raw_longhaul_share(airport: pd.Series) -> float | None:
    value = airport["longhaul_share_pct"]
    if _is_missing(value):
        return None
    return float(value)


def _percentile_rank(
    own_raw: float | None,
    raw_fn: Callable[[pd.Series], float | None],
    airport: pd.Series,
    full_dataset: pd.DataFrame,
) -> float | None:
    """Percentile rank of `own_raw` among `raw_fn` applied to every row of
    `full_dataset`, on a 0-100 scale. `airport` may be a modified copy of a
    dataset row (or not present in the index at all), so its own raw value
    is computed directly rather than looked up from `full_dataset` — that
    value is then inserted into the ranking (replacing any stale entry at
    the same key) so it's ranked correctly against everyone else.
    """
    if own_raw is None:
        return None
    key = airport.name if airport.name is not None else "__query__"
    raw_values = full_dataset.apply(raw_fn, axis=1).dropna()
    raw_values.loc[key] = own_raw
    percentile = raw_values.rank(pct=True) * 100
    return float(percentile.loc[key])


def congestion_score(airport: pd.Series, full_dataset: pd.DataFrame) -> float | None:
    return _percentile_rank(_raw_congestion_ratio(airport), _raw_congestion_ratio, airport, full_dataset)


def growth_score(airport: pd.Series, full_dataset: pd.DataFrame) -> float | None:
    return _percentile_rank(_raw_cagr(airport), _raw_cagr, airport, full_dataset)


def longhaul_mix_score(airport: pd.Series, full_dataset: pd.DataFrame) -> float | None:
    return _percentile_rank(_raw_longhaul_share(airport), _raw_longhaul_share, airport, full_dataset)


def unmet_demand_score(airport: pd.Series, full_dataset: pd.DataFrame) -> float | None:
    """Heuristic, not a measured quantity: high growth combined with high
    congestion suggests demand is outrunning available capacity. There is no
    real "unmet demand" field in any source data.
    """
    g = growth_score(airport, full_dataset)
    c = congestion_score(airport, full_dataset)
    if g is None or c is None:
        return None
    return g * 0.6 + c * 0.4


def investment_score(airport: pd.Series, full_dataset: pd.DataFrame) -> dict:
    components = {
        "congestion": congestion_score(airport, full_dataset),
        "growth": growth_score(airport, full_dataset),
        "longhaul_mix": longhaul_mix_score(airport, full_dataset),
        "unmet_demand": unmet_demand_score(airport, full_dataset),
    }

    non_none = {k: v for k, v in components.items() if v is not None}

    if not non_none:
        score = None
    else:
        # Re-normalize weights over the components that are actually
        # available, so a missing component doesn't silently shrink the
        # weighted sum instead of being excluded from it.
        weight_total = sum(WEIGHTS[k] for k in non_none)
        score = sum(v * WEIGHTS[k] for k, v in non_none.items()) / weight_total

    data_completeness = airport.get("data_completeness")
    if len(non_none) == 4 and data_completeness == "full":
        confidence = "high"
    elif len(non_none) >= 2:
        confidence = "partial"
    else:
        confidence = "insufficient_data"

    raw_congestion = _raw_congestion_ratio(airport)
    raw_cagr = _raw_cagr(airport)

    return {
        "investment_score": score,
        "components": components,
        "raw_values": {
            "congestion_capacity_utilization_pct": None if raw_congestion is None else raw_congestion * 100,
            "growth_cagr_pct": None if raw_cagr is None else raw_cagr * 100,
            "longhaul_share_pct": _raw_longhaul_share(airport),
        },
        "confidence": confidence,
    }
