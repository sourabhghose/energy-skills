"""Preview and apply a reviewed mapping spec: canonical rows, rejects, lineage, OSDU/PPDM views.

Purpose: the core behind osdu-ppdm-mapper. `preview_mapping` is read-only and lists every
problem a reviewer must resolve (unmapped required fields, cast failures, identifier level,
collisions, unmapped reference values, coordinate issues, undeclared units / datum).
`build_canonical` requires the reviewed spec plus every decision explicitly.

Usage:
    from mapping_apply import preview_mapping, build_canonical
    report = preview_mapping(df, spec)
    out = build_canonical(df, spec, source_identifier_level="completion", api_padding="leave_null",
                          source_crs="NAD27", target_standard="both")
"""

from __future__ import annotations

import pandas as pd

from canonical_model import TARGET_STANDARDS, fields, get_field
from geo import coordinate_issues, resolve_crs, transform_coordinates
from identifiers import API_LEVELS, API_PADDING_POLICIES, apply_api_level, detect_api_level, find_collisions
from mapping_spec import spec_hash

ID_TARGET_LEVEL = {"well_uwi": "well", "wellbore_uwi": "wellbore", "completion_id": "completion"}
SOURCE_LEVELS = (*API_LEVELS, "lease")
DEPTH_UOMS = ("ft", "m")


class DecisionRequired(ValueError):
    """Raised when a decision that belongs to the user was not supplied."""


def _mapped(spec: dict) -> dict:
    return {k: v for k, v in spec["fields"].items() if v.get("source")}


def _cast(series: pd.Series, dtype: str) -> pd.Series:
    if dtype == "double":
        return pd.to_numeric(series, errors="coerce")
    if dtype == "int":
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    if dtype == "date":
        return pd.to_datetime(series.astype("string"), errors="coerce", format="mixed").dt.date
    return series.astype("string").str.strip()


def _cast_failures(df: pd.DataFrame, spec: dict) -> list[dict]:
    rows = []
    for name, entry in _mapped(spec).items():
        field = get_field(spec["entity"], name)
        if field.dtype == "string" or field.kind == "identifier":
            continue
        src = df[entry["source"]]
        failed = int((src.notna() & pd.Series(_cast(src, field.dtype), index=src.index).isna()).sum())
        if failed:
            rows.append({"field": name, "source": entry["source"], "failed_casts": failed})
    return rows


def _id_report(df: pd.DataFrame, spec: dict) -> dict:
    out = {}
    for name, entry in _mapped(spec).items():
        if get_field(spec["entity"], name).kind == "identifier":
            out[name] = detect_api_level(df[entry["source"]])
    return out


def _unmapped_values(spec: dict) -> dict:
    return {name: sorted(k for k, v in entry.get("value_map", {}).items() if v is None)
            for name, entry in _mapped(spec).items()
            if entry.get("value_map") and any(v is None for v in entry["value_map"].values())}


def _coord_report(df: pd.DataFrame, spec: dict) -> dict:
    report = {}
    for label, c in spec.get("coordinates", {}).items():
        crs = c.get("crs") or "EPSG:4326"
        issues = coordinate_issues(df[c["lat"]], df[c["lon"]], resolve_crs(crs))
        report[label] = {"declared_crs": c.get("crs"), "issues": issues.to_dict("records")}
    return report


def preview_mapping(df: pd.DataFrame, spec: dict) -> dict:
    """READ-ONLY review report for a (proposed or reviewed) spec."""
    entity_fields = fields(spec["entity"])
    mapped = _mapped(spec)
    first_id = next((f.name for f in entity_fields if f.kind == "identifier" and f.name in mapped), None)
    collisions = (find_collisions(df, mapped[first_id]["source"],
                                  [e["source"] for n, e in mapped.items() if n != first_id])
                  if first_id else pd.DataFrame())
    datum_cols = spec.get("datum_columns_in_source", [])
    return {
        "entity": spec["entity"], "status": spec["status"], "rows": len(df),
        "unmapped_required": [f.name for f in entity_fields if f.required and f.name not in mapped],
        "low_confidence": sorted(n for n, e in mapped.items() if e.get("confidence", 1) < 0.8),
        "cast_failures": _cast_failures(df, spec),
        "identifier_levels": _id_report(df, spec),
        "collisions": collisions.head(50).to_dict("records"),
        "unmapped_reference_values": _unmapped_values(spec),
        "depth_fields_missing_uom": sorted(n for n, e in mapped.items()
                                           if get_field(spec["entity"], n).kind == "depth" and not e.get("uom")),
        "coordinates": _coord_report(df, spec),
        "datum_values_in_source": {c: sorted(map(str, df[c].dropna().unique()))[:10] for c in datum_cols if c in df},
    }


