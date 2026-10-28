"""Protection primitives for grid data: column plan, aggregation rules, suppression, geo, tokens.

Pure pandas / stdlib. ``gdg_sql.py`` renders the same plan as Unity Catalog SQL.

- ``column_plan``: per-column action for an audience (drop / tokenize / mask / generalize ...)
- ``group_stats`` + ``apply_rule``: per-cell customer counts and max single-customer share,
  then the 15/15 (or k-only) rule
- ``complementary_suppression``: stop suppressed cells being recovered by subtraction from a
  published parent total
- ``generalize_point``: coordinate rounding or H3 cell
- ``hmac_token``: salted, keyed pseudonym (an unsalted hash of an account number is not)

    from gdg_core import column_plan, group_stats, apply_rule, complementary_suppression
"""

from __future__ import annotations

import hashlib
import hmac

import numpy as np
import pandas as pd

INTERNAL_ACTIONS = {
    "PII_DIRECT": "mask_privileged", "PII_ID": "tokenize", "GEO_PRECISE": "mask_privileged",
    "CEII_TOPOLOGY": "mask_privileged", "CEII_SETTINGS": "mask_privileged",
    "CONSUMPTION": "keep", "QUASI": "keep", "TIME": "keep", "OTHER": "keep",
}
AGGREGATE_ACTIONS = {
    "PII_DIRECT": "drop", "PII_ID": "count_distinct_only", "GEO_PRECISE": "group_generalized",
    "CEII_TOPOLOGY": "drop", "CEII_SETTINGS": "drop", "CONSUMPTION": "aggregate_sum",
    "QUASI": "group_if_selected", "TIME": "bucket", "OTHER": "drop",
}


def column_plan(classes: dict[str, dict], audience: str,
                group_by: tuple[str, ...] = ()) -> dict[str, dict]:
    """Per-column action. Aggregate audiences may not group by CEII topology or direct PII."""
    internal = audience == "internal_need_to_know"
    actions = INTERNAL_ACTIONS if internal else AGGREGATE_ACTIONS
    plan = {}
    for col, info in classes.items():
        cls = info["class"]
        action = actions[cls]
        if not internal and col in group_by:
            if cls in ("PII_DIRECT", "PII_ID", "CEII_SETTINGS"):
                raise ValueError(f"Cannot group an external release by {col!r} ({cls}).")
            if cls == "CEII_TOPOLOGY" and audience == "public":
                raise ValueError(f"Grouping by {col!r} would publish grid topology (CEII). "
                                 "Use geography or rate class for public releases.")
            action = "group_by"
        plan[col] = {"class": cls, "action": action}
    return plan


def group_stats(df: pd.DataFrame, group_cols: list[str], customer_col: str,
                value_col: str) -> pd.DataFrame:
    """Customers per cell, cell total, and the largest single customer's share of the cell."""
    per_customer = df.groupby(group_cols + [customer_col], dropna=False)[value_col].sum().reset_index()
    g = per_customer.groupby(group_cols, dropna=False)[value_col]
    stats = pd.DataFrame({"n_customers": g.size(), "total": g.sum(),
                          "max_customer_value": g.max()}).reset_index()
    share = stats["max_customer_value"] / stats["total"].where(stats["total"] != 0)
    return stats.assign(max_customer_share_pct=100 * share.fillna(1.0))


def apply_rule(stats: pd.DataFrame, rule: str, k_min: int, max_share_pct: float) -> pd.DataFrame:
    """Add ``passes_rule`` and a ``suppression_reason`` per cell."""
    too_few = stats["n_customers"] < k_min
    dominant = (rule == "15_15") & (stats["max_customer_share_pct"] > max_share_pct)
    reason = np.select([too_few, dominant], [f"fewer than {k_min} customers",
                                             f"one customer > {max_share_pct:g}% of cell"], "")
    return stats.assign(passes_rule=~(too_few | dominant), suppression_reason=reason)


def complementary_suppression(cells: pd.DataFrame, parent_cols: list[str]) -> pd.DataFrame:
    """Within each parent (e.g. each month), never leave exactly one suppressed cell.

    If a parent total is published and only one child cell is suppressed, the child equals
    parent − Σ(visible children). Suppress the smallest visible cell as well.
    """
    out = cells.assign(complementary=False)
    groups = (out.groupby(parent_cols, dropna=False).groups.values() if parent_cols
              else [out.index])
    for idx in groups:
        part = out.loc[idx]
        suppressed = ~part["passes_rule"]
        if suppressed.sum() == 1 and (~suppressed).sum() >= 1:
            victim = part.loc[~suppressed, "total"].idxmin()
            out.loc[victim, ["passes_rule", "complementary"]] = [False, True]
            out.loc[victim, "suppression_reason"] = "complementary suppression"
    return out


def generalize_point(lat: pd.Series, lon: pd.Series, method: str, precision: float) -> pd.Series:
    """Rounded ``"lat,lon"`` cells, or H3 cell ids (needs the ``h3`` package offline)."""
    if method == "round":
        d = int(precision)
        return lat.round(d).map(lambda v: f"{v:.{d}f}") + "," + lon.round(d).map(lambda v: f"{v:.{d}f}")
    if method == "h3":
        import h3

        res = int(precision)
        to_cell = getattr(h3, "latlng_to_cell", None) or getattr(h3, "geo_to_h3")
        return pd.Series([to_cell(a, b, res) for a, b in zip(lat, lon)], index=lat.index)
    raise ValueError(f"Unknown geo_method {method!r}")


def hmac_token(value: object, salt: bytes, length: int = 16) -> str | None:
    """Keyed SHA-256 pseudonym. Same value + salt → same token; no salt → no reversal table."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    digest = hmac.new(salt, str(value).encode(), hashlib.sha256).hexdigest()
    return digest[:length]


def risk_summary(stats: pd.DataFrame) -> dict:
    """How much of the data a grouping would suppress."""
    total = float(stats["total"].sum())
    failed = stats[~stats["passes_rule"]]
    return {"cells": int(len(stats)), "cells_suppressed": int(len(failed)),
            "pct_cells_suppressed": round(100 * len(failed) / max(len(stats), 1), 2),
            "pct_value_suppressed": round(100 * float(failed["total"].sum()) / total, 2)
            if total else 0.0,
            "reasons": failed["suppression_reason"].value_counts().to_dict()}


def coordinate_uniqueness(lat: pd.Series, lon: pd.Series, decimals: int = 5) -> dict:
    """Share of rows whose coordinate is unique (precise points identify single premises)."""
    key = lat.round(decimals).astype(str) + "," + lon.round(decimals).astype(str)
    counts = key.map(key.value_counts())
    return {"rows": int(len(key)), "unique_points_pct": round(100 * float((counts == 1).mean()), 2)}
