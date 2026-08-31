"""Scoring constants: component weights, capacity/long-haul assumptions, regions.

Kept in one module so the scoring methodology can be reviewed or retuned in a
single place, without touching scoring/formulas.py.
"""

# Relative influence of each investment_score component. This split is a
# judgment call about the investment thesis — capacity pressure today
# (congestion) and demand outrunning it (unmet_demand) matter most, route-mix
# quality least — not an empirically fitted result, and DESIGN.md presents it
# as such. The weights only behave as true relative weights because
# scoring/formulas.py percentile-normalizes all four components onto a common
# 0-100 scale before combining them; a raw-valued component added here would
# be driven by its numeric spread rather than by its weight.
WEIGHTS = {
    "congestion": 0.35,
    "growth": 0.25,
    "longhaul_mix": 0.15,
    "unmet_demand": 0.25,
}

# Assumed maximum annual movements (departures + arrivals) one runway can
# handle. A rough industry rule-of-thumb applied uniformly to every airport,
# NOT a measured per-airport capacity — a real figure would need runway
# configuration and ATC data. Documented as an assumption in DESIGN.md and
# surfaced to the user whenever congestion is discussed.
#
# It sets the denominator of the congestion ratio, so it directly scales the
# raw utilization percentages the agent quotes. Because it is applied
# uniformly it does not reorder the congestion percentile ranking, unless it
# were set low enough for the 1.0 cap in formulas.py to start binding (peak
# utilization is ~43% at the current value).
RUNWAY_CAPACITY_PER_YEAR = 230_000

# Great-circle distance at or above which a route counts as long-haul. Applied
# upstream in data/build_dataset.py when longhaul_share_pct is computed, so
# nothing in scoring/ reads this constant — it is kept here so the whole
# scoring methodology is stated in one place.
LONGHAUL_THRESHOLD_MILES = 2500

# Region -> member states. A lookup table rather than branching inside
# rank_airports(), so adding a region is a data change, not a code change.
REGIONS = {
    "new_england": {"ME", "NH", "VT", "MA", "RI", "CT"},
}


def normalize_region(region: str) -> str:
    """Map a free-text region name onto a REGIONS key, e.g. "New England"
    -> "new_england". Raises ValueError naming the valid regions if there's
    no match.

    Lives here, next to REGIONS itself, because the keys it has to match are
    defined here — and because both callers (backend.tools for the agent, and
    rank_airports.py for the CLI) need it, while neither should have to
    import the other.
    """
    key = region.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in REGIONS:
        raise ValueError(f"Unknown region: {region!r}. Known regions: {sorted(REGIONS)}")
    return key
