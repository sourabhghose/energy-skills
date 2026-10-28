"""Vetted entrypoints for ISO/RTO price analysis: preview (read-only), then build confirmed.

    from iso_entry import preview_market_data, build_confirmed_price_analysis, build_confirmed_settlement
    print(preview_market_data(raw, iso="ERCOT", market="RT", time_format="hour_ending",
                              nodes=["HB_NORTH", "RN_SOLAR1"])["readout"])

Time formats:
    time_format="utc_column":   raw has `ts_col` (UTC or offset-aware) marking interval start or end
    time_format="hour_ending":  raw has `date`, `hour_ending` [, `interval`] [, repeated-hour flag]
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from iso_analytics import (HOURLY_AGGREGATION, SETTLEMENT, basis, check_components, hourly, peak_stats,
                           price_flags, settle)
from iso_core import (PEAK_DEFINITIONS, TIMESTAMP_CONVENTIONS, DecisionRequired, convention_evidence,
                      from_hour_ending, from_utc, ground_nodes, interval_grid_report, iso_convention, require)

SKILL, VERSION = "iso-market-data", "0.1.0"
MARKETS = ("DA", "RT")
TIME_FORMATS = ("utc_column", "hour_ending")


def _interval_minutes(iso: str, market: str, override: int | None) -> int:
    conv = iso_convention(iso)
    return override or conv["da_interval_minutes" if market == "DA" else "rt_interval_minutes"]


def normalize_prices(raw: pd.DataFrame, *, iso: str, market: str, time_format: str,
                     source_timestamp_convention: str | None = None, ts_col: str = "timestamp",
                     repeated_col: str | None = None, interval_col: str | None = None,
                     interval_minutes: int | None = None) -> pd.DataFrame:
    """Return prices with interval_start_utc / interval_end_utc / interval_minutes."""
    require("market", market, MARKETS)
    require("time_format", time_format, TIME_FORMATS)
    minutes = _interval_minutes(iso, market, interval_minutes)
    if time_format == "utc_column":
        conv = require("source_timestamp_convention", source_timestamp_convention, TIMESTAMP_CONVENTIONS,
                       f"{iso} default is {iso_convention(iso)['default_convention']}; confirm for this report.")
        return from_utc(raw, ts_col, conv, minutes)
    return from_hour_ending(raw, iso_convention(iso)["timezone"], repeated_col=repeated_col,
                            interval_col=interval_col, interval_minutes=minutes)


def _require_nodes(raw: pd.DataFrame, nodes: list[str] | None) -> list[str]:
    if not nodes:
        raise DecisionRequired("nodes", sorted(raw["node"].unique())[:20], "Pick the settlement points to analyse.")
    g = ground_nodes(nodes, list(raw["node"].unique()))
    if g["missing"]:
        raise ValueError(f"Nodes not in the data (no substitution is made): {g['missing']}")
    return g["found"]


def build_confirmed_price_analysis(raw: pd.DataFrame, *, iso: str, market: str, time_format: str,
                                   nodes=None, source_timestamp_convention=None, hourly_aggregation=None,
                                   peak_definition=None, peak_timezone=None, price_floor=None, price_cap=None,
                                   hub: str | None = None, mwh_col: str | None = None, **time_kw) -> dict:
    """Every decision explicit. Missing nodes raise; flagged prices are kept, never dropped."""
    conv = iso_convention(iso)
    d = {"iso": iso, "market": market, "nodes": _require_nodes(raw, nodes),
         "source_timestamp_convention": source_timestamp_convention if time_format == "utc_column"
         else "hour_ending",
         "hourly_aggregation": require("hourly_aggregation", hourly_aggregation, HOURLY_AGGREGATION),
         "peak_definition": require("peak_definition", peak_definition, PEAK_DEFINITIONS),
         "peak_timezone": _timezone(peak_timezone, conv["timezone"]),
         "price_floor": _number("price_floor", price_floor), "price_cap": _number("price_cap", price_cap)}
    keep = d["nodes"] + ([hub] if hub and hub not in d["nodes"] else [])
    prices = normalize_prices(raw[raw["node"].isin(keep)], iso=iso, market=market, time_format=time_format,
                              source_timestamp_convention=source_timestamp_convention, **time_kw)
    prices = price_flags(check_components(prices, iso), d["price_floor"], d["price_cap"])
    hr = hourly(prices, d["hourly_aggregation"], mwh_col)
    out = {"prices": prices, "hourly": hr, "grid": interval_grid_report(prices, conv["timezone"]),
           "peak": peak_stats(hr[hr["node"].isin(d["nodes"])], d["peak_definition"], d["peak_timezone"]),
           "basis": basis(prices, hub) if hub else pd.DataFrame()}
    out["manifest"] = _manifest(raw, d, prices, hub, conv)
    return out


def _timezone(value, iso_tz: str) -> str:
    """Peak blocks are defined in a contract's local prevailing time; it must be stated."""
    options = [iso_tz, "America/New_York", "America/Chicago", "America/Los_Angeles"]
    if not isinstance(value, str):
        raise DecisionRequired("peak_timezone", options, "Use the timezone of the product definition.")
    try:
        pd.Timestamp("2025-01-01", tz=value)
    except Exception as exc:
        raise DecisionRequired("peak_timezone", options, f"{value!r} is not a valid IANA timezone") from exc
    return value


