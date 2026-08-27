"""Build the unified airport investment dataset.

Merges OurAirports (airports.csv / runways.csv), 3 FAA commercial-service
enplanement workbooks (CY22-CY25 prelim), and one year of BTS T-100 domestic
segment traffic into data/airports_dataset.csv.

Run from the data/ directory:
    cd data && python build_dataset.py
"""
import csv
import os
import sys
import urllib.request

import pandas as pd

RAW_DIR = "raw"
OUTPUT_PATH = "airports_dataset.csv"

AIRPORTS_CSV = os.path.join(RAW_DIR, "airports.csv")
RUNWAYS_CSV = os.path.join(RAW_DIR, "runways.csv")
FAA_CY24_XLSX = os.path.join(RAW_DIR, "arp-cy2024-commercial-service-enplanements.xlsx")
FAA_CY23_XLSX = os.path.join(RAW_DIR, "cy23-commercial-service-enplanements.xlsx")
FAA_CY25_XLSX = os.path.join(RAW_DIR, "arp-cy2025-commercial-service-enplanements-preliminary.xlsx")
BTS_ASC = os.path.join(RAW_DIR, "db28seg.dd.wac.202409.202508.asc")

AIRPORTS_CSV_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv"
RUNWAYS_CSV_URL = "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/runways.csv"

# --- Scope definition (explicit, documented decision) ---
SCOPE_SIZE = 75  # top-N nationally by FAA CY24 rank
NEW_ENGLAND_STATES = {"ME", "NH", "VT", "MA", "RI", "CT"}
NEW_ENGLAND_RANK_CUTOFF = 150
# Rationale: top-75 alone leaves only 2 New England airports (BOS, BDL) in scope —
# not enough to meaningfully answer "which New England airports are strong candidates".
# Rank <=150 captures HVN (New Haven, rank 131) but excludes tiny essential-air-service
# strips like Block Island / Bar Harbor (<15K enplanements/year).

# FAA Locid -> OurAirports `ident`, used as a fallback lookup for renamed airports.
IATA_ALIASES = {"PBI": "KPBI"}

BTS_FIELDS = [
    "YEAR", "MONTH", "ORIGIN", "ORIGIN_AIRPORT_ID", "ORIGIN_CITY_MARKET_ID", "ORIGIN_CITY_NAME",
    "DEST", "DEST_AIRPORT_ID", "DEST_CITY_MARKET_ID", "DEST_CITY_NAME", "UNIQUE_CARRIER", "AIRLINE_ID",
    "CARRIER_GROUP_NEW", "DISTANCE_MILES", "CLASS", "AIRCRAFT_GROUP", "AIRCRAFT_TYPE", "AIRCRAFT_CONFIG",
    "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "PAYLOAD_LBS", "SEATS", "PASSENGERS", "FREIGHT_LBS",
    "MAIL_LBS", "RAMP_TO_RAMP_MIN", "AIR_TIME_MIN", "CARRIER_WAC",
]
ORIGIN_IDX = BTS_FIELDS.index("ORIGIN")
DEST_IDX = BTS_FIELDS.index("DEST")
CLASS_IDX = BTS_FIELDS.index("CLASS")
DISTANCE_IDX = BTS_FIELDS.index("DISTANCE_MILES")
DEPARTURES_PERFORMED_IDX = BTS_FIELDS.index("DEPARTURES_PERFORMED")
PASSENGERS_IDX = BTS_FIELDS.index("PASSENGERS")

LONGHAUL_MILES = 2500


def download_raw_files():
    os.makedirs(RAW_DIR, exist_ok=True)
    for path, url in ((AIRPORTS_CSV, AIRPORTS_CSV_URL), (RUNWAYS_CSV, RUNWAYS_CSV_URL)):
        if os.path.exists(path):
            print(f"[download] {path} already present, skipping")
            continue
        print(f"[download] fetching {url} -> {path}")
        urllib.request.urlretrieve(url, path)


