#!/usr/bin/env python3
"""Seed synthetic data for energy-accelerators eval task ea-001 (no real wells).

Writes $SKILL_EVAL_DATA_DIR/permian_monthly_production.csv (default ./eval_data):
24 synthetic wells with hyperbolic decline, API-like IDs prefixed 'SYN-' so they can never
be mistaken for real API numbers. The other tasks need no data.

Usage:
    SKILL_EVAL_DATA_DIR=/Volumes/<catalog>/energy_skills/eval/energy_accelerators python3 generate_data.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261028
OUT = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "eval_data"))


def well_rows(i: int, rng: np.random.Generator) -> pd.DataFrame:
    months = pd.period_range("2022-01", "2026-09", freq="M")
    t = np.arange(len(months))
    qi, di, b = rng.uniform(600, 1400), rng.uniform(0.08, 0.2), rng.uniform(0.6, 1.2)
    oil = qi / (1 + b * di * t) ** (1 / b) * 30.4 * rng.normal(1, 0.05, len(t))
    return pd.DataFrame({"well_id": f"SYN-42-{i:05d}", "month": months.astype(str),
                         "oil_bbl": oil.round(1), "gas_mcf": (oil * rng.uniform(1.5, 3.0)).round(1),
                         "days_on": np.minimum(30, rng.integers(26, 32, len(t)))})


def main() -> None:
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.concat([well_rows(i, rng) for i in range(24)], ignore_index=True)
    df.to_csv(OUT / "permian_monthly_production.csv", index=False)
    print(f"wrote {len(df)} rows to {OUT.resolve()}")


if __name__ == "__main__":
    main()
