"""Wildfire asset risk core: H3 joins, likelihood x consequence, PSPS screening, mitigation RSE.

Purpose
    Pure pandas / numpy. Indexes overhead line segments to grid cells (densified so long
    spans do not skip cells), joins hazard layers, scores ignition likelihood and exposure
    consequence with transparent user-supplied weights, screens PSPS candidate circuits
    against user-supplied weather thresholds, and ranks mitigations by risk-spend
    efficiency (risk reduced per $M) under a budget.

Usage
    from wildfire_core import segment_cells, score_segments, psps_candidates, plan_mitigation
    cells = segment_cells(segments, res=9)
    scored = score_segments(cells, segments, layers, weights, consequence_basis, buffer_k=2)

Input contract
    segments:  segment_id, circuit_id, lat1, lon1, lat2, lon2 [, hftd_tier]
    layers:    dict of DataFrames keyed by cell:
               vegetation(cell, veg_strike_index 0-1), fuel(cell, fbfm40 code),
               slope(cell, slope_deg), ignitions(cell, n_ignitions),
               exposure(cell, structures, population)
    forecast:  cell, valid_ts (tz-aware), wind_gust_mph, rh_pct, temp_f
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from fire_weather import fosberg_ffwi
from h3grid import cell_for, disk

LOG = logging.getLogger(__name__)
EARTH_RADIUS_M = 6_371_008.8
METERS_PER_MILE = 1609.344
LIKELIHOOD_COMPONENTS = ("vegetation", "fuel", "slope", "ignition_history")
CONSEQUENCE_OPTIONS = ("structures", "population", "structures_and_population")
SLOPE_SCALE_DEG = 45.0
IGNITION_CAP = 3.0
STRUCTURE_CAP = 1_000.0
POPULATION_CAP = 5_000.0

# LANDFIRE FBFM40 fuel-model family -> relative spread/intensity hazard (0-1).
# The family is the leading letters of the code (GR1, SH5, TU2, NB1 ...).
FUEL_FAMILY_HAZARD = {"NB": 0.0, "TL": 0.3, "TU": 0.6, "GR": 0.6, "GS": 0.75,
                      "SB": 0.85, "SH": 0.9}


class DecisionRequired(ValueError):
    """A decision that belongs to the wildfire risk owner was not supplied."""

    def __init__(self, decision: str, options, why: str):
        super().__init__(f"Decision required: '{decision}' ({options}). {why}")
        self.decision = decision
        self.options = options


# --------------------------------------------------------------------------- geometry

def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi, dlmb = p2 - p1, np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def check_coordinates(segments: pd.DataFrame) -> list[str]:
    """Data-quality problems: out-of-range or likely swapped lat/lon, zero-length spans."""
    problems = []
    for col in ("lat1", "lat2"):
        if (segments[col].abs() > 90).any():
            problems.append(f"{col} has |values| > 90: latitude and longitude look swapped")
    length = haversine_m(segments["lat1"], segments["lon1"], segments["lat2"], segments["lon2"])
    zero = int((length < 1.0).sum())
    if zero:
        problems.append(f"{zero} segment(s) have zero length")
    return problems


def segment_lengths_mi(segments: pd.DataFrame) -> pd.Series:
    meters = haversine_m(segments["lat1"], segments["lon1"], segments["lat2"], segments["lon2"])
    return pd.Series(meters / METERS_PER_MILE, index=segments.index)


def _densify(row, step_m: float) -> list[tuple[float, float]]:
    length = float(haversine_m(row.lat1, row.lon1, row.lat2, row.lon2))
    n = max(int(math.ceil(length / step_m)), 1)
    return [(row.lat1 + (row.lat2 - row.lat1) * i / n, row.lon1 + (row.lon2 - row.lon1) * i / n)
            for i in range(n + 1)]


def segment_cells(segments: pd.DataFrame, res: int, step_m: float | None = None) -> pd.DataFrame:
    """Unique (segment_id, cell) pairs; points every step_m along each span.

    Indexing only the span endpoints misses every cell the conductor crosses between
    poles. The default step is a third of the cell edge.
    """
    from h3grid import EDGE_KM

    step = step_m or EDGE_KM[res] * 1000.0 / 3.0
    rows = [(row.segment_id, cell_for(lat, lon, res))
            for row in segments.itertuples(index=False) for lat, lon in _densify(row, step)]
    return pd.DataFrame(rows, columns=["segment_id", "cell"]).drop_duplicates(ignore_index=True)


# --------------------------------------------------------------------------- scoring

def fuel_hazard(codes: pd.Series) -> pd.Series:
    """Map FBFM40 codes (e.g. 'GS2', 'NB1') to family hazard; unknown codes -> NaN."""
    family = codes.astype(str).str.upper().str.extract(r"^([A-Z]{2})", expand=False)
    return family.map(FUEL_FAMILY_HAZARD)


def validate_weights(weights) -> dict:
    if not weights:
        raise DecisionRequired("likelihood_weights", list(LIKELIHOOD_COMPONENTS),
                               "Weights decide which segments rank highest.")
    unknown = set(weights) - set(LIKELIHOOD_COMPONENTS)
    if unknown:
        raise ValueError(f"unknown likelihood components: {sorted(unknown)}")
    total = sum(weights.values())
    if not math.isclose(total, 1.0, abs_tol=1e-6) or min(weights.values()) < 0:
        raise ValueError(f"likelihood weights must be >= 0 and sum to 1 (got {total:.4f})")
    return {c: float(weights.get(c, 0.0)) for c in LIKELIHOOD_COMPONENTS}


def _cell_hazards(layers: dict) -> pd.DataFrame:
    """One row per cell with 0-1 hazard components on fixed physical scales."""
    veg = layers["vegetation"].set_index("cell")["veg_strike_index"].clip(0, 1)
    fuel = layers["fuel"].assign(h=lambda d: fuel_hazard(d["fbfm40"])).set_index("cell")["h"]
    slope = (layers["slope"].set_index("cell")["slope_deg"] / SLOPE_SCALE_DEG).clip(0, 1)
    return pd.concat({"vegetation": veg, "fuel": fuel, "slope": slope}, axis=1)


def _buffer_sum(cells: pd.DataFrame, table: pd.DataFrame, cols: list[str], k: int) -> pd.DataFrame:
    """Sum `cols` of `table` over each segment's cells plus k rings (no double counting)."""
    ring = [(s, n) for s, c in cells.itertuples(index=False) for n in disk(c, k)]
    near = pd.DataFrame(ring, columns=["segment_id", "cell"]).drop_duplicates()
    joined = near.merge(table, on="cell", how="left").fillna({c: 0.0 for c in cols})
    return joined.groupby("segment_id")[cols].sum()