def _require(value, key: str, options) -> None:
    if value is None:
        raise DecisionRequired(f"Decision '{key}' is required. Options: {options}")


def _check_decisions(spec: dict, source_identifier_level, api_padding, source_crs, target_standard) -> None:
    _require(source_identifier_level, "source_identifier_level", SOURCE_LEVELS)
    _require(api_padding, "api_padding", API_PADDING_POLICIES)
    _require(source_crs, "source_crs", "EPSG code / NAD27 / NAD83 / WGS84 / 'column:<datum col>' / 'not_applicable'")
    _require(target_standard, "target_standard", TARGET_STANDARDS)
    if source_identifier_level not in SOURCE_LEVELS:
        raise DecisionRequired(f"source_identifier_level must be one of {SOURCE_LEVELS}")
    if api_padding not in API_PADDING_POLICIES:
        raise DecisionRequired(f"api_padding must be one of {API_PADDING_POLICIES}")
    if target_standard not in TARGET_STANDARDS:
        raise DecisionRequired(f"target_standard must be one of {TARGET_STANDARDS}")
    if spec.get("status") != "reviewed":
        raise DecisionRequired("mapping spec status must be 'reviewed' (a human signs off the proposal)")
    if spec.get("coordinates") and source_crs == "not_applicable":
        raise DecisionRequired("spec maps coordinates, so source_crs cannot be 'not_applicable'")


def _check_level_against_data(df: pd.DataFrame, spec: dict, level: str) -> None:
    """A declared level finer than the digits present would require inventing digits."""
    if level == "lease":
        return
    for name, rep in _id_report(df, spec).items():
        lengths = rep["length_counts"]
        if lengths and max(lengths) < API_LEVELS[level]:
            raise ValueError(f"{name}: declared source level '{level}' needs {API_LEVELS[level]}-digit APIs "
                             f"but the data has lengths {sorted(lengths)}")


def _identifier(series: pd.Series, field_name: str, entity: str, level: str, padding: str) -> pd.Series:
    if level == "lease" or entity == "production":
        return series.astype("string").str.strip()
    return apply_api_level(series, ID_TARGET_LEVEL[field_name], padding).astype("string")


def _value(df: pd.DataFrame, entity: str, name: str, entry: dict, level: str, padding: str) -> pd.Series:
    field = get_field(entity, name)
    src = df[entry["source"]]
    if field.kind == "identifier":
        return _identifier(src, name, entity, level, padding)
    if entry.get("value_map") is not None:
        vm = {str(k): v for k, v in entry["value_map"].items()}
        return src.astype("string").map(lambda v: vm.get(str(v)) if pd.notna(v) else None).astype("string")
    if field.kind == "depth" and entry.get("uom") not in DEPTH_UOMS:
        raise DecisionRequired(f"{name}: declare uom ('ft' or 'm') in the spec; it is never inferred")
    return pd.Series(_cast(src, field.dtype), index=src.index)


def _crs_column(df: pd.DataFrame, source_crs: str) -> pd.Series:
    if source_crs.startswith("column:"):
        col = source_crs.split(":", 1)[1]
        return df[col].map(lambda v: resolve_crs(v) if pd.notna(v) else None).astype("string")
    if source_crs == "not_applicable":
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return pd.Series(resolve_crs(source_crs), index=df.index, dtype="string")


