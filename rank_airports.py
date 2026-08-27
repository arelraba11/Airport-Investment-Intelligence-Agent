"""Manual sanity-check CLI for the scoring engine. Not part of the agent.

Usage:
    python rank_airports.py --region new_england
    python rank_airports.py --iata BOS,BDL,PVD
"""

import sys

from scoring.scorer import rank_airports


def _fmt(value) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def print_table(results: list[dict]) -> None:
    header = f"{'Rank':<5}{'IATA':<6}{'Name':<38}{'Score':<8}{'Confidence':<12}{'Congest':<9}{'Growth':<8}{'LongHaul':<10}{'Unmet':<8}"
    print(header)
    print("-" * len(header))
    for r in results:
        c = r["components"]
        print(
            f"{r['rank']:<5}{r['iata']:<6}{r['name'][:36]:<38}"
            f"{_fmt(r['investment_score']):<8}{r['confidence']:<12}"
            f"{_fmt(c['congestion']):<9}{_fmt(c['growth']):<8}"
            f"{_fmt(c['longhaul_mix']):<10}{_fmt(c['unmet_demand']):<8}"
        )


def main(argv: list[str]) -> None:
    region = None
    iata_list = None

    for i, arg in enumerate(argv):
        if arg == "--region" and i + 1 < len(argv):
            region = argv[i + 1]
        elif arg == "--iata" and i + 1 < len(argv):
            iata_list = argv[i + 1].split(",")

    top_n = len(iata_list) if iata_list else 10
    results = rank_airports(region=region, iata_list=iata_list, top_n=top_n)
    print_table(results)


if __name__ == "__main__":
    main(sys.argv[1:])
