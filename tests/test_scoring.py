import math

import pandas as pd
import pytest

from scoring.data_loader import load_dataset
from scoring.formulas import (
    congestion_score,
    growth_score,
    longhaul_mix_score,
    unmet_demand_score,
    investment_score,
)
from scoring.scorer import (
    AirportNotFoundError,
    score_airport,
    rank_airports,
    compare_airports,
)


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def test_load_dataset_indexed_by_iata(dataset):
    assert dataset.index.name == "iata"
    assert "BOS" in dataset.index


def test_congestion_score_normal_airport_in_range(dataset):
    airport = dataset.loc["ATL"]
    score = congestion_score(airport, dataset)
    assert score is not None
    assert 0 <= score <= 100


def test_congestion_score_is_percentile_normalized_across_dataset(dataset):
    from scoring.formulas import _raw_congestion_ratio

    airport = dataset.loc["ATL"]
    score = congestion_score(airport, dataset)

    raw_ratios = dataset.apply(_raw_congestion_ratio, axis=1)
    expected = float((raw_ratios.rank(pct=True) * 100).loc["ATL"])
    assert score == pytest.approx(expected)


def test_congestion_score_zero_runways_returns_none(dataset):
    airport = dataset.loc["ATL"].copy()
    airport["runway_count"] = 0
    assert congestion_score(airport, dataset) is None


def test_growth_score_valid_data_in_range(dataset):
    airport = dataset.loc["ATL"]
    score = growth_score(airport, dataset)
    assert score is not None
    assert 0 <= score <= 100


def test_growth_score_missing_cy22_returns_none(dataset):
    airport = dataset.loc["ATL"].copy()
    airport["enplanements_cy22"] = None
    assert growth_score(airport, dataset) is None


def test_longhaul_mix_score_is_percentile_normalized_across_dataset(dataset):
    airport = dataset.loc["ATL"]
    score = longhaul_mix_score(airport, dataset)

    expected = float((dataset["longhaul_share_pct"].rank(pct=True) * 100).loc["ATL"])
    assert score == pytest.approx(expected)


def test_longhaul_mix_score_none_when_source_is_nan(dataset):
    airport = dataset.loc["ATL"].copy()
    airport["longhaul_share_pct"] = float("nan")
    assert longhaul_mix_score(airport, dataset) is None


def test_investment_score_full_airport_is_high_confidence(dataset):
    airport = dataset.loc["ATL"]
    result = investment_score(airport, dataset)
    assert result["confidence"] == "high"
    assert result["investment_score"] is not None
    assert 0 <= result["investment_score"] <= 100


def test_investment_score_exposes_raw_values_alongside_percentiles(dataset):
    from scoring.formulas import _raw_cagr

    airport = dataset.loc["ATL"]
    result = investment_score(airport, dataset)

    raw = result["raw_values"]
    expected_cagr_pct = _raw_cagr(airport) * 100
    assert raw["growth_cagr_pct"] == pytest.approx(expected_cagr_pct)
    assert raw["longhaul_share_pct"] == pytest.approx(airport["longhaul_share_pct"])
    assert raw["congestion_capacity_utilization_pct"] is not None
    assert 0 <= raw["congestion_capacity_utilization_pct"] <= 100


def test_investment_score_renormalizes_when_component_missing(dataset):
    airport = dataset.loc["ATL"].copy()
    airport["longhaul_share_pct"] = float("nan")  # longhaul_mix component becomes None
    result = investment_score(airport, dataset)

    assert result["components"]["longhaul_mix"] is None
    assert result["investment_score"] is not None

    # manually recompute the expected renormalized weighted sum
    congestion = result["components"]["congestion"]
    growth = result["components"]["growth"]
    unmet_demand = result["components"]["unmet_demand"]
    remaining_weight = 0.35 + 0.25 + 0.25  # congestion + growth + unmet_demand
    expected = (
        congestion * 0.35 + growth * 0.25 + unmet_demand * 0.25
    ) / remaining_weight
    assert result["investment_score"] == pytest.approx(expected)


def test_score_airport_unknown_iata_raises():
    with pytest.raises(AirportNotFoundError):
        score_airport("ZZZ")


def test_rank_airports_new_england_returns_expected_seven():
    results = rank_airports(region="new_england")
    expected = {"BOS", "BDL", "PVD", "PWM", "BTV", "MHT", "HVN"}
    assert {r["iata"] for r in results} == expected

    scores = [
        r["investment_score"] for r in results if r["investment_score"] is not None
    ]
    assert scores == sorted(scores, reverse=True)


def test_bos_outranks_hvn_after_percentile_normalizing_all_components():
    """Regression test for the weights-are-decorative bug: before
    percentile-normalizing congestion and longhaul_mix, HVN's growth
    percentile alone (unopposed by a same-scale congestion signal) put it
    ahead of BOS despite BOS being the region's largest, busiest airport.
    """
    results = rank_airports(region="new_england")
    scores = {r["iata"]: r["investment_score"] for r in results}
    assert scores["BOS"] > scores["HVN"]


def test_compare_airports_requires_two_or_more():
    with pytest.raises(ValueError):
        compare_airports(["BOS"])


def test_compare_airports_includes_raw_metrics():
    result = compare_airports(["LAX", "SNA"])
    assert set(result.keys()) == {"LAX", "SNA"}
    assert "raw_metrics" in result["LAX"]
    assert result["LAX"]["raw_metrics"]["enplanements_cy24"] > 0