def load_faa_scope():
    """Load the 3 FAA workbooks and build the in-scope airport list with enplanement history."""
    cy24_df = pd.read_excel(FAA_CY24_XLSX)
    cy23_df = pd.read_excel(FAA_CY23_XLSX)
    cy25_df = pd.read_excel(FAA_CY25_XLSX)

    cy24 = cy24_df[["Rank", "ST", "Locid", "Airport Name", "CY 24 Enplanements", "CY 23 Enplanements"]].copy()
    cy24.columns = ["faa_rank_cy24", "state", "iata", "name", "enplanements_cy24", "_cy23_from_cy24file"]

    cy23_only = cy23_df[["Locid", "CY 23 Enplanements", "CY 22 Enplanements"]].copy()
    cy23_only.columns = ["iata", "enplanements_cy23", "enplanements_cy22"]

    cy25 = cy25_df[["Locid", "CY 25 Enplanements"]].copy()
    cy25.columns = ["iata", "enplanements_cy25_prelim"]

    merged = cy24.merge(cy23_only, on="iata", how="left").merge(cy25, on="iata", how="left")
    merged["enplanements_cy23"] = merged["enplanements_cy23"].fillna(merged["_cy23_from_cy24file"])
    merged = merged.drop(columns=["_cy23_from_cy24file"])

    top_national = merged[merged["faa_rank_cy24"] <= SCOPE_SIZE]
    new_england = merged[
        merged["state"].isin(NEW_ENGLAND_STATES) & (merged["faa_rank_cy24"] <= NEW_ENGLAND_RANK_CUTOFF)
    ]

    scope = pd.concat([top_national, new_england]).drop_duplicates(subset="iata").reset_index(drop=True)

    print(f"[faa] top-{SCOPE_SIZE} national airports: {len(top_national)}")
    print(f"[faa] New England airports (rank<={NEW_ENGLAND_RANK_CUTOFF}): {len(new_england)}")
    print(f"[faa] combined scope after de-dup: {len(scope)} airports")
    return scope


def load_ourairports():
    """Return (airports_df indexed by iata, ident_by_iata dict)."""
    airports_df = pd.read_csv(AIRPORTS_CSV, dtype=str, keep_default_na=False)
    ident_by_iata = {}
    row_by_iata = {}
    for row in airports_df.itertuples(index=False):
        iata = row.iata_code
        if iata:
            ident_by_iata[iata] = row.ident
            row_by_iata[iata] = row
    return airports_df, ident_by_iata, row_by_iata


def _to_int_or_blank(value):
    return int(value) if pd.notna(value) else None


def resolve_ident(iata, ident_by_iata):
    if iata in ident_by_iata:
        return ident_by_iata[iata]
    alias_ident = IATA_ALIASES.get(iata)
    if alias_ident:
        return alias_ident
    return None


def load_runway_stats(ourairports_df):
    runways_df = pd.read_csv(RUNWAYS_CSV, dtype=str, keep_default_na=False)
    runways_df = runways_df[runways_df["closed"] != "1"]
    runways_df["length_ft"] = pd.to_numeric(runways_df["length_ft"], errors="coerce")
    stats = runways_df.groupby("airport_ident").agg(
        runway_count=("airport_ident", "count"),
        longest_runway_ft=("length_ft", "max"),
    )
    return stats


def stream_bts_aggregates(iata_codes):
    """Stream the BTS .asc file once, aggregating per-origin scheduled-passenger stats."""
    wanted = set(iata_codes)
    departures = {code: 0 for code in wanted}
    passengers = {code: 0 for code in wanted}
    routes = {code: set() for code in wanted}
    longhaul_routes = {code: set() for code in wanted}

    total_lines = 0
    used_lines = 0
    with open(BTS_ASC, encoding="utf-8", errors="replace") as f:
        for line in f:
            total_lines += 1
            fields = line.rstrip("\n").split("|")
            if len(fields) < 27:
                continue
            origin = fields[ORIGIN_IDX]
            if origin not in wanted:
                continue
            if fields[CLASS_IDX] != "F":
                continue
            used_lines += 1
            dest = fields[DEST_IDX]
            try:
                distance = float(fields[DISTANCE_IDX])
            except ValueError:
                continue
            try:
                dep_perf = float(fields[DEPARTURES_PERFORMED_IDX])
            except ValueError:
                dep_perf = 0.0
            try:
                pax = float(fields[PASSENGERS_IDX])
            except ValueError:
                pax = 0.0

            departures[origin] += dep_perf
            passengers[origin] += pax
            route_key = (dest, distance)
            routes[origin].add(route_key)
            if distance >= LONGHAUL_MILES:
                longhaul_routes[origin].add(route_key)

    print(f"[bts] scanned {total_lines} lines, {used_lines} matched scope + CLASS=F")

    result = {}
    for code in wanted:
        total_routes = len(routes[code])
        longhaul = len(longhaul_routes[code])
        longhaul_share_pct = round(100 * longhaul / total_routes, 1) if total_routes else 0.0
        result[code] = {
            "bts_total_departures_12mo": int(departures[code]),
            "bts_total_passengers_12mo": int(passengers[code]),
            "bts_total_routes": total_routes,
            "bts_longhaul_routes": longhaul,
            "longhaul_share_pct": longhaul_share_pct,
        }
    return result


