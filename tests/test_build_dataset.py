"""Sanity checks for data/airports_dataset.csv produced by data/build_dataset.py."""
import csv
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH = os.path.join(REPO_ROOT, "data", "airports_dataset.csv")

REQUIRED_IATA_CODES = {"BOS", "LAX", "ANC", "SFO", "SNA"}


def _load_rows():
    with open(DATASET_PATH, newline="") as f:
        return list(csv.DictReader(f))


def test_dataset_exists():
    assert os.path.exists(DATASET_PATH), (
        f"{DATASET_PATH} not found — run `python build_dataset.py` from data/ first"
    )


def test_required_airports_present():
    rows = _load_rows()
    present = {row["iata"] for row in rows}
    missing = REQUIRED_IATA_CODES - present
    assert not missing, f"Required airports missing from dataset: {missing}"


def test_every_row_has_runways():
    rows = _load_rows()
    zero_runway = [row["iata"] for row in rows if int(row["runway_count"]) <= 0]
    assert not zero_runway, f"Airports with runway_count <= 0: {zero_runway}"


def test_no_duplicate_iata_codes():
    rows = _load_rows()
    codes = [row["iata"] for row in rows]
    assert len(codes) == len(set(codes)), "Duplicate IATA codes found in dataset"


def test_expected_columns_present():
    rows = _load_rows()
    expected = {
        "iata", "name", "state", "iso_region", "lat", "lon", "faa_rank_cy24",
        "runway_count", "longest_runway_ft", "enplanements_cy22", "enplanements_cy23",
        "enplanements_cy24", "enplanements_cy25_prelim", "bts_total_departures_12mo",
        "bts_total_passengers_12mo", "bts_total_routes", "bts_longhaul_routes",
        "longhaul_share_pct", "data_completeness",
    }
    assert expected.issubset(set(rows[0].keys()))
