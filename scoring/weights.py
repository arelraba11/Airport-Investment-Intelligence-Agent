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
