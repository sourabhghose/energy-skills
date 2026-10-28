"""Wind turbine SCADA performance core: filtering, air-density normalization, binned power
curves, lost-production split, availability, and static yaw misalignment.

Pure pandas/numpy. Input SCADA columns (10-minute data):
    turbine_id, timestamp (tz-aware), wind_speed_ms, power_kw, state,
    optional: ambient_temp_c, pressure_hpa, setpoint_kw, vane_rel_deg

`state` vocabulary: running, curtailed, derated, fault, maintenance, grid_outage, weather_standby.
Methods summarize IEC 61400-12-1 (power performance) and IEC 61400-26 (availability).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

R_DRY_AIR = 287.05  # J/(kg K)
ISO_DENSITY = 1.225  # kg/m3 at 15 degC, 101.325 kPa
BIN_WIDTH = 0.5      # m/s, IEC method of bins
MIN_BIN_COUNT = 3    # IEC minimum 10-minute samples per bin

TURBINE_DOWN = {"fault", "maintenance"}
EXTERNAL_DOWN = {"grid_outage"}
CURTAILED = {"curtailed", "derated"}
STATES = {"running", "weather_standby"} | TURBINE_DOWN | EXTERNAL_DOWN | CURTAILED


def flag_scada(df: pd.DataFrame, rated_kw: float, stuck_window: int = 6) -> pd.DataFrame:
    """Return a copy with boolean flag columns and `valid_for_curve`."""
    unknown = set(df["state"].dropna().unique()) - STATES
    if unknown:
        raise ValueError(f"Unknown state values {sorted(unknown)}; map them to {sorted(STATES)}")
    ws, p = df["wind_speed_ms"], df["power_kw"]
    stuck = (df.groupby("turbine_id")["wind_speed_ms"]
             .transform(lambda s: s.diff().eq(0).astype(int).rolling(stuck_window - 1).sum())
             .ge(stuck_window - 1) & ws.gt(0))
    setpoint_cut = df.get("setpoint_kw", pd.Series(np.inf, index=df.index)).fillna(np.inf) < 0.99 * rated_kw
    flags = pd.DataFrame({
        "flag_missing": ws.isna() | p.isna(),
        "flag_out_of_range": ws.lt(0) | ws.gt(40) | p.lt(-0.05 * rated_kw) | p.gt(1.1 * rated_kw),
        "flag_stuck_anemometer": stuck,
        "flag_curtailed": df["state"].isin(CURTAILED) | setpoint_cut,
        "flag_turbine_down": df["state"].isin(TURBINE_DOWN),
        "flag_external_down": df["state"].isin(EXTERNAL_DOWN),
    }, index=df.index)
    valid = ~flags.any(axis=1) & df["state"].eq("running")
    return pd.concat([df, flags], axis=1).assign(valid_for_curve=valid)


def air_density(df: pd.DataFrame, site_elevation_m: float | None = None) -> pd.Series:
    """rho = p / (R T). Pressure from data, else barometric estimate from elevation."""
    if "ambient_temp_c" not in df:
        raise ValueError("ambient_temp_c is required for air-density normalization")
    t_k = df["ambient_temp_c"] + 273.15
    if "pressure_hpa" in df and df["pressure_hpa"].notna().all():
        p_pa = df["pressure_hpa"] * 100
    elif site_elevation_m is not None:
        p_pa = pd.Series(101325 * (1 - 2.25577e-5 * site_elevation_m) ** 5.25588, index=df.index)
    else:
        raise ValueError("Need pressure_hpa or site_elevation_m to compute air density")
    return p_pa / (R_DRY_AIR * t_k)


def resolve_reference_density(rho: pd.Series, ref_density) -> float:
    if ref_density == "site_mean":
        return float(rho.mean())
    if ref_density == "iso_1.225":
        return ISO_DENSITY
    value = float(ref_density)
    if not 0.9 <= value <= 1.4:
        raise ValueError(f"Reference density {value} kg/m3 outside plausible 0.9-1.4")
    return value


def normalize_density(df: pd.DataFrame, rho: pd.Series, rho_ref: float, control: str) -> pd.DataFrame:
    """Pitch-regulated: normalize wind speed by (rho/rho_ref)^(1/3). Stall: scale power by rho_ref/rho."""
    if control == "pitch":
        return df.assign(ws_norm=df["wind_speed_ms"] * (rho / rho_ref) ** (1 / 3), p_norm=df["power_kw"])
    if control == "stall":
        return df.assign(ws_norm=df["wind_speed_ms"], p_norm=df["power_kw"] * rho_ref / rho)
    raise ValueError(f"turbine_control must be pitch|stall, got {control!r}")


def binned_power_curve(df: pd.DataFrame, ws_col: str = "ws_norm", p_col: str = "p_norm") -> pd.DataFrame:
    """IEC method of bins on valid data: 0.5 m/s bins centred on multiples of 0.5 m/s."""
    valid = df[df["valid_for_curve"]]
    bins = (valid[ws_col] / BIN_WIDTH).round() * BIN_WIDTH
    curve = (valid.groupby(bins).agg(ws_mean=(ws_col, "mean"), power_kw=(p_col, "mean"), n=(p_col, "size"))
             .rename_axis("bin_ms").reset_index())
    return curve.assign(complete=curve["n"] >= MIN_BIN_COUNT)


def curve_power(curve: pd.DataFrame, ws: pd.Series, rated_kw: float) -> pd.Series:
    """Interpolate a power curve (columns ws_mean|bin_ms, power_kw) at wind speeds; 0 outside range."""
    x_col = "ws_mean" if "ws_mean" in curve else "bin_ms"
    c = curve.dropna(subset=[x_col, "power_kw"]).sort_values(x_col)
    vals = np.interp(ws.fillna(0), c[x_col], c["power_kw"], left=0.0, right=0.0)
    return pd.Series(np.clip(vals, 0, rated_kw), index=ws.index)


def rayleigh_aep_mwh(curve: pd.DataFrame, mean_ws: float, rated_kw: float) -> float:
    """AEP for a Rayleigh wind distribution with the given annual mean wind speed."""
    edges = np.arange(0, 30.25, BIN_WIDTH)
    cdf = 1 - np.exp(-np.pi / 4 * (edges / mean_ws) ** 2)
    centres = pd.Series((edges[:-1] + edges[1:]) / 2)
    power = curve_power(curve, centres, rated_kw).to_numpy()
    return float(8760 * np.sum(np.diff(cdf) * power) / 1000)


def lost_production(df: pd.DataFrame, expected_kw: pd.Series) -> pd.DataFrame:
    """Per-interval split of the energy gap into availability, external, curtailment, performance."""
    gap_kwh = (expected_kw - df["power_kw"].fillna(0)) * df["interval_h"]
    lost = gap_kwh.clip(lower=0)
    running = df["state"].eq("running") & ~df["flag_curtailed"]
    return pd.DataFrame({
        "turbine_id": df["turbine_id"],
        "expected_kwh": expected_kw * df["interval_h"],
        "actual_kwh": df["power_kw"].fillna(0).clip(lower=0) * df["interval_h"],
        "lost_availability_kwh": lost.where(df["flag_turbine_down"], 0.0),
        "lost_external_kwh": lost.where(df["flag_external_down"], 0.0),
        "lost_curtailment_kwh": lost.where(df["flag_curtailed"] & ~df["flag_turbine_down"], 0.0),
        "performance_gap_kwh": gap_kwh.where(running & ~df["flag_missing"], 0.0),
    }, index=df.index)


def availability(df: pd.DataFrame, losses: pd.DataFrame, basis: str, external: str) -> pd.DataFrame:
    """Time- or energy-based availability per turbine (IEC 61400-26 style)."""
    unavailable = df["flag_turbine_down"] | (df["flag_external_down"] & (external == "count_as_unavailable"))
    excluded = df["flag_external_down"] & (external == "exclude_from_availability")
    frame = df.assign(_down_h=unavailable * df["interval_h"], _excl_h=excluded * df["interval_h"],
                      _lost=losses["lost_availability_kwh"]
                      + losses["lost_external_kwh"] * (external == "count_as_unavailable"),
                      _act=losses["actual_kwh"])
    g = frame.groupby("turbine_id")
    period_h, down_h, excl_h = g["interval_h"].sum(), g["_down_h"].sum(), g["_excl_h"].sum()
    if basis == "time":
        value = 1 - down_h / (period_h - excl_h)
    elif basis == "energy":
        value = g["_act"].sum() / (g["_act"].sum() + g["_lost"].sum())
    else:
        raise ValueError(f"availability_basis must be time|energy, got {basis!r}")
    return value.rename("availability").reset_index().assign(basis=basis, external_downtime=external)


def yaw_misalignment(df: pd.DataFrame, ws_range=(5.0, 10.0), threshold_deg: float = 4.0) -> pd.DataFrame:
    """Median vane-relative wind direction in partial-load operation; flags static offsets."""
    if "vane_rel_deg" not in df:
        return pd.DataFrame(columns=["turbine_id", "median_offset_deg", "flag", "loss_band_pct"])
    sel = df[df["valid_for_curve"] & df["wind_speed_ms"].between(*ws_range)]
    med = sel.groupby("turbine_id")["vane_rel_deg"].median().rename("median_offset_deg").reset_index()
    rad = np.radians(med["median_offset_deg"].abs())
    band = [f"{100 * (1 - np.cos(r) ** 2):.1f}-{100 * (1 - np.cos(r) ** 3):.1f}" for r in rad]
    return med.assign(flag=med["median_offset_deg"].abs() > threshold_deg, loss_band_pct=band)


def icing_suspect(df: pd.DataFrame, expected_kw: pd.Series, temp_c: float = 2.0,
                  ratio: float = 0.5) -> pd.Series:
    """Cold, windy, running, and producing under half the expected power."""
    if "ambient_temp_c" not in df:
        return pd.Series(False, index=df.index)
    return (df["ambient_temp_c"].le(temp_c) & df["state"].eq("running") & expected_kw.gt(0)
            & df["power_kw"].lt(ratio * expected_kw))
