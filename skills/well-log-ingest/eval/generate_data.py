"""Seeded synthetic LAS 2.0 files with planted ingestion traps for the well-log-ingest benchmark.

Traps: density in kg/m3, neutron in percent labelled V/V or blank, sonic in us/m, -9999
sentinels besides the header NULL, Colorado API numbers with a lost leading zero, KB vs GL
datum, overlapping logging runs, and a metric file whose user asks for TVDSS (impossible
without a survey). Inputs go to $SKILL_EVAL_DATA_DIR/task_00N/; truth to _answer_key/.

    SKILL_EVAL_DATA_DIR=/tmp/wli-eval python3 eval/generate_data.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

SEED = 20261028


def _las(well: dict, curves: list[tuple[str, str, str]], data: np.ndarray, depth_unit: str = "F") -> str:
    head = ["~Version Information", " VERS.   2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0",
            " WRAP.   NO  : ONE LINE PER DEPTH STEP", "~Well Information",
            f" STRT.{depth_unit} {data[0, 0]:.4f} : START DEPTH", f" STOP.{depth_unit} {data[-1, 0]:.4f} : STOP DEPTH",
            f" STEP.{depth_unit} {data[1, 0] - data[0, 0]:.4f} : STEP", " NULL.  -999.25 : NULL VALUE"]
    head += [f" {k:4s}.{u:3s} {v} : {d}" for k, u, v, d in well["items"]]
    head.append("~Curve Information")
    head += [f" {m:5s}.{u:5s} : {d}" for m, u, d in curves]
    head.append("~ASCII")
    rows = [" ".join(f"{v:10.4f}" for v in row) for row in data]
    return "\n".join(head + rows) + "\n"


def _well_items(api: str, name: str, ekb: float, egl: float, date: str, unit: str = "F") -> dict:
    return {"items": [("COMP", "", "EVAL ENERGY", "COMPANY"), ("WELL", "", name, "WELL"),
                      ("API", "", api, "API NUMBER"), ("DATE", "", date, "LOG DATE"),
                      ("EKB", unit, f"{ekb:.1f}", "KB ELEVATION"), ("EGL", unit, f"{egl:.1f}", "GL ELEVATION"),
                      ("LMF", "", "KB", "LOG MEASURED FROM")]}


def _logs(rng, depth: np.ndarray) -> dict[str, np.ndarray]:
    n = depth.size
    shale = (np.sin(depth / 37.0) > 0.2).astype(float)
    return {"GR": 30 + 90 * shale + rng.normal(0, 5, n),
            "RHOB": 2.35 + 0.2 * shale + rng.normal(0, 0.02, n),
            "NPHI": 0.12 + 0.18 * shale + rng.normal(0, 0.01, n),
            "DT": 70 + 25 * shale + rng.normal(0, 2, n)}


def task_001(root: Path, rng) -> dict:
    out, truth = root / "task_001", {}
    out.mkdir(parents=True, exist_ok=True)
    wells = [("0512345678", "512345679", "512345680"), ("42-317-40001", "42-317-40002", "42-317-40003")]
    for i, api in enumerate([a for group in wells for a in group]):
        ekb, egl = 5100.0 + 10 * i, 5075.0 + 10 * i
        depth = np.arange(7000.0, 7400.0, 0.5)
        logs = _logs(rng, depth)
        vendor = i % 3
        gr = logs["GR"].copy()
        gr[rng.choice(depth.size, 15, replace=False)] = -9999.0
        if vendor == 0:
            curves = [("DEPT", "F", "DEPTH"), ("GR", "GAPI", "GAMMA"), ("RHOB", "G/C3", "DENSITY"),
                      ("NPHI", "V/V", "NEUTRON"), ("DT", "US/F", "SONIC")]
            data = np.column_stack([depth, gr, logs["RHOB"], logs["NPHI"], logs["DT"]])
        elif vendor == 1:
            curves = [("DEPT", "F", "DEPTH"), ("GR", "GAPI", "GAMMA"), ("RHOZ", "K/M3", "DENSITY"),
                      ("TNPH", "V/V", "NEUTRON"), ("DTCO", "US/M", "SONIC")]
            data = np.column_stack([depth, gr, logs["RHOB"] * 1000, logs["NPHI"] * 100, logs["DT"] / 0.3048])
        else:
            curves = [("DEPT", "F", "DEPTH"), ("GR", "GAPI", "GAMMA"), ("ZDEN", "G/CC", "DENSITY"),
                      ("NPOR", "", "NEUTRON"), ("AC", "US/F", "SONIC")]
            data = np.column_stack([depth, gr, logs["RHOB"], logs["NPHI"] * 100, logs["DT"]])
        name = f"EVAL {i + 1}H"
        (out / f"well_{i + 1}.las").write_text(_las(_well_items(api, name, ekb, egl, "2024-05-01"), curves, data))
        digits = api.replace("-", "")
        norm = ("0" + digits if len(digits) == 9 else digits).ljust(14, "0")
        valid = gr != -9999.0
        truth[norm] = {"top_depth_ft_below_gl": 7000.0 - (ekb - egl), "mean_rhob_gcc": float(logs["RHOB"].mean()),
                       "mean_nphi_vv": float(logs["NPHI"].mean()), "mean_dt_usft": float(logs["DT"].mean()),
                       "mean_gr_gapi": float(gr[valid].mean())}
    return truth


def task_002(root: Path, rng) -> dict:
    out = root / "task_002"
    out.mkdir(parents=True, exist_ok=True)
    runs = [(np.arange(6000.0, 6600.0, 0.5), "2022-02-10"), (np.arange(6400.0, 7200.0, 0.5), "2024-09-15")]
    overlap_means = []
    for k, (depth, date) in enumerate(runs):
        gr = _logs(rng, depth)["GR"] + (25.0 if k == 1 else 0.0)        # newer tool reads 25 gAPI hotter
        curves = [("DEPT", "F", "DEPTH"), ("GR", "GAPI", "GAMMA")]
        items = _well_items("42-389-51234", "OVERLAP 1", 3000.0, 2978.0, date)
        (out / f"overlap_run{k + 1}.las").write_text(_las(items, curves, np.column_stack([depth, gr])))
        overlap_means.append(float(gr[(depth >= 6400) & (depth < 6600)].mean()))
    return {"overlap_interval_ft_kb": [6400, 6600], "gr_mean_in_overlap_latest_run": overlap_means[1],
            "gr_mean_in_overlap_earliest_run": overlap_means[0]}


def task_003(root: Path, rng) -> dict:
    out = root / "task_003"
    out.mkdir(parents=True, exist_ok=True)
    depth = np.arange(2500.0, 2800.0, 0.1524)
    logs = _logs(rng, depth / 0.3048)
    items = _well_items("100/06-12-034-05W5/00", "HZ DEVIATED 1", 812.0, 805.0, "2023-11-20", unit="M")
    curves = [("DEPT", "M", "MEASURED DEPTH"), ("GR", "GAPI", "GAMMA"), ("RHOB", "G/C3", "DENSITY")]
    (out / "deviated_metric.las").write_text(_las(items, curves, np.column_stack([depth, logs["GR"], logs["RHOB"]]),
                                                  depth_unit="M"))
    (out / "README.txt").write_text("Horizontal well, landed at ~90 degrees inclination. No directional survey provided.\n")
    return {"tvdss_possible": False, "reason": "MD-only log in a deviated well; TVDSS needs a directional survey"}


def main() -> None:
    root = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/wli-eval"))
    rng = np.random.default_rng(SEED)
    key = {"wli-001": task_001(root, rng), "wli-002": task_002(root, rng), "wli-003": task_003(root, rng)}
    (root / "_answer_key").mkdir(parents=True, exist_ok=True)
    (root / "_answer_key" / "truth.json").write_text(json.dumps(key, indent=2))
    print(f"Wrote tasks to {root}; answer key to {root / '_answer_key' / 'truth.json'}")


if __name__ == "__main__":
    main()