def _with_target_crs(out: pd.DataFrame, spec: dict, target_crs: str | None) -> pd.DataFrame:
    if not target_crs:
        return out
    target = resolve_crs(target_crs)
    for label in spec.get("coordinates", {}):
        lat, lon = f"{label}_latitude", f"{label}_longitude"
        parts = []
        for crs, group in out.groupby("source_crs", dropna=True):
            y, x = transform_coordinates(group[lat], group[lon], crs, target)
            parts.append(pd.DataFrame({f"{lat}_target": y, f"{lon}_target": x}))
        if parts:
            out = out.join(pd.concat(parts))
    return out.assign(target_crs=target)


def _rejects(canonical: pd.DataFrame, entity: str) -> pd.DataFrame:
    reasons = pd.Series("", index=canonical.index, dtype="string")
    for f in fields(entity):
        if f.required and f.name in canonical:
            reasons = reasons.mask(canonical[f.name].isna(), reasons + f"null_{f.name};")
    return canonical.assign(reject_reason=reasons)[reasons != ""]


def _conflicting_duplicates(canonical: pd.DataFrame, key: str) -> pd.Index:
    attrs = [c for c in canonical.columns if c not in (key, "source_row")]
    dupes = canonical[canonical.duplicated(key, keep=False)]
    if dupes.empty:
        return pd.Index([])
    conflicting = dupes.groupby(key)[attrs].nunique(dropna=True).gt(1).any(axis=1)
    return dupes[dupes[key].isin(conflicting[conflicting].index)].index


def lineage(spec: dict, target_standard: str) -> pd.DataFrame:
    """One row per mapped field: source column -> canonical field -> OSDU path / PPDM column."""
    h = spec_hash(spec)
    rows = []
    for name, entry in _mapped(spec).items():
        f = get_field(spec["entity"], name)
        transform = ("api_level" if f.kind == "identifier" else "value_map" if entry.get("value_map") is not None
                     else f"cast:{f.dtype}")
        rows.append({"canonical_field": name, "source_column": entry["source"], "transform": transform,
                     "uom": entry.get("uom"),
                     "osdu_path": f.osdu_path if target_standard in ("osdu", "both") else None,
                     "ppdm_column": f.ppdm_column if target_standard in ("ppdm", "both") else None,
                     "spec_hash": h})
    return pd.DataFrame(rows)


def ppdm_view(canonical: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Canonical columns renamed to PPDM 3.9-style TABLE.COLUMN names (mapped fields only)."""
    names = {f.name: f.ppdm_column for f in fields(entity) if f.name in canonical}
    return canonical[list(names)].rename(columns=names)


def build_canonical(df: pd.DataFrame, spec: dict, *, source_identifier_level, api_padding, source_crs,
                    target_standard, target_crs: str | None = None) -> dict:
    """Apply a reviewed spec. Decisions are keyword-only with no defaults (DecisionRequired)."""
    _check_decisions(spec, source_identifier_level, api_padding, source_crs, target_standard)
    _check_level_against_data(df, spec, source_identifier_level)
    entity = spec["entity"]
    cols = {name: _value(df, entity, name, e, source_identifier_level, api_padding)
            for name, e in _mapped(spec).items()}
    uoms = {f"{n}_uom": e["uom"] for n, e in _mapped(spec).items() if get_field(entity, n).kind == "depth"}
    canonical = pd.DataFrame(cols).assign(source_row=df.index, **uoms)
    if spec.get("coordinates"):
        canonical = _with_target_crs(canonical.assign(source_crs=_crs_column(df, source_crs)), spec, target_crs)
    key = next(f.name for f in fields(entity) if f.kind == "identifier")
    conflict_idx = _conflicting_duplicates(canonical, key)
    parts = [_rejects(canonical, entity), canonical.loc[conflict_idx].assign(reject_reason="conflicting_duplicate")]
    non_empty = [p for p in parts if len(p)]
    rejects = pd.concat(non_empty) if non_empty else parts[0]
    clean = canonical.drop(index=rejects.index.unique()).drop_duplicates(subset=[c for c in canonical if c != "source_row"])
    return {"canonical": clean.reset_index(drop=True), "rejects": rejects.reset_index(drop=True),
            "lineage": lineage(spec, target_standard),
            "ppdm": ppdm_view(clean, entity) if target_standard in ("ppdm", "both") else None}
