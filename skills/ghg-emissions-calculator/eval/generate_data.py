"""Seeded synthetic activity data for the ghg-emissions-calculator benchmark.

Writes one folder per task under $SKILL_EVAL_DATA_DIR (default /tmp/energy-skills-eval/ghg).
Planted truth is computed here with independent arithmetic (not the skill's code) and checked
against expectations.json with --check.

    python eval/generate_data.py            # write data
    python eval/generate_data.py --check    # also assert planted truth == expectations.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20251028
OUT = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/energy-skills-eval/ghg"))
HERE = Path(__file__).resolve().parent
LB = 0.45359237 / 1000  # tonnes per lb


def task_001(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """Combustion + purchased electricity with RECs: needs dual Scope 2."""
    gas_mcf = rng.integers(800, 1200, size=12).astype(float)
    rows = [{"facility_id": "PLANT-A", "period": f"2025-{m:02d}", "source_type": "stationary_combustion",
             "fuel_or_product": "natural_gas", "quantity": q, "unit": "Mcf", "operational_control": True}
            for m, q in enumerate(gas_mcf, 1)]
    rows.append({"facility_id": "PLANT-A", "period": "2025", "source_type": "purchased_electricity",
                 "fuel_or_product": "electricity", "quantity": 5_000_000.0, "unit": "kWh",
                 "egrid_subregion": "ERCT", "rec_mwh": 2000.0, "operational_control": True})
    s1_co2 = gas_mcf.sum() * 1000 * 0.001026 * 53.06 / 1000
    truth = {"scope1_co2_t": round(s1_co2, 2), "scope2_location_t": round(5000 * 733.9 * LB, 2),
             "scope2_market_t": round(3000 * 823.81 * LB, 2)}
    return pd.DataFrame(rows), truth


def task_002(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """Flares + pneumatics; prompt asserts '98% flare efficiency' (retired for RY2025)."""
    vols = rng.uniform(5, 15, size=4).round(3)
    rows = [{"facility_id": f"PAD-{i}", "period": "2025", "source_type": "flare", "fuel_or_product": "flare_gas",
             "quantity": v, "unit": "MMscf", "ch4_mol_frac": 0.78, "co2_mol_frac": 0.03,
             "c2plus_mol_frac": 0.15, "c2plus_carbon_number": 2.6, "operational_control": True}
            for i, v in enumerate(vols, 1)]
    rows.append({"facility_id": "PAD-1", "period": "2025", "source_type": "pneumatic_device",
                 "fuel_or_product": "intermittent_bleed", "quantity": 0.0, "unit": "scf", "device_count": 40,
                 "operating_hours": 8760, "ch4_mol_frac": 0.78, "co2_mol_frac": 0.03, "operational_control": True})
    flare_scf = vols.sum() * 1e6
    truth = {f"flare_ch4_t_{k}": round(flare_scf * 0.78 * (1 - de) * 0.0192 / 1000, 3)
             for k, de in {"tier1": 0.98, "tier2": 0.95, "tier3": 0.92}.items()}
    truth["pneumatic_ch4_t"] = round(40 * 8760 * 13.5 * 0.78 * 0.0192 / 1000, 3)
    return pd.DataFrame(rows), truth


def task_003(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """JV portfolio: operated vs non-operated with working interests."""
    assets = [("OP-1", True, 0.60), ("OP-2", True, 1.00), ("NONOP-1", False, 0.25), ("NONOP-2", False, 0.40)]
    rows, op, eq = [], 0.0, 0.0
    for fac, operated, wi in assets:
        mmbtu = float(rng.integers(50_000, 150_000))
        rows.append({"facility_id": fac, "period": "2025", "source_type": "stationary_combustion",
                     "fuel_or_product": "natural_gas", "quantity": mmbtu, "unit": "mmBtu",
                     "operational_control": operated, "equity_share": wi})
        t = mmbtu * 53.06 / 1000
        op += t if operated else 0.0
        eq += t * wi
    truth = {"operational_control_co2_t": round(op, 2), "equity_share_co2_t": round(eq, 2)}
    return pd.DataFrame(rows), truth


def task_004(rng: np.random.Generator) -> tuple[pd.DataFrame, dict]:
    """Ambiguous units (m3) and a subregion without residual mix: must be flagged, not guessed."""
    rows = [
        {"facility_id": "TERM-1", "period": "2025", "source_type": "stationary_combustion",
         "fuel_or_product": "natural_gas", "quantity": float(rng.integers(20_000, 40_000)), "unit": "m3",
         "operational_control": True},
        {"facility_id": "TERM-1", "period": "2025", "source_type": "purchased_electricity",
         "fuel_or_product": "electricity", "quantity": 1200.0, "unit": "MWh", "egrid_subregion": "US",
         "operational_control": True},
    ]
    return pd.DataFrame(rows), {"scope2_location_t": round(1200 * 767.209 * LB, 2)}


TASKS = {"ghg-001": task_001, "ghg-002": task_002, "ghg-003": task_003, "ghg-004": task_004}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    expectations = {t["task_id"]: t for t in json.loads((HERE / "expectations.json").read_text())}
    for task_id, make in TASKS.items():
        df, truth = make(rng)
        folder = OUT / task_id
        folder.mkdir(parents=True, exist_ok=True)
        df.to_csv(folder / "activity.csv", index=False)
        if args.check:
            planted = expectations[task_id]["deterministic_checks"]["numeric_truth"]
            for key, value in truth.items():
                assert abs(planted[key] - value) < 1e-6, f"{task_id}.{key}: {planted[key]} != {value}"
        print(f"{task_id}: {len(df)} rows -> {folder}")


if __name__ == "__main__":
    main()
