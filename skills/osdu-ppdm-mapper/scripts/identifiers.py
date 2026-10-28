"""US API well number handling: normalization, level detection, padding, and collisions.

Purpose: "what is a well" disambiguation. An API number is hierarchical:
  API-10 = state(2) + county(3) + unique well(5)       -> the well (surface origin)
  API-12 = API-10 + wellbore / sidetrack code(2)        -> a wellbore
  API-14 = API-12 + completion / event code(2)          -> a completion (wellbore event)
A source column called "API" may hold any of these, mixed. This module measures which level
the data is at and never invents digits (padding is the user's decision).

Usage:
    from identifiers import normalize_api, detect_api_level, apply_api_level, find_collisions
"""

from __future__ import annotations

import re

import pandas as pd

API_LEVELS = {"well": 10, "wellbore": 12, "completion": 14}
API_PADDING_POLICIES = ("pad_zeros", "leave_null")
NON_DIGIT = re.compile(r"[^0-9]")


NUMERIC_TEXT = re.compile(r"^\d+(\.0)?$")


def normalize_api(value) -> str | None:
    """Strip separators ('42-301-12345-00' -> '4230112345'); None if empty or not 10/12/14 digits.

    A single leading zero is restored only for values that look numerically stored (a number,
    or digits with an optional '.0'), where states 01-09 lose their zero. Formatted strings
    with separators are never padded: '42-301-1234' is malformed, not state 04.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    numeric = isinstance(value, (int, float)) or bool(NUMERIC_TEXT.match(text))
    digits = NON_DIGIT.sub("", text.removesuffix(".0"))
    if numeric and len(digits) in (9, 11, 13):
        digits = "0" + digits
    return digits if len(digits) in (10, 12, 14) else None


def api_quality(series: pd.Series) -> pd.DataFrame:
    """Per-value normalization result with a reason (ok, null, bad_length, leading_zero_restored)."""
    norm = series.map(normalize_api)
    digits = series.map(lambda v: None if pd.isna(v) else NON_DIGIT.sub("", str(v).removesuffix(".0")))
    lengths = digits.map(lambda d: None if not isinstance(d, str) else len(d))
    reason = [
        "null" if pd.isna(raw) else "bad_length" if pd.isna(n) else
        "leading_zero_restored" if ln in (9, 11, 13) else "ok"
        for raw, n, ln in zip(series, norm, lengths)
    ]
    return pd.DataFrame({"raw": series, "normalized": norm, "digit_len": lengths, "reason": reason})


def detect_api_level(series: pd.Series) -> dict:
    """Counts of 10/12/14-digit values and distinct prefixes, plus the implied level."""
    norm = series.map(normalize_api).dropna()
    lengths = norm.str.len().value_counts().to_dict()
    distinct = {lvl: int(norm.str[:n].nunique()) for lvl, n in API_LEVELS.items() if len(norm)}
    mixed = len(lengths) > 1
    implied = None if mixed or not lengths else {10: "well", 12: "wellbore", 14: "completion"}[next(iter(lengths))]
    return {"length_counts": {int(k): int(v) for k, v in lengths.items()}, "distinct_by_level": distinct,
            "mixed_lengths": mixed, "implied_level": implied, "invalid": int(series.notna().sum() - len(norm))}


def _to_level(api: str | None, n: int, padding: str) -> str | None:
    if api is None:
        return None
    if len(api) >= n:
        return api[:n]
    return api + "0" * (n - len(api)) if padding == "pad_zeros" else None


def apply_api_level(series: pd.Series, target_level: str, padding: str) -> pd.Series:
    """Truncate to the target level, or pad shorter values per `padding` (never silently)."""
    if target_level not in API_LEVELS:
        raise ValueError(f"target_level must be one of {list(API_LEVELS)}")
    if padding not in API_PADDING_POLICIES:
        raise ValueError(f"padding must be one of {API_PADDING_POLICIES}")
    n = API_LEVELS[target_level]
    values = [_to_level(normalize_api(v), n, padding) for v in series]
    return pd.Series(values, index=series.index, dtype="string")


def find_collisions(df: pd.DataFrame, id_col: str, attr_cols: list[str]) -> pd.DataFrame:
    """IDs that appear on several rows with conflicting attribute values (e.g. two names)."""
    present = [c for c in attr_cols if c in df.columns]
    if id_col not in df.columns or not present:
        return pd.DataFrame(columns=[id_col, "attribute", "distinct_values", "examples"])
    rows = []
    for col in present:
        counts = df.groupby(id_col)[col].nunique(dropna=True)
        for ident in counts[counts > 1].index:
            vals = df.loc[df[id_col] == ident, col].dropna().astype(str).unique()[:3]
            rows.append({id_col: ident, "attribute": col, "distinct_values": int(counts[ident]),
                         "examples": " | ".join(vals)})
    return pd.DataFrame(rows, columns=[id_col, "attribute", "distinct_values", "examples"])


def ground_ids(candidate_ids, present_ids) -> tuple[list[str], list[str]]:
    """Split proposed identifiers into those present in the data and those that are not."""
    present = set(map(str, present_ids))
    kept = [str(i) for i in candidate_ids if str(i) in present]
    missing = [str(i) for i in candidate_ids if str(i) not in present]
    return kept, missing
