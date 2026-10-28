"""Planted-truth data for energy-report-writer eval tasks.

Writes three small inputs to SKILL_EVAL_DATA_DIR (default ./data):
  reliability_annual.csv   SAIDI/SAIFI/CAIDI 2021-2025, MED-included and MED-excluded
  reliability_manifest.json  decisions used upstream (T_MED, MED dates)
  decline_summary.csv      decline-analysis EUR per well (technical forecasts, not reserves)

Planted answers are printed to stdout for the evaluator to copy into
expectations.json; they are never written into the data folder.

Usage:
  SKILL_EVAL_DATA_DIR=/Volumes/<catalog>/<schema>/eval/energy-report-writer python generate_data.py
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

OUT_DIR = Path(os.environ.get("SKILL_EVAL_DATA_DIR", Path(__file__).parent / "data"))

# (year, saidi_excl, saifi_excl, saidi_incl, saifi_incl) in min and interruptions/customer
RELIABILITY = [
    (2021, 118.6, 1.02, 131.9, 1.09),
    (2022, 121.4, 1.05, 121.4, 1.05),
    (2023, 115.2, 0.98, 188.7, 1.31),
    (2024, 112.9, 0.97, 126.3, 1.03),
    (2025, 109.8, 0.95, 241.5, 1.44),
]
WELLS = [("W-0001", 412.0), ("W-0002", 287.5), ("W-0003", 655.2)]  # EUR, Mbbl oil


def reliability_rows() -> list[dict]:
    rows = []
    for year, s_ex, f_ex, s_in, f_in in RELIABILITY:
        for basis, saidi, saifi in (("excl_med", s_ex, f_ex), ("incl_med", s_in, f_in)):
            rows += [
                {"year": year, "basis": basis, "metric": "saidi", "value": saidi, "unit": "min"},
                {"year": year, "basis": basis, "metric": "saifi", "value": saifi, "unit": "interruptions"},
                {"year": year, "basis": basis, "metric": "caidi", "value": round(saidi / saifi, 1), "unit": "min"},
            ]
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUT_DIR / "reliability_annual.csv", reliability_rows())
    manifest = {"run_id": "rel-2025-eval", "skill": "reliability-metrics", "version": "0.1.0",
                "decisions": {"med_method": "ieee1366_2.5beta", "t_med_min": 9.84,
                              "med_dates_2025": ["2025-06-14", "2025-06-15"]}}
    (OUT_DIR / "reliability_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_csv(OUT_DIR / "decline_summary.csv",
              [{"well_id": w, "eur_mbbl": e, "model": "modified_hyperbolic", "b_max": 1.2,
                "d_min_pct_per_yr": 8.0, "category": "technical_forecast"} for w, e in WELLS])
    print(json.dumps({"saidi_2025_excl_med_min": 109.8, "saidi_2025_incl_med_min": 241.5,
                      "med_days_2025": 2, "total_eur_mbbl": round(sum(e for _, e in WELLS), 1)}))


if __name__ == "__main__":
    main()
