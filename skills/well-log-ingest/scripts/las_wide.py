"""Build a wide (one column per family) log table from the tidy long table.

Multiple runs (files) for the same well often overlap in depth. Which run wins in the
overlap is a decision (`overlap_policy`): prefer the latest or the earliest run by log date
(file order breaks ties). Depths are snapped to a grid (`depth_step`) so runs logged at
different sample rates align. The long table always keeps every run; only the wide view
resolves overlaps.

Usage:
    from las_wide import to_wide
    wide = to_wide(long_df, headers_df, overlap_policy="prefer_latest_run", depth_step=0.5)
"""

from __future__ import annotations

import pandas as pd

OVERLAP_POLICIES = ("prefer_latest_run", "prefer_earliest_run", "skip_wide")


def _run_rank(headers: pd.DataFrame, policy: str) -> dict[str, int]:
    dates = pd.to_datetime(headers["log_date"], errors="coerce", format="mixed")
    order = headers.assign(_date=dates, _pos=range(len(headers)))
    ascending = policy == "prefer_earliest_run"
    order = order.sort_values(["_date", "_pos"], ascending=[ascending, ascending], na_position="last")
    return {src: rank for rank, src in enumerate(order["source_file"])}


def to_wide(long: pd.DataFrame, headers: pd.DataFrame, overlap_policy: str, depth_step: float) -> pd.DataFrame:
    """Pivot to api14 x depth rows with one column per family; first-ranked run wins overlaps."""
    if overlap_policy not in OVERLAP_POLICIES:
        raise ValueError(f"overlap_policy must be one of {OVERLAP_POLICIES}")
    if overlap_policy == "skip_wide" or long.empty:
        return pd.DataFrame()
    if depth_step <= 0:
        raise ValueError("depth_step must be positive")
    rank = _run_rank(headers, overlap_policy)
    snapped = long.assign(depth=(long["depth"] / depth_step).round() * depth_step,
                          _rank=long["source_file"].map(rank).fillna(len(rank)))
    snapped = snapped[snapped["family"] != "UNMAPPED"]
    best = (snapped.sort_values(["_rank"])
            .drop_duplicates(subset=["api14", "depth", "family"], keep="first"))
    wide = best.pivot_table(index=["api14", "depth"], columns="family", values="value", aggfunc="first")
    wide.columns = [f"{c.lower()}" for c in wide.columns]
    units = best.drop_duplicates("family").set_index("family")["unit"].to_dict()
    wide = wide.rename(columns={f.lower(): f"{f.lower()}_{_unit_suffix(u)}" for f, u in units.items()})
    return wide.reset_index().assign(depth_unit=long["depth_unit"].iloc[0], depth_datum=long["depth_datum"].iloc[0])


def _unit_suffix(unit: str) -> str:
    return {"gAPI": "gapi", "g/cm3": "gcc", "v/v": "vv", "us/ft": "usft", "ohm.m": "ohmm", "in": "in",
            "mV": "mv", "b/e": "be"}.get(unit, "raw")