def segment_likelihood(cells: pd.DataFrame, layers: dict, weights: dict, k: int) -> pd.DataFrame:
    """Per-segment components (max over cells) and weighted likelihood."""
    hazards = cells.merge(_cell_hazards(layers), left_on="cell", right_index=True, how="left")
    comp = hazards.groupby("segment_id")[["vegetation", "fuel", "slope"]].max()
    missing = comp.isna().any(axis=1)
    ign = _buffer_sum(cells, layers["ignitions"], ["n_ignitions"], k)
    comp = comp.assign(ignition_history=(ign["n_ignitions"] / IGNITION_CAP).clip(0, 1))
    w = validate_weights(weights)
    score = sum(comp[c].fillna(0.0) * w[c] for c in LIKELIHOOD_COMPONENTS)
    return comp.assign(likelihood=score, missing_hazard_data=missing)


def segment_consequence(cells: pd.DataFrame, exposure: pd.DataFrame, basis: str,
                        k: int) -> pd.DataFrame:
    """Exposure within k rings, log-scaled to 0-1 on fixed caps."""
    if basis not in CONSEQUENCE_OPTIONS:
        raise DecisionRequired("consequence_basis", CONSEQUENCE_OPTIONS,
                               "Which exposure the risk metric protects.")
    near = _buffer_sum(cells, exposure, ["structures", "population"], k)
    s = np.log1p(near["structures"]) / math.log1p(STRUCTURE_CAP)
    p = np.log1p(near["population"]) / math.log1p(POPULATION_CAP)
    value = {"structures": s, "population": p,
             "structures_and_population": (s + p) / 2.0}[basis].clip(0, 1)
    return near.assign(consequence=value)


def score_segments(cells: pd.DataFrame, segments: pd.DataFrame, layers: dict, weights: dict,
                   consequence_basis: str, buffer_k: int) -> pd.DataFrame:
    """Risk = likelihood x consequence per segment, with rank and length."""
    lik = segment_likelihood(cells, layers, weights, buffer_k)
    con = segment_consequence(cells, layers["exposure"], consequence_basis, buffer_k)
    base = segments.assign(length_mi=segment_lengths_mi(segments)).set_index("segment_id")
    keep = [c for c in ("circuit_id", "hftd_tier", "length_mi") if c in base.columns]
    out = base[keep].join(lik).join(con)
    out = out.assign(risk=out["likelihood"] * out["consequence"])
    return out.assign(risk_rank=out["risk"].rank(ascending=False, method="first").astype(int))\
        .sort_values("risk_rank").reset_index()


