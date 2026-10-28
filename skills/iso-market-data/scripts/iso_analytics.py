"""Price analytics on normalized ISO data: LMP decomposition check, time-weighted hourly prices,
peak-block statistics, basis to hub, DA-RT spread, price sanity flags, and two-settlement revenue.

Input prices (long): node, interval_start_utc, interval_end_utc, interval_minutes, lmp
[, energy, congestion, loss, ghg]. Produce them with iso_core.from_utc / from_hour_ending.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from iso_core import iso_convention, peak_mask

HOURLY_AGGREGATION = ("time_weighted", "energy_weighted")
SETTLEMENT = ("two_settlement", "rt_only", "da_only")


def check_components(prices: pd.DataFrame, iso: str, tol: float = 0.011) -> pd.DataFrame:
    """Recompute LMP from components using the ISO's sign convention; flag residuals > tol $/MWh."""
    conv = iso_convention(iso)
    comps = [c for c in conv["components"] if c in prices]
    if not comps or "energy" not in comps:
        return prices.assign(component_residual=np.nan, component_mismatch=False)
    total = sum(prices[c] * (conv["congestion_sign"] if c == "congestion" else 1) for c in comps)
    resid = prices["lmp"] - total
    return prices.assign(component_residual=resid, component_mismatch=resid.abs() > tol)


def normalized_congestion(prices: pd.DataFrame, iso: str) -> pd.Series:
    """Congestion in the 'adds to price' sign convention (flips NYISO's published sign)."""
    return prices["congestion"] * iso_convention(iso)["congestion_sign"]


def price_flags(prices: pd.DataFrame, floor: float, cap: float) -> pd.DataFrame:
    """Flag (never drop) negative prices and prices outside [floor, cap]."""
    return prices.assign(flag_negative=prices["lmp"] < 0,
                         flag_outside_bounds=(prices["lmp"] < floor) | (prices["lmp"] > cap))


def hourly(prices: pd.DataFrame, method: str, mwh_col: str | None = None) -> pd.DataFrame:
    """Hourly price per node. time_weighted: sum(p*minutes)/sum(minutes); energy_weighted needs MWh.

    Reports covered minutes; hours with < 60 covered minutes are flagged `incomplete`.
    """
    hour = prices["interval_start_utc"].dt.floor("h")
    frame = prices.assign(hour_start_utc=hour, _w=prices["interval_minutes"].astype(float))
    if method == "energy_weighted":
        if not mwh_col or mwh_col not in prices:
            raise ValueError("energy_weighted aggregation needs an MWh column (mwh_col)")
        frame = frame.assign(_w=prices[mwh_col].abs())
    elif method != "time_weighted":
        raise ValueError(f"hourly_aggregation must be one of {HOURLY_AGGREGATION}")
    frame = frame.assign(_pw=frame["lmp"] * frame["_w"])
    g = frame.groupby(["node", "hour_start_utc"])
    out = pd.DataFrame({"lmp": g["_pw"].sum() / g["_w"].sum(), "covered_minutes": g["interval_minutes"].sum(),
                        "n_intervals": g.size()}).reset_index()
    return out.assign(incomplete=out["covered_minutes"] < 60)


def peak_stats(hourly_prices: pd.DataFrame, definition: str, peak_tz: str) -> pd.DataFrame:
    """Average, min, max and negative-hour share per node in the chosen peak block."""
    mask = peak_mask(hourly_prices["hour_start_utc"], definition, peak_tz)
    sel = hourly_prices[mask]
    g = sel.groupby("node")["lmp"]
    return pd.DataFrame({"avg": g.mean(), "min": g.min(), "max": g.max(), "hours": g.size(),
                         "negative_share": sel.assign(neg=sel["lmp"] < 0).groupby("node")["neg"].mean()}
                        ).reset_index().assign(block=definition, peak_tz=peak_tz)


def basis(prices: pd.DataFrame, hub: str) -> pd.DataFrame:
    """Node minus hub, interval by interval (same market and interval grid)."""
    hub_px = prices[prices["node"] == hub][["interval_start_utc", "lmp"]].rename(columns={"lmp": "hub_lmp"})
    if hub_px.empty:
        raise ValueError(f"Hub {hub!r} not present in the price data")
    merged = prices[prices["node"] != hub].merge(hub_px, on="interval_start_utc", how="inner")
    return merged.assign(basis=merged["lmp"] - merged["hub_lmp"])


def da_rt_spread(da_hourly: pd.DataFrame, rt_hourly: pd.DataFrame) -> pd.DataFrame:
    """DA minus time-weighted hourly RT, per node-hour. Incomplete RT hours are kept and flagged."""
    m = da_hourly[["node", "hour_start_utc", "lmp"]].merge(
        rt_hourly[["node", "hour_start_utc", "lmp", "incomplete"]], on=["node", "hour_start_utc"],
        suffixes=("_da", "_rt"))
    return m.assign(da_minus_rt=m["lmp_da"] - m["lmp_rt"])


def settle(da_prices: pd.DataFrame | None, rt_prices: pd.DataFrame | None, da_awards: pd.DataFrame | None,
           rt_meter: pd.DataFrame, method: str) -> pd.DataFrame:
    """Interval revenue ($). Generation positive MWh, battery charging negative MWh.

    two_settlement: DA_MW x DA_LMP (hourly) + (RT_MWh - DA_MW x hours) x RT_LMP (per RT interval).
    rt_only: RT_MWh x RT_LMP. da_only: DA_MW x DA_LMP (financial view, no deviations).
    """
    if method == "rt_only":
        m = rt_meter.merge(rt_prices[["node", "interval_start_utc", "lmp"]], on=["node", "interval_start_utc"])
        return m.assign(da_revenue=0.0, rt_revenue=m["mwh"] * m["lmp"]).assign(
            revenue=lambda x: x["rt_revenue"])
    da = da_awards.merge(da_prices[["node", "interval_start_utc", "lmp"]], on=["node", "interval_start_utc"])
    da = da.assign(da_revenue=da["mw"] * da["lmp"] * da_prices["interval_minutes"].iloc[0] / 60)
    if method == "da_only":
        return da.assign(rt_revenue=0.0, revenue=da["da_revenue"])
    if method != "two_settlement":
        raise ValueError(f"settlement must be one of {SETTLEMENT}")
    rt = rt_meter.merge(rt_prices[["node", "interval_start_utc", "interval_minutes", "lmp"]],
                        on=["node", "interval_start_utc"]).assign(hour=lambda x: x["interval_start_utc"].dt.floor("h"))
    awards = da_awards.rename(columns={"interval_start_utc": "hour", "mw": "da_mw"})[["node", "hour", "da_mw"]]
    rt = rt.merge(awards, on=["node", "hour"], how="left").fillna({"da_mw": 0.0})
    deviation = rt["mwh"] - rt["da_mw"] * rt["interval_minutes"] / 60
    rt = rt.assign(deviation_mwh=deviation, rt_revenue=deviation * rt["lmp"], da_revenue=0.0)
    da_rows = da.assign(rt_revenue=0.0)[["node", "interval_start_utc", "da_revenue", "rt_revenue"]]
    rt_rows = rt[["node", "interval_start_utc", "da_revenue", "rt_revenue", "deviation_mwh"]]
    return pd.concat([da_rows, rt_rows], ignore_index=True).assign(
        revenue=lambda x: x["da_revenue"] + x["rt_revenue"])
