"""Entrypoints the agent calls: read-only preview, then confirmed wildfire risk build.

Purpose
    preview_wildfire_risk         READ-ONLY. Coverage profile, coordinate checks, how the
                                  top-N ranking moves under example weightings, and how many
                                  circuits candidate PSPS thresholds would flag.
    build_confirmed_wildfire_risk Requires likelihood_weights and consequence_basis (and
                                  psps_thresholds / mitigation_assumptions when those outputs
                                  are requested). Returns segment risk, circuit roll-up, PSPS
                                  candidates, mitigation plan, a coarse shareable view, and a
                                  run manifest.

Usage
    import sys; sys.path.append("<skill-dir>/scripts")
    from wildfire_api import preview_wildfire_risk, build_confirmed_wildfire_risk
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from h3grid import BACKEND, parent, ring_radius_km
from wildfire_core import (
    check_coordinates,
    plan_mitigation,
    psps_candidates,
    score_segments,
    segment_cells,
)

SKILL_NAME = "wildfire-asset-risk"
SKILL_VERSION = "0.1.0"
SHAREABLE_RES = 7
EXAMPLE_WEIGHTINGS = {
    "equal": {"vegetation": 0.25, "fuel": 0.25, "slope": 0.25, "ignition_history": 0.25},
    "vegetation_led": {"vegetation": 0.5, "fuel": 0.2, "slope": 0.1, "ignition_history": 0.2},
    "history_led": {"vegetation": 0.2, "fuel": 0.2, "slope": 0.1, "ignition_history": 0.5},
}
EXAMPLE_PSPS = ({"wind_gust_mph": 40, "rh_pct": 25}, {"wind_gust_mph": 45, "rh_pct": 30},
                {"wind_gust_mph": 50, "rh_pct": 20})


def _coverage(cells: pd.DataFrame, layers: dict) -> dict:
    total = cells["cell"].nunique()
    return {name: round(cells["cell"].isin(set(layers[name]["cell"])).sum() / len(cells), 3)
            for name in ("vegetation", "fuel", "slope", "exposure") if name in layers} | {
        "segment_cells": int(total)}


def _top_overlap(rankings: dict, n: int) -> pd.DataFrame:
    tops = {k: set(v.nsmallest(n, "risk_rank")["segment_id"]) for k, v in rankings.items()}
    names = list(tops)
    rows = [{"a": a, "b": b, f"top{n}_overlap": len(tops[a] & tops[b]) / max(n, 1)}
            for i, a in enumerate(names) for b in names[i + 1:]]
    return pd.DataFrame(rows)


def preview_wildfire_risk(segments: pd.DataFrame, layers: dict, res: int, buffer_k: int,
                          forecast: pd.DataFrame | None = None, top_n: int = 20,
                          cells: pd.DataFrame | None = None) -> dict:
    """READ-ONLY: profile inputs and show sensitivity to the decisions. Builds nothing.

    `cells` may be precomputed (segment_id, cell) pairs, e.g. from Databricks h3_coverash3.
    """
    problems = check_coordinates(segments)
    if problems:
        return {"ok": False, "problems": problems, "readout": "\n".join(problems)}
    cells = cells if cells is not None else segment_cells(segments, res)
    rankings = {name: score_segments(cells, segments, layers, w, "structures_and_population",
                                     buffer_k) for name, w in EXAMPLE_WEIGHTINGS.items()}
    overlap = _top_overlap(rankings, min(top_n, len(segments)))
    psps = []
    if forecast is not None:
        psps = [{**t, "circuits_flagged": len(psps_candidates(cells, segments, forecast, t))}
                for t in EXAMPLE_PSPS]
    readout = _preview_readout(segments, cells, layers, res, buffer_k, overlap, psps)
    return {"ok": True, "coverage": _coverage(cells, layers), "ranking_overlap": overlap,
            "psps_sensitivity": pd.DataFrame(psps), "readout": readout}


def _preview_readout(segments, cells, layers, res, k, overlap, psps) -> str:
    lines = [
        "Wildfire risk preview — READ-ONLY, nothing built.",
        f"  segments: {len(segments):,}  grid cells touched: {cells['cell'].nunique():,}"
        f"  (res {res}, buffer k={k} ≈ {ring_radius_km(res, k):.2f} km, backend {BACKEND})",
        f"  layer coverage of segment cells: {_coverage(cells, layers)}",
        "", "How much the top-ranked segments change with the weighting:",
        overlap.to_string(index=False),
        "", "Decisions needed (no defaults):",
        "  1. likelihood_weights over vegetation, fuel, slope, ignition_history (sum to 1)",
        "  2. consequence_basis: 'structures', 'population', or 'structures_and_population'",
        "  3. psps_thresholds (if screening PSPS): wind_gust_mph, rh_pct [, ffwi]",
        "  4. mitigation_assumptions (if planning): effectiveness + cost_per_mile_usd per option",
    ]
    if psps:
        lines += ["", "Circuits flagged under example PSPS thresholds (illustrative only):",
                  pd.DataFrame(psps).to_string(index=False)]
    return "\n".join(lines)


def build_confirmed_wildfire_risk(segments: pd.DataFrame, layers: dict, res: int,
                                  buffer_k: int, *, likelihood_weights, consequence_basis,
                                  psps_thresholds=None, forecast: pd.DataFrame | None = None,
                                  mitigation_assumptions: pd.DataFrame | None = None,
                                  budget_usd: float | None = None,
                                  circuit_customers: pd.DataFrame | None = None,
                                  source_tables: dict | None = None,
                                  cells: pd.DataFrame | None = None) -> dict:
    """Score, screen and plan under the user's confirmed decisions."""
    problems = check_coordinates(segments)
    if problems:
        raise ValueError("Segment coordinates failed validation: " + "; ".join(problems))
    cells = cells if cells is not None else segment_cells(segments, res)
    scored = score_segments(cells, segments, layers, likelihood_weights, consequence_basis,
                            buffer_k)
    psps = (psps_candidates(cells, segments, forecast, psps_thresholds, circuit_customers)
            if forecast is not None else None)
    plan = (plan_mitigation(scored, mitigation_assumptions, budget_usd)
            if budget_usd is not None else None)
    decisions = {"likelihood_weights": likelihood_weights, "consequence_basis": consequence_basis,
                 "psps_thresholds": psps_thresholds,
                 "mitigation_assumptions": None if mitigation_assumptions is None
                 else mitigation_assumptions.to_dict("records"), "budget_usd": budget_usd}
    return {
        "segment_risk": scored, "circuit_risk": circuit_rollup(scored),
        "psps_candidates": psps, "mitigation_plan": plan,
        "shareable_cells": shareable_view(cells, scored),
        "manifest": _manifest(decisions, res, buffer_k, segments, source_tables),
        "readout": _build_readout(scored, psps, plan),
    }


