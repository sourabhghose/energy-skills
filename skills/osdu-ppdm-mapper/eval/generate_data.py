#!/usr/bin/env python3
"""Seeded synthetic vendor well-header and lease production data with planted mapping traps.

Purpose: data for the osdu-ppdm-mapper benchmark. Planted truth (see --print-truth):
  * completion-level rows (API-14) for wells with original holes and sidetracks
  * mixed API formats: dashed, plain, numeric with the Colorado (05) leading zero dropped
  * 3 malformed API values
  * a DATUM column mixing NAD27 and NAD83
  * status codes including one with no standard equivalent ("OBS")
  * one wellbore whose completions disagree on TD (conflicting duplicate)
  * oil production reported by lease, not by well (Texas-style)

Usage:
    python3 generate_data.py [--out DIR]     # DIR defaults to $SKILL_EVAL_DATA_DIR or ./eval_data
    python3 generate_data.py --print-truth
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
# (state, county, unique, sidetracks, completions per wellbore, datum, lease)
WELLS = [
    ("42", "301", f"{10000 + i:05d}", 2 if i % 4 == 0 else 1, 2 if i % 3 == 0 else 1,
     "NAD27" if i < 9 else "NAD83", f"L{100 + i // 3}")
    for i in range(14)
] + [("05", "123", f"{20000 + i:05d}", 1, 1, "NAD83", f"CO{i}") for i in range(4)]
STATUS_CYCLE = ["PR", "PR", "SI", "TA", "P&A", "PR", "INJ", "OBS"]
BAD_APIS = ["42-301-1234", "4230", "N/A"]
CONFLICT_WELLBORE = ("42", "301", "10000", "00")


def _api(state, county, unique, bore, comp, style: int) -> str | float:
    digits = f"{state}{county}{unique}{bore:02d}{comp:02d}"
    if state == "05" and style == 2:
        return float(digits)  # stored numerically: leading zero lost, '.0' appended
    if style == 0:
        return f"{state}-{county}-{unique}-{bore:02d}-{comp:02d}"
    return digits


def _rows(rng: np.random.Generator) -> list[dict]:
    rows = []
    for i, (st, co, un, bores, comps, datum, lease) in enumerate(WELLS):
        lat, lon = 31.5 + i * 0.03, -103.2 - i * 0.02
        for b in range(bores):
            td = int(9000 + 800 * b + rng.integers(0, 500))
            for c in range(comps):
                conflict = (st, co, un, f"{b:02d}") == CONFLICT_WELLBORE and c == 1
                rows.append({
                    "API_NO": _api(st, co, un, b, c, style=(i + c) % 3),
                    "LEASE_WELL": f"{'SMITH' if st == '42' else 'ROCKY'} {i + 1}{'H' if b == 0 else 'H ST' + str(b)}",
                    "OPERATOR": "Acme Energy" if i % 2 == 0 else "Borealis Resources",
                    "WELL_STATUS": STATUS_CYCLE[i % len(STATUS_CYCLE)],
                    "SURF_LAT": round(lat, 5), "SURF_LONG": round(lon, 5), "DATUM": datum,
                    "TD": td + 750 if conflict else td, "LEASE_ID": lease,
                })
    return rows


def build_header(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = _rows(rng)
    bad = [{**rows[k], "API_NO": api} for k, api in zip((1, 5, 9), BAD_APIS)]
    return pd.DataFrame(rows + bad)


def build_production(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed + 1)
    leases = sorted({w[6] for w in WELLS if w[0] == "42"})
    months = pd.date_range("2026-01-01", periods=6, freq="MS")
    return pd.DataFrame([{"LEASE_ID": lease, "PROD_MONTH": m.date().isoformat(),
                          "OIL_BBL": int(rng.integers(2000, 9000)), "GAS_MCF": int(rng.integers(5000, 30000))}
                         for lease in leases for m in months])


def truth() -> dict:
    header = build_header()
    good = header[~header["API_NO"].isin(BAD_APIS)]
    wellbores = {f"{w[0]}{w[1]}{w[2]}{b:02d}" for w in WELLS for b in range(w[3])}
    return {
        "completion_rows_valid": int(len(good)),
        "distinct_wells_api10": len({f"{w[0]}{w[1]}{w[2]}" for w in WELLS}),
        "distinct_wellbores_api12": len(wellbores),
        "sidetracked_wells": sorted(f"{w[0]}{w[1]}{w[2]}" for w in WELLS if w[3] > 1),
        "conflicting_wellbore": "".join(CONFLICT_WELLBORE),
        "bad_api_values": BAD_APIS,
        "colorado_numeric_rows": int(header["API_NO"].map(lambda v: isinstance(v, float)).sum()),
        "datum_row_counts": header["DATUM"].value_counts().to_dict(),
        "unmapped_status_codes": ["OBS"],
        "production_reporting_level": "lease",
        "wells_per_lease_max": int(pd.Series([w[6] for w in WELLS]).value_counts().max()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.environ.get("SKILL_EVAL_DATA_DIR", "eval_data"))
    parser.add_argument("--print-truth", action="store_true")
    args = parser.parse_args()
    if args.print_truth:
        print(json.dumps(truth(), indent=2))
        return
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    build_header().to_csv(out / "vendor_well_header.csv", index=False)
    build_production().to_csv(out / "lease_production.csv", index=False)
    print(f"wrote vendor_well_header.csv and lease_production.csv to {out}")


if __name__ == "__main__":
    main()
