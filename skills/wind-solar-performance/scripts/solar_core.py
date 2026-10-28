"""Solar PV performance core: cell temperature, performance ratio (IEC 61724-1 and NREL
weather-corrected), clipping, curtailment separation, inverter availability, soiling screen,
and year-on-year degradation (RdTools-style).

Pure pandas/numpy. Input columns (plant or inverter level):
    timestamp (tz-aware), poa_wm2, ac_power_kw, inverter_id (optional),
    module_temp_c or (ambient_temp_c + wind_speed_ms), optional: ghi_wm2, setpoint_kw,
    curtailed (bool), inverter_status ('ok'|'fault'|...).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

G_STC = 1000.0           # W/m2
T_STC = 25.0             # degC
SANDIA_OPEN_RACK = (-3.56, -0.075, 3.0)  # a, b, deltaT for glass/cell/polymer, open rack


class IrradianceBasisError(ValueError):
    """PR needs plane-of-array irradiance; GHI is not a substitute."""


def require_poa(df: pd.DataFrame) -> None:
    if "poa_wm2" not in df or df["poa_wm2"].isna().all():
        hint = " Only GHI is present: transpose to POA first (e.g. pvlib) and state the model." \
            if "ghi_wm2" in df else ""
        raise IrradianceBasisError("poa_wm2 (plane-of-array irradiance) is required for PR." + hint)


def cell_temperature(df: pd.DataFrame, model: tuple = SANDIA_OPEN_RACK) -> pd.Series:
    """Sandia model: T_cell = T_module + G/1000 * dT; T_module from back-of-module or ambient + wind."""
    a, b, dt = model
    g = df["poa_wm2"].clip(lower=0)
    if "module_temp_c" in df and df["module_temp_c"].notna().any():
        t_mod = df["module_temp_c"]
    elif {"ambient_temp_c", "wind_speed_ms"} <= set(df.columns):
        t_mod = g * np.exp(a + b * df["wind_speed_ms"]) + df["ambient_temp_c"]
    else:
        raise ValueError("Need module_temp_c, or ambient_temp_c + wind_speed_ms, for cell temperature")
    return t_mod + g / G_STC * dt


def flag_solar(df: pd.DataFrame, ac_capacity_kw: float, min_poa_wm2: float,
               clip_fraction: float = 0.98) -> pd.DataFrame:
    """Daylight, curtailment (instructed), clipping (inverter AC limit), inverter fault flags."""
    setpoint = df["setpoint_kw"] if "setpoint_kw" in df else pd.Series(np.inf, index=df.index)
    curtailed = setpoint.fillna(np.inf).lt(0.99 * ac_capacity_kw)
    if "curtailed" in df:
        curtailed = curtailed | df["curtailed"].fillna(False).astype(bool)
    status = df["inverter_status"] if "inverter_status" in df else pd.Series("ok", index=df.index)
    daylight = df["poa_wm2"].ge(min_poa_wm2)
    return df.assign(
        daylight=daylight,
        flag_curtailed=curtailed & daylight,
        flag_clipped=df["ac_power_kw"].ge(clip_fraction * ac_capacity_kw) & ~curtailed & daylight,
        flag_inverter_fault=status.ne("ok") & daylight,
        flag_missing=df["ac_power_kw"].isna() | df["poa_wm2"].isna(),
    )


def expected_dc_kw(df: pd.DataFrame, dc_kwp: float, gamma: float | None, t_ref: float | None) -> pd.Series:
    """Reference yield: P_stc * G/1000, optionally temperature-adjusted to t_ref."""
    base = dc_kwp * df["poa_wm2"].clip(lower=0) / G_STC
    if gamma is None:
        return base
    return base * (1 + gamma * (df["t_cell"] - t_ref))


def irradiance_weighted_tcell(df: pd.DataFrame) -> float:
    g = df["poa_wm2"].clip(lower=0)
    return float((df["t_cell"] * g).sum() / g.sum())


def performance_ratio(df: pd.DataFrame, dc_kwp: float, method: str, gamma: float | None,
                      t_ref: float | None = None) -> float:
    """Energy-weighted PR over the included intervals of df."""
    if method == "iec_61724_uncorrected":
        ref = expected_dc_kw(df, dc_kwp, None, None)
    elif method == "temperature_corrected_stc":
        ref = expected_dc_kw(df, dc_kwp, _need_gamma(gamma), T_STC)
    elif method == "nrel_weather_corrected":
        ref = expected_dc_kw(df, dc_kwp, _need_gamma(gamma),
                             t_ref if t_ref is not None else irradiance_weighted_tcell(df))
    else:
        raise ValueError(f"Unknown pr_method {method!r}")
    e_ac = (df["ac_power_kw"].clip(lower=0) * df["interval_h"]).sum()
    e_ref = (ref * df["interval_h"]).sum()
    return float(e_ac / e_ref) if e_ref > 0 else float("nan")


def _need_gamma(gamma: float | None) -> float:
    if gamma is None:
        raise ValueError("gamma_pmax_per_c (module datasheet, e.g. -0.0035) is required for corrected PR")
    if not -0.01 < gamma < 0:
        raise ValueError(f"gamma_pmax_per_c={gamma} implausible; expected about -0.002 to -0.005 per degC")
    return gamma


def inverter_availability(df: pd.DataFrame) -> pd.DataFrame:
    """Share of daylight intervals each inverter was producing without fault (time-based)."""
    day = df[df["daylight"]]
    key = day["inverter_id"] if "inverter_id" in day else pd.Series("plant", index=day.index)
    ok = ~day["flag_inverter_fault"] & day["ac_power_kw"].fillna(0).gt(0)
    return ok.groupby(key).mean().rename("availability").rename_axis("inverter_id").reset_index()


def daily_normalized(df: pd.DataFrame, dc_kwp: float, gamma: float) -> pd.Series:
    """Daily insolation- and temperature-normalized energy (actual / expected at 25 degC)."""
    ref = expected_dc_kw(df, dc_kwp, gamma, T_STC) * df["interval_h"]
    act = df["ac_power_kw"].clip(lower=0) * df["interval_h"]
    day = df["interval_start"].dt.floor("D", ambiguous="NaT", nonexistent="shift_forward")
    agg = pd.DataFrame({"act": act, "ref": ref, "day": day}).groupby("day").sum()
    return (agg["act"] / agg["ref"]).where(agg["ref"] > 0).dropna()


def yoy_degradation(daily: pd.Series, n_boot: int = 1000, seed: int = 7) -> dict:
    """Median of same-day year-over-year % changes; bootstrap 68.2% interval (RdTools convention)."""
    s = daily.copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    prior = s.reindex(s.index - pd.DateOffset(years=1))
    ratios = (s.to_numpy() / prior.to_numpy() - 1) * 100
    yoy = ratios[np.isfinite(ratios)]
    if len(yoy) < 30:
        raise ValueError(f"Need >= 30 year-over-year day pairs (>= 1 year + 30 days of data); got {len(yoy)}")
    rng = np.random.default_rng(seed)
    boots = np.median(rng.choice(yoy, size=(n_boot, len(yoy)), replace=True), axis=1)
    lo, hi = np.percentile(boots, [15.9, 84.1])
    return {"rd_pct_per_year": float(np.median(yoy)), "ci_68_low": float(lo), "ci_68_high": float(hi),
            "n_pairs": int(len(yoy))}


def soiling_screen(daily: pd.Series, window_days: int = 30) -> dict:
    """Screening soiling ratio: daily normalized energy / trailing 95th percentile (clean reference)."""
    clean = daily.rolling(window_days, min_periods=7).quantile(0.95)
    ratio = (daily / clean).clip(upper=1.0).dropna()
    return {"median_soiling_ratio": float(ratio.median()) if len(ratio) else float("nan"),
            "median_soiling_loss_pct": float(100 * (1 - ratio.median())) if len(ratio) else float("nan"),
            "method": "screening: trailing-95th-percentile clean reference; confirm with RdTools SRR"}


def lost_energy(df: pd.DataFrame, dc_kwp: float, pr_reference: float, gamma: float | None) -> dict:
    """Energy lost to curtailment, clipping and inverter faults vs PR-scaled expected power."""
    exp = expected_dc_kw(df, dc_kwp, gamma, T_STC if gamma is not None else None) * pr_reference
    gap = ((exp - df["ac_power_kw"].fillna(0)).clip(lower=0) * df["interval_h"])
    return {"lost_curtailment_kwh": float(gap[df["flag_curtailed"]].sum()),
            "lost_clipping_kwh": float(gap[df["flag_clipped"]].sum()),
            "lost_inverter_fault_kwh": float(gap[df["flag_inverter_fault"] & ~df["flag_curtailed"]].sum())}
