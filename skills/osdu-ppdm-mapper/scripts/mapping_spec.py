"""Source profiling and mapping-spec proposal (source columns -> canonical OSDU/PPDM fields).

Purpose: profile a source table, propose a column mapping with a confidence and a reason for
every canonical field, and propose value maps for status / fluid reference lists. The output
is a mapping spec (dict, YAML-serialisable) with status "proposed"; a human reviews it, edits
it, and sets status "reviewed" before mapping_apply.build will accept it.

Usage:
    from mapping_spec import profile_source, propose_mapping, spec_to_yaml, load_spec
    spec = propose_mapping(df, entity="wellbore", source_table="main.raw.wells")
    open("wellbore_spec.yaml", "w").write(spec_to_yaml(spec))
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re

import pandas as pd

from canonical_model import REFERENCE_LISTS, Field, fields
from identifiers import normalize_api

SPEC_VERSION = 1
MIN_CONFIDENCE = 0.6
DATUM_COLUMN = re.compile(r"(datum|crs|epsg|geodetic|coord_sys|coordinate_system)", re.IGNORECASE)


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _share(mask: pd.Series) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def _value_patterns(series: pd.Series) -> dict:
    s = series.dropna()
    if s.empty:
        return {"api_like": 0.0, "numeric": 0.0, "lat_like": 0.0, "lon_like": 0.0, "date_like": 0.0}
    num = pd.to_numeric(s, errors="coerce")
    dates = pd.to_datetime(s.astype(str), errors="coerce", format="mixed") if num.isna().all() else pd.Series(dtype=float)
    return {
        "api_like": _share(s.map(normalize_api).notna()),
        "numeric": _share(num.notna()),
        "lat_like": _share(num.between(-90, 90)),
        "lon_like": _share(num.between(-180, 180)),
        "date_like": _share(dates.notna()) if len(dates) else 0.0,
    }


def profile_source(df: pd.DataFrame, sample_values: int = 3) -> pd.DataFrame:
    """One row per source column: dtype, null %, distinct count, examples, value patterns."""
    rows = []
    for col in df.columns:
        s = df[col]
        rows.append({"column": col, "dtype": str(s.dtype), "null_pct": round(100 * s.isna().mean(), 1),
                     "distinct": int(s.nunique(dropna=True)),
                     "examples": " | ".join(map(str, s.dropna().astype(str).unique()[:sample_values])),
                     "datum_like_name": bool(DATUM_COLUMN.search(str(col))), **_value_patterns(s)})
    return pd.DataFrame(rows)


def _tokens(column: str) -> set[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(column))
    return {tok for tok in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if tok}


def _name_score(field: Field, column: str) -> float:
    """1.0 exact synonym; 0.8 synonym is a whole token of the column; 0.75*ratio if ratio >= 0.85."""
    col = _norm_name(column)
    names = [_norm_name(field.name)] + [_norm_name(s) for s in field.synonyms]
    if col in names:
        return 1.0
    if any(len(n) >= 3 and n in _tokens(column) for n in names):
        return 0.8
    ratio = max(difflib.SequenceMatcher(None, col, n).ratio() for n in names)
    return 0.75 * ratio if ratio >= 0.85 else 0.0


def _pattern_fit(field: Field, prof: dict) -> float:
    if field.kind == "identifier":
        return prof["api_like"]
    if field.kind == "latitude":
        return prof["lat_like"]
    if field.kind == "longitude":
        return prof["lon_like"]
    if field.dtype == "double":
        return prof["numeric"]
    if field.dtype == "date":
        return max(prof["date_like"], 0.5 if prof["numeric"] > 0.9 else 0.0)
    return 1.0 - 0.5 * prof["numeric"]


def _scored(field: Field, profile: pd.DataFrame) -> list[tuple[float, str, str]]:
    out = []
    for prof in profile.to_dict("records"):
        name = _name_score(field, prof["column"])
        fit = _pattern_fit(field, prof)
        score = round(name * (0.6 + 0.4 * fit), 3)
        out.append((score, prof["column"], f"name match {name:.2f}, value-pattern fit {fit:.2f}"))
    return sorted(out, reverse=True)


def _assign(entity_fields, profile: pd.DataFrame) -> dict:
    """Greedy assignment: best-scoring fields claim columns first; only identifiers share a column."""
    ranked = {f.name: _scored(f, profile) for f in entity_fields}
    order = sorted(entity_fields, key=lambda f: -(ranked[f.name][0][0] if ranked[f.name] else 0))
    used: set[str] = set()
    picks = {}
    for f in order:
        options = [c for c in ranked[f.name] if f.kind == "identifier" or c[1] not in used]
        best = options[0] if options else (0.0, None, "no source columns")
        if best[0] >= MIN_CONFIDENCE:
            picks[f.name] = (best[1], best[0], best[2])
            used.add(best[1])
        else:
            picks[f.name] = (None, best[0], f"best candidate below {MIN_CONFIDENCE}: {best[2]}")
    return picks


def propose_value_map(series: pd.Series, list_name: str) -> dict:
    """Map distinct source values to a reference list by synonym; unmatched values map to None."""
    synonyms = {syn: code for code, syns in REFERENCE_LISTS[list_name].items() for syn in (*syns, code.lower())}
    out = {}
    for value in sorted(series.dropna().astype(str).unique()):
        key = re.sub(r"\s+", " ", value.strip().lower().replace("_", " "))
        out[value] = synonyms.get(key)
    return out


def _field_entry(field: Field, column: str | None, score: float, reason: str, df: pd.DataFrame) -> dict:
    entry = {"source": column, "confidence": score, "reason": reason, "required": field.required}
    if column and field.kind in ("status", "fluid"):
        entry["value_map"] = propose_value_map(df[column], field.kind)
    if field.kind == "depth":
        entry["uom"] = None  # must be declared by the reviewer: 'ft' or 'm'
    return entry


def _coordinate_block(entity: str, mapped: dict) -> dict:
    pairs = {"surface": ("surface_latitude", "surface_longitude"),
             "bottom_hole": ("bottom_hole_latitude", "bottom_hole_longitude")}
    block = {}
    for label, (lat, lon) in pairs.items():
        if mapped.get(lat, {}).get("source") and mapped.get(lon, {}).get("source"):
            block[label] = {"lat": mapped[lat]["source"], "lon": mapped[lon]["source"], "crs": None}
    return block


def propose_mapping(df: pd.DataFrame, entity: str, source_table: str) -> dict:
    """Proposed mapping spec for `entity`. Never marks itself reviewed."""
    profile = profile_source(df)
    picks = _assign(fields(entity), profile)
    mapped = {f.name: _field_entry(f, *picks[f.name], df) for f in fields(entity)}
    datum_cols = profile.loc[profile["datum_like_name"], "column"].tolist()
    return {"spec_version": SPEC_VERSION, "entity": entity, "source_table": source_table,
            "status": "proposed", "fields": mapped,
            "coordinates": _coordinate_block(entity, mapped),
            "datum_columns_in_source": datum_cols,
            "notes": "Review every field. Set uom for depth fields, fill value_map nulls, set "
                     "coordinates.*.crs (or a datum column), then set status: reviewed."}


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:16]


def spec_to_yaml(spec: dict) -> str:
    import yaml

    return yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


def load_spec(text_or_path: str) -> dict:
    """Load a YAML spec from a path or a YAML string; validate its top-level shape."""
    import os

    import yaml

    text = open(text_or_path, encoding="utf-8").read() if os.path.exists(text_or_path) else text_or_path
    spec = yaml.safe_load(text)
    missing = [k for k in ("spec_version", "entity", "status", "fields") if k not in (spec or {})]
    if missing:
        raise ValueError(f"mapping spec is missing keys: {missing}")
    fields(spec["entity"])  # validates entity name
    return spec