def circuit_rollup(scored: pd.DataFrame) -> pd.DataFrame:
    """Circuit risk = sum of segment risk; also risk per mile (length-weighted)."""
    out = scored.groupby("circuit_id").agg(risk=("risk", "sum"), miles=("length_mi", "sum"),
                                           segments=("segment_id", "nunique"))
    return out.assign(risk_per_mile=out["risk"] / out["miles"]).sort_values(
        "risk", ascending=False).reset_index()


def shareable_view(cells: pd.DataFrame, scored: pd.DataFrame) -> pd.DataFrame:
    """Risk aggregated to coarse cells with no asset ids or coordinates (CEII-safer)."""
    seg_risk = scored.set_index("segment_id")["risk"]
    coarse = cells.assign(coarse_cell=cells["cell"].map(lambda c: parent(c, SHAREABLE_RES)))
    per = coarse.drop_duplicates(["segment_id", "coarse_cell"]).assign(
        risk=lambda d: d["segment_id"].map(seg_risk))
    return per.groupby("coarse_cell", as_index=False).agg(
        max_risk=("risk", "max"), segments=("segment_id", "nunique"))


def _manifest(decisions: dict, res: int, k: int, segments: pd.DataFrame,
              source_tables: dict | None) -> dict:
    return {"skill": SKILL_NAME, "skill_version": SKILL_VERSION,
            "run_at_utc": datetime.now(timezone.utc).isoformat(),
            "grid": {"backend": BACKEND, "resolution": res, "buffer_k": k,
                     "buffer_km_approx": ring_radius_km(res, k)},
            "decisions": decisions,
            "inputs": {**(source_tables or {}), "segments": int(len(segments))}}


def _build_readout(scored: pd.DataFrame, psps, plan) -> str:
    top = scored.head(10)[["segment_id", "circuit_id", "likelihood", "consequence", "risk"]]
    lines = ["Wildfire segment risk — top 10:", top.to_string(index=False)]
    if psps is not None:
        lines += ["", f"PSPS candidate circuits: {len(psps)}",
                  psps.head(10).to_string(index=False)]
    if plan is not None:
        chosen = plan.loc[plan["selected"]]
        lines += ["", f"Mitigation plan: {len(chosen)} segments, "
                  f"${chosen['cost_usd'].sum():,.0f}, risk reduced "
                  f"{chosen['risk_reduction'].sum():.3f} (greedy by RSE, not an optimal solve)."]
    lines.append("Coordinates and segment ids are CEII-sensitive: share `shareable_cells` only.")
    return "\n".join(lines)