def build_dataset():
    download_raw_files()

    scope = load_faa_scope()
    ourairports_df, ident_by_iata, row_by_iata = load_ourairports()
    runway_stats = load_runway_stats(ourairports_df)

    matched_rows = []
    missing_from_ourairports = []
    missing_runways = []

    for row in scope.itertuples(index=False):
        iata = row.iata
        oa_row = row_by_iata.get(iata)
        ident = resolve_ident(iata, ident_by_iata)

        if oa_row is None and iata in IATA_ALIASES:
            alias_ident = IATA_ALIASES[iata]
            for r in ourairports_df.itertuples(index=False):
                if r.ident == alias_ident:
                    oa_row = r
                    break

        if oa_row is None:
            missing_from_ourairports.append(iata)
            lat = lon = iso_region = ""
        else:
            lat = oa_row.latitude_deg
            lon = oa_row.longitude_deg
            iso_region = oa_row.iso_region

        if ident is not None and ident in runway_stats.index:
            runway_count = int(runway_stats.loc[ident, "runway_count"])
            longest_runway_ft = runway_stats.loc[ident, "longest_runway_ft"]
            longest_runway_ft = int(longest_runway_ft) if pd.notna(longest_runway_ft) else 0
        else:
            missing_runways.append(iata)
            runway_count = 0
            longest_runway_ft = 0

        matched_rows.append({
            "iata": iata,
            "name": row.name,
            "state": row.state,
            "iso_region": iso_region,
            "lat": lat,
            "lon": lon,
            "faa_rank_cy24": int(row.faa_rank_cy24),
            "runway_count": runway_count,
            "longest_runway_ft": longest_runway_ft,
            "enplanements_cy22": _to_int_or_blank(row.enplanements_cy22),
            "enplanements_cy23": _to_int_or_blank(row.enplanements_cy23),
            "enplanements_cy24": _to_int_or_blank(row.enplanements_cy24),
            "enplanements_cy25_prelim": _to_int_or_blank(row.enplanements_cy25_prelim),
        })

    print(f"[ourairports] {len(matched_rows)} in-scope airports total")
    print(f"[ourairports] missing from airports.csv: {len(missing_from_ourairports)} {missing_from_ourairports}")
    print(f"[runways] airports with no runway match: {len(missing_runways)} {missing_runways}")

    bts_stats = stream_bts_aggregates([r["iata"] for r in matched_rows])

    final_rows = []
    for r in matched_rows:
        bts = bts_stats.get(r["iata"], {
            "bts_total_departures_12mo": 0,
            "bts_total_passengers_12mo": 0,
            "bts_total_routes": 0,
            "bts_longhaul_routes": 0,
            "longhaul_share_pct": 0.0,
        })
        r.update(bts)

        has_cy22 = r["enplanements_cy22"] is not None
        r["data_completeness"] = (
            "full" if (has_cy22 and r["runway_count"] > 0 and r["bts_total_routes"] > 0) else "partial"
        )
        final_rows.append(r)

    columns = [
        "iata", "name", "state", "iso_region", "lat", "lon", "faa_rank_cy24",
        "runway_count", "longest_runway_ft",
        "enplanements_cy22", "enplanements_cy23", "enplanements_cy24", "enplanements_cy25_prelim",
        "bts_total_departures_12mo", "bts_total_passengers_12mo", "bts_total_routes",
        "bts_longhaul_routes", "longhaul_share_pct", "data_completeness",
    ]

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in final_rows:
            writer.writerow({c: r.get(c, "") for c in columns})

    print(f"[output] wrote {len(final_rows)} rows to {OUTPUT_PATH}")

    partial_count = sum(1 for r in final_rows if r["data_completeness"] == "partial")
    print(f"[summary] {len(final_rows) - partial_count} 'full' rows, {partial_count} 'partial' rows")

    print("\n=== New England airports by CY24 enplanements (descending) ===")
    ne_rows = [r for r in final_rows if r["state"] in NEW_ENGLAND_STATES]
    ne_rows.sort(key=lambda r: r["enplanements_cy24"] or 0, reverse=True)
    header = f"{'IATA':<6}{'Name':<45}{'Rank':<6}{'CY24 Enpl.':>12}"
    print(header)
    print("-" * len(header))
    for r in ne_rows:
        print(f"{r['iata']:<6}{r['name'][:43]:<45}{r['faa_rank_cy24']:<6}{r['enplanements_cy24']:>12,}")

    return final_rows


if __name__ == "__main__":
    build_dataset()
