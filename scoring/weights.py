WEIGHTS = {
    "congestion": 0.35,
    "growth": 0.25,
    "longhaul_mix": 0.15,
    "unmet_demand": 0.25,
}

RUNWAY_CAPACITY_PER_YEAR = 230_000  # assumed max annual movements (departures+arrivals) per runway
                                     # — a rough industry-standard capacity proxy, NOT measured;
                                     # documented as an assumption in DESIGN.md.

LONGHAUL_THRESHOLD_MILES = 2500  # already applied upstream when building longhaul_share_pct;
                                  # kept here only for documentation/traceability, not re-used in formulas.

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