def _number(name: str, value) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DecisionRequired(name, ["<$/MWh bound used to flag outliers, e.g. ISO offer floor / cap>"])
    return float(value)


def _manifest(raw, d, prices, hub, conv) -> dict:
    return {"skill": SKILL, "skill_version": VERSION, "built_utc": datetime.now(timezone.utc).isoformat(),
            "decisions": d, "hub": hub, "convention_registry_status": conv["status"],
            "inputs": {"rows": len(raw), "rows_used": len(prices),
                       "start_utc": str(prices["interval_start_utc"].min()),
                       "end_utc": str(prices["interval_end_utc"].max())},
            "flags": {"component_mismatch": int(prices["component_mismatch"].sum()),
                      "negative": int(prices["flag_negative"].sum()),
                      "outside_bounds": int(prices["flag_outside_bounds"].sum())}}


def build_confirmed_settlement(*, rt_meter: pd.DataFrame, settlement=None, rt_prices=None, da_prices=None,
                               da_awards=None) -> dict:
    """Revenue from normalized prices. rt_meter: node, interval_start_utc, mwh (charging negative)."""
    method = require("settlement", settlement, SETTLEMENT)
    if method != "rt_only" and (da_prices is None or da_awards is None):
        raise ValueError(f"settlement={method} needs da_prices and da_awards (node, interval_start_utc, mw)")
    if method != "da_only" and rt_prices is None:
        raise ValueError(f"settlement={method} needs rt_prices")
    rev = settle(da_prices, rt_prices, da_awards, rt_meter, method)
    totals = rev.groupby("node")[["da_revenue", "rt_revenue", "revenue"]].sum().reset_index()
    manifest = {"skill": SKILL, "skill_version": VERSION, "built_utc": datetime.now(timezone.utc).isoformat(),
                "decisions": {"settlement": method}, "inputs": {"meter_rows": len(rt_meter)}}
    return {"intervals": rev, "totals": totals, "manifest": manifest}


# ----------------------------------------------------------------------------- preview

def _component_fit(prices: pd.DataFrame, iso: str) -> dict:
    if not {"energy", "congestion", "loss"} <= set(prices.columns):
        return {"components": "not present"}
    base = prices["energy"] + prices["loss"] + prices.get("ghg", 0)
    plus = (prices["lmp"] - (base + prices["congestion"])).abs().mean()
    minus = (prices["lmp"] - (base - prices["congestion"])).abs().mean()
    expected = "minus" if iso_convention(iso)["congestion_sign"] < 0 else "plus"
    return {"mean_abs_residual_congestion_plus": round(float(plus), 4),
            "mean_abs_residual_congestion_minus": round(float(minus), 4),
            "registry_expects": expected}


def _peak_consequences(prices: pd.DataFrame, tz: str) -> dict:
    hr = hourly(prices, "time_weighted")
    return {block: round(float(peak_stats(hr, block, tz)["avg"].mean()), 3) for block in PEAK_DEFINITIONS}


def preview_market_data(raw: pd.DataFrame, *, iso: str, market: str, time_format: str,
                        nodes: list[str] | None = None, ts_col: str = "timestamp", **time_kw) -> dict:
    """READ-ONLY. Registry conventions, data evidence, grid gaps, component sign fit, node grounding."""
    conv = iso_convention(iso)
    grounding = ground_nodes(nodes or [], list(raw["node"].unique()))
    probe_conv = conv["default_convention"] if time_format == "utc_column" else None
    prices = normalize_prices(raw, iso=iso, market=market, time_format=time_format,
                              source_timestamp_convention=probe_conv, ts_col=ts_col, **time_kw)
    evidence = convention_evidence(pd.to_datetime(raw[ts_col], utc=True).dt.tz_convert(conv["timezone"]),
                                   int(prices["interval_minutes"].iloc[0])) if time_format == "utc_column" \
        else "hour-ending labels: interval_ending by definition"
    grid = interval_grid_report(prices, conv["timezone"])
    consequences = {"peak_block_avg_lmp": _peak_consequences(prices, conv["timezone"]),
                    "component_fit": _component_fit(prices, iso),
                    "negative_price_share": round(float((prices["lmp"] < 0).mean()), 4),
                    "lmp_min_max": [float(prices["lmp"].min()), float(prices["lmp"].max())]}
    readout = "\n".join([
        f"## {iso} {market} price preview (nothing built)",
        f"Registry ({conv['status']}): tz={conv['timezone']}, native={conv['native_timestamp']}",
        f"Registry notes: {conv['notes']}",
        f"Timestamp evidence: {evidence}",
        f"Nodes in data: {raw['node'].nunique()}; requested found={grounding['found']} missing={grounding['missing']}",
        f"Incomplete node-days: {int((~grid['complete']).sum())} of {len(grid)}; "
        f"DST-length days: {sorted(set(grid.loc[grid['day_hours'] != 24, 'local_date'].astype(str)))}",
        "### Effect of each option on this data", "\n".join(f"- {k}: {v}" for k, v in consequences.items()),
        "### Decisions you must make: nodes, source_timestamp_convention (utc_column only), "
        "hourly_aggregation, peak_definition, peak_timezone, price_floor, price_cap",
    ])
    return {"grounding": grounding, "grid": grid, "consequences": consequences, "evidence": evidence,
            "readout": readout}
