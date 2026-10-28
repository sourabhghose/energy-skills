"""Historian tag grounding, unit normalization, and digital-state cleaning.

Purpose: map raw historian tags (PI / AVEVA-style names) to canonical asset + measurement
with canonical units, using a tag-map table. Tags are never matched by guessing:
  * tags in the map but absent from the historian are reported (missing_in_historian)
  * historian tags absent from the map are excluded and listed (unmapped_tags)
  * tags with unknown or unconvertible units are excluded (unit_unknown)
Analog tags in PI often carry digital-state strings ("I/O Timeout", "Shutdown", "Bad Input")
in the value column. Those samples are dropped and counted, never coerced to 0.

Usage:
    from tags import ground_tags, normalize_samples
    grounding = ground_tags(historian, tag_map)
    samples = normalize_samples(historian, grounding.mapped)
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pdm_taxonomy import MEASUREMENTS, UNIT_ALIASES, UNIT_CONVERSIONS

TAG_MAP_COLUMNS = ("tag", "asset_id", "equipment_class", "measurement", "unit")
HISTORIAN_COLUMNS = ("tag", "ts", "value")
RUN_STATES = {"1", "1.0", "run", "running", "on", "true", "started"}
STOP_STATES = {"0", "0.0", "stop", "stopped", "off", "false", "shutdown", "tripped"}


@dataclass(frozen=True)
class Grounding:
    mapped: pd.DataFrame          # tag map rows usable for analysis (+ multiplier, offset)
    unmapped_tags: list[str]
    missing_in_historian: list[str]
    unit_problems: pd.DataFrame


def canonical_unit(unit) -> str | None:
    if unit is None or (isinstance(unit, float) and pd.isna(unit)):
        return None
    text = str(unit).strip()
    return UNIT_ALIASES.get(text.lower(), text)


def _conversion(measurement: str, unit) -> tuple[float, float] | None:
    target, kind = MEASUREMENTS[measurement]
    if kind == "state":
        return (1.0, 0.0)
    src = canonical_unit(unit)
    if src == target:
        return (1.0, 0.0)
    return UNIT_CONVERSIONS.get((src, target))


def _check(df: pd.DataFrame, cols, label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {missing}")


def ground_tags(historian: pd.DataFrame, tag_map: pd.DataFrame) -> Grounding:
    """Split the tag map into usable rows and reported problems."""
    _check(historian, HISTORIAN_COLUMNS, "historian")
    _check(tag_map, TAG_MAP_COLUMNS, "tag_map")
    present = set(historian["tag"].astype(str).unique())
    known_measure = tag_map["measurement"].isin(MEASUREMENTS)
    conv = [(_conversion(m, u) if ok else None) for m, u, ok in
            zip(tag_map["measurement"], tag_map["unit"], known_measure)]
    usable = pd.Series([c is not None for c in conv], index=tag_map.index) & tag_map["tag"].isin(present)
    problems = tag_map[[c is None for c in conv]].assign(
        problem=lambda d: d["measurement"].map(lambda m: "unit_unknown" if m in MEASUREMENTS else "measurement_unknown"))
    mapped = tag_map[usable].assign(
        multiplier=[c[0] for c, u in zip(conv, usable) if u],
        offset=[c[1] for c, u in zip(conv, usable) if u],
        kind=lambda d: d["measurement"].map(lambda m: MEASUREMENTS[m][1]),
        canonical_unit=lambda d: d["measurement"].map(lambda m: MEASUREMENTS[m][0]))
    return Grounding(mapped=mapped.reset_index(drop=True),
                     unmapped_tags=sorted(present - set(tag_map["tag"].astype(str))),
                     missing_in_historian=sorted(set(tag_map["tag"].astype(str)) - present),
                     unit_problems=problems.reset_index(drop=True))


def _state_value(value) -> float | None:
    text = str(value).strip().lower()
    if text in RUN_STATES:
        return 1.0
    return 0.0 if text in STOP_STATES else None


def normalize_samples(historian: pd.DataFrame, mapped: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Canonical long samples (asset_id, measurement, ts, value) + dropped digital states.

    Timestamps must be tz-aware (historians store UTC); naive timestamps raise.
    """
    joined = historian.merge(mapped, on="tag", how="inner")
    ts = pd.to_datetime(joined["ts"])
    if ts.dt.tz is None:
        raise ValueError("historian timestamps must be timezone-aware (store UTC)")
    numeric = pd.to_numeric(joined["value"], errors="coerce")
    state = joined["value"].map(_state_value)
    value = numeric.where(joined["kind"] == "analog", state)
    scaled = value * joined["multiplier"] + joined["offset"]
    good = value.notna()
    if "quality" in joined.columns:
        good &= joined["quality"].astype(str).str.lower().isin({"good", "0", "192", "true"})
    dropped = (joined.loc[~good, ["tag", "value"]].astype(str).value_counts()
               .rename("count").reset_index())
    samples = pd.DataFrame({"asset_id": joined["asset_id"], "equipment_class": joined["equipment_class"],
                            "measurement": joined["measurement"], "ts": ts, "value": scaled})[good]
    return samples.sort_values(["asset_id", "measurement", "ts"]).reset_index(drop=True), dropped
