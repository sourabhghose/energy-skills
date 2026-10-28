"""Seeded synthetic wildfire inputs with planted truth for the wildfire-asset-risk eval.

Task data -> $SKILL_EVAL_DATA_DIR (default /tmp/wildfire-eval); answer key ->
$SKILL_EVAL_KEY_DIR (default <data_dir>_answer_key). Layers are keyed by grid cell
from scripts/h3grid.py (real H3 when the `h3` package is installed).

Planted traps
    * SPAN1: a long span whose two pole cells are benign but whose conductor crosses a
      hazardous, populated pocket. Pole-only indexing ranks it low.
    * Forecast for wf-002 is in degrees C and km/h; the protocol is in F / mph / %RH.
    * Circuit Z meets the weather thresholds but has no high fire-threat district tier.
    * wf-004 segments have lat/lon swapped on 3 rows.

    python3 eval/generate_data.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from h3grid import BACKEND, cell_for  # noqa: E402
from wildfire_api import build_confirmed_wildfire_risk  # noqa: E402
from wildfire_core import segment_cells  # noqa: E402

SEED, RES, K = 4242, 9, 1
LAT0, LON0 = 39.70, -121.60
WEIGHTS = {"vegetation": 0.35, "fuel": 0.30, "slope": 0.10, "ignition_history": 0.25}
PSPS = {"wind_gust_mph": 45, "rh_pct": 20}
MITIGATIONS = pd.DataFrame({"mitigation": ["covered_conductor", "undergrounding", "enhanced_veg"],
                            "effectiveness": [0.65, 0.97, 0.30],
                            "cost_per_mile_usd": [800_000.0, 4_000_000.0, 60_000.0]})
BUDGET = 300_000.0


def network(rng) -> pd.DataFrame:
    rows = []
    for c, circuit in enumerate("PQRSTZ"):
        tier = None if circuit == "Z" else ("Tier 3" if c % 2 else "Tier 2")
        for s in range(8):
            lat, lon = LAT0 + c * 0.02, LON0 + s * 0.006
            rows.append({"segment_id": f"{circuit}{s}", "circuit_id": circuit, "lat1": lat,
                         "lon1": lon, "lat2": lat + float(rng.normal(0, 0.001)),
                         "lon2": lon + 0.006, "hftd_tier": tier})
    rows.append({"segment_id": "SPAN1", "circuit_id": "R", "lat1": LAT0 + 0.13, "lon1": LON0,
                 "lat2": LAT0 + 0.13, "lon2": LON0 + 0.03, "hftd_tier": "Tier 3"})
    return pd.DataFrame(rows)


def layers(rng, segs: pd.DataFrame) -> dict:
    cells = segment_cells(segs, RES)["cell"].unique()
    veg = pd.DataFrame({"cell": cells, "veg_strike_index": rng.uniform(0.05, 0.5, len(cells))})
    fuel = pd.DataFrame({"cell": cells, "fbfm40": rng.choice(["GR2", "TL3", "TU1", "NB1"], len(cells))})
    slope = pd.DataFrame({"cell": cells, "slope_deg": rng.uniform(0, 15, len(cells))})
    expo = pd.DataFrame({"cell": cells, "structures": rng.integers(0, 6, len(cells)),
                         "population": rng.integers(0, 15, len(cells))})
    pocket = _span_interior(segs)
    hot = veg["cell"].isin(pocket)
    return {"vegetation": veg.assign(veg_strike_index=np.where(hot, 0.95, veg["veg_strike_index"])),
            "fuel": fuel.assign(fbfm40=np.where(fuel["cell"].isin(pocket), "SH7", fuel["fbfm40"])),
            "slope": slope.assign(slope_deg=np.where(slope["cell"].isin(pocket), 35.0, slope["slope_deg"])),
            "ignitions": pd.DataFrame({"cell": list(pocket)[:2], "n_ignitions": [2, 1]}),
            "exposure": expo.assign(structures=np.where(expo["cell"].isin(pocket), 300, expo["structures"]),
                                    population=np.where(expo["cell"].isin(pocket), 900, expo["population"]))}


def _span_interior(segs: pd.DataFrame) -> set:
    span = segs.loc[segs["segment_id"] == "SPAN1"].iloc[0]
    ends = {cell_for(span.lat1, span.lon1, RES), cell_for(span.lat2, span.lon2, RES)}
    ends |= {cell_for(span.lat1, span.lon1 + 0.003, RES), cell_for(span.lat2, span.lon2 - 0.003, RES)}
    inner = set(segment_cells(segs.loc[segs["segment_id"] == "SPAN1"], RES)["cell"]) - ends
    return set(sorted(inner)[len(inner) // 3: 2 * len(inner) // 3 + 1])


def forecast(segs: pd.DataFrame) -> pd.DataFrame:
    cells = segment_cells(segs.loc[segs["circuit_id"].isin(["Q", "T", "Z"])], RES)["cell"].unique()
    hours = pd.date_range("2025-10-14 18:00", periods=12, freq="h", tz="America/Los_Angeles")
    rows = [{"cell": c, "valid_ts": h, "wind_gust_mph": 52.0, "wind_sustained_mph": 30.0,
             "rh_pct": 12.0, "temp_f": 88.0} for c in cells for h in hours]
    return pd.DataFrame(rows)


def to_metric_units(fc: pd.DataFrame) -> pd.DataFrame:
    """The task file: deg C and km/h, as many weather vendors deliver."""
    return pd.DataFrame({"cell": fc["cell"], "valid_ts": fc["valid_ts"].map(lambda t: t.isoformat()),
                         "wind_gust_kmh": fc["wind_gust_mph"] * 1.609344,
                         "wind_sustained_kmh": fc["wind_sustained_mph"] * 1.609344,
                         "rh_pct": fc["rh_pct"], "temp_c": (fc["temp_f"] - 32) / 1.8})


def write_task(folder: Path, segs: pd.DataFrame, lyr: dict, extra: dict | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    segs.to_csv(folder / "oh_segments.csv", index=False)
    for name, df in {**lyr, **(extra or {})}.items():
        df.to_csv(folder / f"{name}_h3.csv", index=False)


def main() -> int:
    data_dir = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/wildfire-eval"))
    key_dir = Path(os.environ.get("SKILL_EVAL_KEY_DIR", f"{data_dir}_answer_key"))
    rng = np.random.default_rng(SEED)
    segs = network(rng)
    lyr = layers(rng, segs)
    fc = forecast(segs)
    res = build_confirmed_wildfire_risk(segs, lyr, RES, K, likelihood_weights=WEIGHTS,
                                        consequence_basis="structures_and_population",
                                        psps_thresholds=PSPS, forecast=fc,
                                        mitigation_assumptions=MITIGATIONS, budget_usd=BUDGET)
    swapped = segs.copy()
    swapped.loc[:2, ["lat1", "lon1"]] = swapped.loc[:2, ["lon1", "lat1"]].to_numpy()
    write_task(data_dir / "task_001", segs, lyr)
    write_task(data_dir / "task_002", segs, lyr, {"forecast": to_metric_units(fc)})
    write_task(data_dir / "task_003", segs, lyr)
    write_task(data_dir / "task_004", swapped, lyr)
    write_task(data_dir / "task_005", segs, lyr)
    plan = res["mitigation_plan"]
    truth = {"grid_backend": BACKEND, "resolution": RES, "buffer_k": K, "weights": WEIGHTS,
             "top5_segments": res["segment_risk"].head(5)["segment_id"].tolist(),
             "span1_rank": int(res["segment_risk"].set_index("segment_id").loc["SPAN1", "risk_rank"]),
             "psps_circuits": sorted(res["psps_candidates"]["circuit_id"]),
             "selected_segments": sorted(plan.loc[plan["selected"], "segment_id"]),
             "selected_cost_usd": float(plan.loc[plan["selected"], "cost_usd"].sum()),
             "swapped_segment_ids": swapped.loc[:2, "segment_id"].tolist()}
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote task data to {data_dir} and answer key to {key_dir} (grid {BACKEND})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