# --------------------------------------------------------------------------- PSPS

def validate_psps_thresholds(thresholds) -> dict:
    required = ("wind_gust_mph", "rh_pct")
    if not thresholds or any(k not in thresholds for k in required):
        raise DecisionRequired("psps_thresholds", {"wind_gust_mph": "...", "rh_pct": "...",
                                                   "ffwi (optional)": "..."},
                               "PSPS criteria come from the utility's de-energization protocol.")
    return dict(thresholds)


def _ffwi_wind(forecast: pd.DataFrame) -> pd.Series:
    """Fosberg is defined on sustained wind; fall back to gusts only with a warning."""
    if "wind_sustained_mph" in forecast.columns:
        return forecast["wind_sustained_mph"]
    LOG.warning("No wind_sustained_mph in forecast: FFWI computed from gusts (overstated).")
    return forecast["wind_gust_mph"]


def psps_candidates(cells: pd.DataFrame, segments: pd.DataFrame, forecast: pd.DataFrame,
                    thresholds: dict, circuit_customers: pd.DataFrame | None = None,
                    hftd_only: bool = True) -> pd.DataFrame:
    """Circuits with any segment cell meeting every threshold in some forecast hour."""
    t = validate_psps_thresholds(thresholds)
    fc = forecast.assign(ffwi=fosberg_ffwi(forecast["temp_f"], forecast["rh_pct"],
                                           _ffwi_wind(forecast)))
    hit = (fc["wind_gust_mph"] >= t["wind_gust_mph"]) & (fc["rh_pct"] <= t["rh_pct"])
    if "ffwi" in t:
        hit &= fc["ffwi"] >= t["ffwi"]
    seg = segments[["segment_id", "circuit_id"] + (["hftd_tier"] if "hftd_tier" in segments else [])]
    if hftd_only and "hftd_tier" in seg:
        seg = seg.loc[seg["hftd_tier"].notna()]
    flagged = cells.merge(fc.loc[hit], on="cell").merge(seg, on="segment_id")
    summary = flagged.groupby("circuit_id").agg(
        segments_flagged=("segment_id", "nunique"), first_hour=("valid_ts", "min"),
        last_hour=("valid_ts", "max"), peak_gust_mph=("wind_gust_mph", "max"),
        min_rh_pct=("rh_pct", "min"), peak_ffwi=("ffwi", "max")).reset_index()
    if circuit_customers is not None:
        summary = summary.merge(circuit_customers, on="circuit_id", how="left")
    return summary.sort_values("segments_flagged", ascending=False, ignore_index=True)


# --------------------------------------------------------------------------- mitigation

def validate_mitigations(mitigations: pd.DataFrame | None) -> pd.DataFrame:
    cols = {"mitigation", "effectiveness", "cost_per_mile_usd"}
    if mitigations is None or mitigations.empty or not cols <= set(mitigations.columns):
        raise DecisionRequired("mitigation_assumptions", sorted(cols),
                               "Effectiveness and unit cost must come from your WMP/GRC.")
    if ((mitigations["effectiveness"] < 0) | (mitigations["effectiveness"] > 1)).any():
        raise ValueError("effectiveness must be a fraction in [0, 1]")
    return mitigations


def plan_mitigation(scored: pd.DataFrame, mitigations: pd.DataFrame,
                    budget_usd: float) -> pd.DataFrame:
    """Best-RSE mitigation per segment, then greedy selection under the budget.

    RSE (risk-spend efficiency) = risk reduced / cost in $M. Greedy-by-RSE is a
    heuristic; it is not an optimal knapsack, and the readout says so.
    """
    m = validate_mitigations(mitigations)
    options = scored[["segment_id", "circuit_id", "length_mi", "risk"]].merge(m, how="cross")
    options = options.assign(
        cost_usd=options["length_mi"] * options["cost_per_mile_usd"],
        risk_reduction=options["risk"] * options["effectiveness"])
    options = options.assign(rse_per_musd=options["risk_reduction"] / (options["cost_usd"] / 1e6))
    best = options.sort_values("rse_per_musd", ascending=False).drop_duplicates("segment_id")
    return best.assign(selected=_greedy_select(best["cost_usd"].tolist(), budget_usd))\
        .reset_index(drop=True)


def _greedy_select(costs: list[float], budget: float) -> list[bool]:
    """Take items in order while they fit; skip (not stop at) items that do not fit."""
    chosen, spent = [], 0.0
    for cost in costs:
        fits = spent + cost <= budget
        chosen.append(fits)
        spent += cost if fits else 0.0
    return chosen
