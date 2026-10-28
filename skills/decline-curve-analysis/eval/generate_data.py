"""Seeded planted-truth data for the decline-curve-analysis benchmark.

Wells follow a known modified-hyperbolic curve with a 2-3 month cleanup ramp, random
downtime (days_on < calendar days), shut-in months, workover spikes, and lognormal noise.
Task inputs go to $SKILL_EVAL_DATA_DIR/task_00N/; truth goes to $SKILL_EVAL_DATA_DIR/_answer_key/
(never upload _answer_key to the agent's volume).

    SKILL_EVAL_DATA_DIR=/tmp/dca-eval python3 eval/generate_data.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from dca_models import (  # noqa: E402
    DAYS_PER_YEAR,
    hyperbolic_cum,
    modified_cum,
    modified_rate,
    secant_to_nominal,
    terminal_effective_to_nominal,
    time_to_rate,
)

SEED, ECON, LIFE, D_MIN = 20261028, 5.0, 50.0, 0.08


def _well(rng: np.random.Generator, api: str, months: int, artefacts: bool) -> tuple[pd.DataFrame, dict]:
    qi, di, b = rng.uniform(500, 1400), rng.uniform(2.0, 5.0), rng.uniform(1.0, 1.4)
    ramp = int(rng.integers(2, 4))
    dates = pd.date_range("2021-01-01", periods=months, freq="MS")
    d_lim = terminal_effective_to_nominal(D_MIN)
    t = ((dates - dates[ramp]).days + dates.days_in_month / 2) / DAYS_PER_YEAR
    rate = np.asarray(modified_rate(np.clip(t, 0, None), qi, di, b, d_lim))
    rate[:ramp] = qi * np.linspace(0.3, 0.8, ramp)
    cal = dates.days_in_month.to_numpy().astype(float)
    days_on = cal.copy()
    if artefacts:
        for idx in rng.choice(np.arange(ramp + 1, months), size=4, replace=False):
            days_on[idx] = float(rng.integers(5, 25))
    volume = rate * days_on * np.exp(rng.normal(0, 0.04, months))
    if artefacts:
        shut = int(rng.integers(ramp + 6, months - 3))
        volume[shut], days_on[shut] = 0.0, 0.0
        volume[shut + 2] *= 2.5                       # flush production / allocation spike
    true_hist = volume.sum()                          # reported history is truth to date
    t_last = ((dates[-1] - dates[ramp]).days + cal[-1]) / DAYS_PER_YEAR
    t_end = min(time_to_rate(ECON, qi, di, b, d_lim), LIFE - (dates[ramp] - dates[0]).days / DAYS_PER_YEAR)
    remaining = float(modified_cum(t_end, qi, di, b, d_lim) - modified_cum(t_last, qi, di, b, d_lim)) * DAYS_PER_YEAR
    frame = pd.DataFrame({"api14": api, "prod_month": dates.date, "oil_bbl": volume.round(1), "days_on": days_on})
    return frame, {"qi": qi, "di": di, "b": b, "eur_bbl": float(true_hist + max(remaining, 0.0))}


def _field(rng, n: int, prefix: str, artefacts: bool) -> tuple[pd.DataFrame, dict, dict]:
    frames, truth, laterals = [], {}, {}
    for i in range(n):
        api = f"42{prefix}{i:05d}0000"
        frame, t = _well(rng, api, months=int(rng.integers(30, 60)), artefacts=artefacts)
        lateral = float(rng.uniform(6000, 12500))
        scale = lateral / 10_000.0
        frame = frame.assign(oil_bbl=(frame["oil_bbl"] * scale).round(1))
        truth[api] = {**t, "eur_bbl": t["eur_bbl"] * scale, "lateral_ft": lateral}
        laterals[api] = lateral
        frames.append(frame)
    return pd.concat(frames, ignore_index=True), truth, laterals


def main() -> None:
    root = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/dca-eval"))
    rng = np.random.default_rng(SEED)
    key: dict = {}

    prod, truth, _ = _field(rng, 30, "329", artefacts=True)
    (root / "task_001").mkdir(parents=True, exist_ok=True)
    prod.to_csv(root / "task_001" / "monthly_production.csv", index=False)
    key["dca-001"] = {"total_eur_bbl": sum(v["eur_bbl"] for v in truth.values()), "wells": truth}

    prod, truth, laterals = _field(rng, 40, "317", artefacts=False)
    headers = pd.DataFrame({"api14": list(laterals), "lateral_ft": list(laterals.values())})
    headers.loc[[3, 17], "lateral_ft"] = np.nan
    (root / "task_002").mkdir(parents=True, exist_ok=True)
    prod.to_csv(root / "task_002" / "monthly_production.csv", index=False)
    headers.to_csv(root / "task_002" / "well_headers.csv", index=False)
    usable = [v["eur_bbl"] / v["lateral_ft"] * 1e4 for i, v in enumerate(truth.values()) if i not in (3, 17)]
    key["dca-002"] = {"p50_eur_per_10k_ft": float(np.median(usable)),
                      "p10_high_eur_per_10k_ft": float(np.quantile(usable, 0.9)),
                      "p90_low_eur_per_10k_ft": float(np.quantile(usable, 0.1)),
                      "wells_missing_lateral": [headers.api14[3], headers.api14[17]]}

    di = secant_to_nominal(0.72, 1.2)
    key["dca-004"] = {"di_nominal_per_yr": di,
                      "first_year_cum_bbl": float(hyperbolic_cum(1.0, 1000.0, di, 1.2)) * DAYS_PER_YEAR}

    (root / "_answer_key").mkdir(parents=True, exist_ok=True)
    (root / "_answer_key" / "truth.json").write_text(json.dumps(key, indent=2, default=float))
    print(f"Wrote tasks to {root}; answer key to {root / '_answer_key' / 'truth.json'}")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "wells"} for k, v in key.items()}, indent=2))


if __name__ == "__main__":
    main()
