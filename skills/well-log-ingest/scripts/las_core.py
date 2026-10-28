"""Profile and normalize parsed LAS files (pandas only; no lasio, no Spark).

profile_las   -> FileProfile: version, depth unit/datum, elevations, API check, per-curve
                 family / unit status / sentinel counts, and the decisions this file needs.
normalize_las -> NormalizedLas: one header row, curve-catalog rows, and a tidy long frame
                 (depth in the chosen unit and datum, values in canonical family units).

Usage:
    from las_core import profile_las, normalize_las, IngestDecisions
    prof = profile_las(parsed)
    norm = normalize_las(parsed, decisions)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from api_number import API_ZERO_PAD_OPTIONS, check_api
from las_parse import ParsedLas
from mnemonics import (
    DEPTH_SCALE,
    FAMILIES,
    candidate_units,
    family_of,
    infer_unit_from_values,
    normalize_unit_string,
    resolve_unit,
)

COMMON_SENTINELS = (-999.25, -999.0, -9999.0, -99999.0, -999.2500, 999.25, -9999.25)
SENTINEL_POLICIES = ("header_null_only", "common_sentinels")
DEPTH_UNITS = ("ft", "m")
DEPTH_DATUMS = ("as_logged", "KB", "DF", "GL")
CONFLICT_POLICIES = ("keep_all", "first_listed")
DATUM_ALIASES = {"KB": "KB", "KELLYBUSHING": "KB", "RKB": "KB", "DF": "DF", "DERRICKFLOOR": "DF",
                 "DRILLFLOOR": "DF", "GL": "GL", "GROUNDLEVEL": "GL", "GROUND": "GL"}


class DecisionRequired(ValueError):
    """An ingest choice that belongs to the user was not supplied (or is invalid)."""

    def __init__(self, decision: str, options, why: str):
        self.decision, self.options, self.why = decision, tuple(options), why
        super().__init__(f"Decision required: {decision!r} ({why}). Options: {', '.join(map(str, options))}")


@dataclass(frozen=True)
class CurveProfile:
    mnemonic: str
    family: str
    declared_unit: str
    status: str                 # ok | ambiguous_unit | implausible_range | unmapped
    proposed_unit: str | None
    n_values: int
    n_null: int
    n_sentinel: int
    median: float | None


@dataclass(frozen=True)
class FileProfile:
    source: str
    version: str
    wrap: bool
    index_mnemonic: str
    depth_unit: str | None
    logged_from: str | None
    elevations: dict
    api: dict
    curves: tuple[CurveProfile, ...]
    family_conflicts: dict
    warnings: tuple[str, ...] = ()

    def decisions_needed(self) -> list[str]:
        needed = [f"unit_resolution[{self.source}::{c.mnemonic}]" for c in self.curves
                  if c.status in ("ambiguous_unit", "implausible_range")]
        if self.depth_unit is None:
            needed.append(f"unit_resolution[{self.source}::{self.index_mnemonic}] (depth unit)")
        if self.api["status"] == "leading_zero_lost":
            needed.append("api_zero_pad")
        if self.family_conflicts:
            needed.append("family_conflict_policy")
        if any(c.n_sentinel for c in self.curves):
            needed.append("sentinel_policy")
        return needed


@dataclass(frozen=True)
class IngestDecisions:
    sentinel_policy: str
    depth_unit: str
    depth_datum: str
    family_conflict_policy: str
    unit_resolution: dict = field(default_factory=dict)
    api_zero_pad: str | None = None

    @classmethod
    def from_kwargs(cls, **kw) -> "IngestDecisions":
        checks = (("sentinel_policy", SENTINEL_POLICIES, "-999.25-style values may be real nulls or data"),
                  ("depth_unit", DEPTH_UNITS, "all depths are stored in one unit"),
                  ("depth_datum", DEPTH_DATUMS, "KB vs GL shifts every depth by the KB height"),
                  ("family_conflict_policy", CONFLICT_POLICIES, "two curves of one family in a file"))
        for name, options, why in checks:
            if kw.get(name) not in options:
                raise DecisionRequired(name, options, why)
        if not isinstance(kw.get("unit_resolution"), dict):
            raise DecisionRequired("unit_resolution", ("{} if the preview listed none",),
                                   "explicit units for every ambiguous curve")
        if kw.get("api_zero_pad") not in (None, *API_ZERO_PAD_OPTIONS):
            raise DecisionRequired("api_zero_pad", API_ZERO_PAD_OPTIONS, "restore dropped leading zeros?")
        return cls(kw["sentinel_policy"], kw["depth_unit"], kw["depth_datum"], kw["family_conflict_policy"],
                   dict(kw["unit_resolution"]), kw.get("api_zero_pad"))

    def as_dict(self) -> dict:
        return asdict(self)


# --- Profiling ------------------------------------------------------------------------


def _sentinel_mask(values: pd.Series) -> pd.Series:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    hit = np.zeros(arr.shape, dtype=bool)
    for s in COMMON_SENTINELS:
        hit |= np.isclose(arr, s, rtol=0, atol=1e-6)
    return pd.Series(hit, index=values.index)


def _curve_status(family: str, unit: str, values: pd.Series) -> tuple[str, str | None, float | None]:
    clean = pd.to_numeric(values, errors="coerce")
    clean = clean[~_sentinel_mask(clean)].dropna()
    median = float(clean.median()) if len(clean) else None
    if family == "UNMAPPED":
        return "unmapped", None, median
    resolved = resolve_unit(family, unit)
    proposed = infer_unit_from_values(family, median) if median is not None else None
    if resolved is None:
        return "ambiguous_unit", proposed, median
    lo, hi = FAMILIES[family].plausible
    if median is not None and not lo <= median * resolved[1] <= hi:
        return "implausible_range", proposed, median
    return "ok", None, median


def _profile_curve(parsed: ParsedLas, curve) -> CurveProfile:
    values = parsed.data[curve.mnemonic]
    family = family_of(curve.original_mnemonic)
    status, proposed, median = _curve_status(family, curve.unit, values)
    return CurveProfile(curve.mnemonic, family, curve.unit, status, proposed, int(values.notna().sum()),
                        int(values.isna().sum()), int(_sentinel_mask(values).sum()), median)


def _elevations(parsed: ParsedLas, depth_unit: str | None) -> dict:
    out = {}
    for key in ("EKB", "EDF", "EGL"):
        item = parsed.well_item(key)
        if item is None:
            continue
        try:
            value = float(item.value)
        except ValueError:
            continue
        unit = resolve_unit("DEPTH", item.unit) or ((depth_unit, 1.0) if depth_unit else None)
        out[key[1:]] = {"value": value, "unit": unit[0] if unit else None}
    return out


def _logged_from(parsed: ParsedLas) -> str | None:
    raw = parsed.well_value("LMF", "DMF", "PDAT")
    return DATUM_ALIASES.get(raw.upper().replace(" ", "").replace("_", ""), None) if raw else None


def profile_las(parsed: ParsedLas) -> FileProfile:
    """Read-only profile of one parsed LAS file."""
    index = parsed.curves[0]
    strt = parsed.well.get("STRT")
    depth = resolve_unit("DEPTH", index.unit) or resolve_unit("DEPTH", strt.unit if strt else None)
    curves = tuple(_profile_curve(parsed, c) for c in parsed.curves[1:])
    families: dict[str, list[str]] = {}
    for c in curves:
        if c.family != "UNMAPPED":
            families.setdefault(c.family, []).append(c.mnemonic)
    api = check_api(parsed.well_value("API", "UWI", "APINO", "API_NUMBER"))
    return FileProfile(parsed.source, parsed.version, parsed.wrap, index.mnemonic,
                       depth[0] if depth else None, _logged_from(parsed),
                       _elevations(parsed, depth[0] if depth else None), asdict(api), curves,
                       {f: m for f, m in families.items() if len(m) > 1}, parsed.warnings)


# --- Normalization --------------------------------------------------------------------


def _resolution(decisions: IngestDecisions, source: str, mnemonic: str) -> str | None:
    return decisions.unit_resolution.get(f"{source}::{mnemonic}", decisions.unit_resolution.get(mnemonic))


def _curve_unit(decisions: IngestDecisions, source: str, cp: CurveProfile) -> tuple[str, float] | None:
    if cp.status == "unmapped":
        return normalize_unit_string(cp.declared_unit) or "unknown", 1.0
    if cp.status == "ok":
        return resolve_unit(cp.family, cp.declared_unit)
    chosen = _resolution(decisions, source, cp.mnemonic)
    if chosen is None:
        raise DecisionRequired(f"unit_resolution[{source}::{cp.mnemonic}]",
                               candidate_units(cp.family) or ["declared unit"],
                               f"{cp.family} declared '{cp.declared_unit}', median {cp.median}; "
                               f"proposed {cp.proposed_unit}")
    resolved = resolve_unit(cp.family, chosen)
    if resolved is None:
        raise ValueError(f"unit_resolution {chosen!r} is not a valid unit for family {cp.family}")
    return resolved


def _depth_series(parsed: ParsedLas, prof: FileProfile, decisions: IngestDecisions) -> pd.Series:
    unit = prof.depth_unit or (resolve_unit("DEPTH", _resolution(decisions, prof.source, prof.index_mnemonic))
                               or (None,))[0]
    if unit is None:
        raise DecisionRequired(f"unit_resolution[{prof.source}::{prof.index_mnemonic}]", ("F", "M"),
                               "depth index unit is missing or unrecognized")
    depth = pd.to_numeric(parsed.data[prof.index_mnemonic], errors="coerce") * DEPTH_SCALE[(unit, decisions.depth_unit)]
    if decisions.depth_datum == "as_logged":
        return depth
    return depth - _datum_shift(prof, unit, decisions)


def _datum_shift(prof: FileProfile, depth_unit: str, decisions: IngestDecisions) -> float:
    """Elevation(logged datum) - elevation(target datum), in the output depth unit."""
    target, logged = decisions.depth_datum, prof.logged_from
    if logged is None:
        raise ValueError(f"{prof.source}: LMF/DMF (log measured from) missing; cannot convert to {target}")
    if logged == target:
        return 0.0
    elev = prof.elevations
    if logged not in elev or target not in elev:
        raise ValueError(f"{prof.source}: need E{logged} and E{target} elevations to convert datum")

    def in_out(key):
        unit = elev[key]["unit"] or depth_unit
        return elev[key]["value"] * DEPTH_SCALE[(unit, decisions.depth_unit)]

    return in_out(logged) - in_out(target)


def _api(prof: FileProfile, decisions: IngestDecisions) -> tuple[str | None, str]:
    if prof.api["status"] == "leading_zero_lost":
        if decisions.api_zero_pad is None:
            raise DecisionRequired("api_zero_pad", API_ZERO_PAD_OPTIONS,
                                   f"{prof.source}: API '{prof.api['raw']}' lost its leading zero")
        fixed = check_api(prof.api["raw"], zero_pad=decisions.api_zero_pad)
        return fixed.normalized, fixed.status
    return prof.api["normalized"], prof.api["status"]


@dataclass(frozen=True)
class NormalizedLas:
    header: dict
    catalog: pd.DataFrame
    long: pd.DataFrame


def _kept_curves(prof: FileProfile, decisions: IngestDecisions) -> list[CurveProfile]:
    if decisions.family_conflict_policy == "keep_all":
        return list(prof.curves)
    seen, kept = set(), []
    for c in prof.curves:
        if c.family == "UNMAPPED" or c.family not in seen:
            kept.append(c)
            seen.add(c.family)
    return kept


def _clean_values(values: pd.Series, decisions: IngestDecisions) -> tuple[pd.Series, int]:
    numeric = pd.to_numeric(values, errors="coerce")
    if decisions.sentinel_policy != "common_sentinels":
        return numeric, 0
    mask = _sentinel_mask(numeric)
    return numeric.mask(mask), int(mask.sum())


def _catalog_row(prof, cp, unit, scale, n_replaced, canonical: pd.Series, kept: bool) -> dict:
    lo, hi = FAMILIES[cp.family].plausible if cp.family in FAMILIES else (-np.inf, np.inf)
    out_of_range = int(((canonical < lo) | (canonical > hi)).sum()) if kept else 0
    return {"source_file": prof.source, "mnemonic": cp.mnemonic, "family": cp.family,
            "unit_declared": cp.declared_unit, "unit_canonical": unit, "scale": scale, "status": cp.status,
            "kept": kept, "n_values": int(canonical.notna().sum()) if kept else cp.n_values,
            "n_null": cp.n_null, "n_sentinel_replaced": n_replaced, "n_out_of_range": out_of_range,
            "min": float(canonical.min()) if kept and canonical.notna().any() else None,
            "max": float(canonical.max()) if kept and canonical.notna().any() else None}


def _header_row(parsed: ParsedLas, prof: FileProfile, api: str | None, api_status: str,
                decisions: IngestDecisions) -> dict:
    elev = {f"elev_{k.lower()}": v["value"] for k, v in prof.elevations.items()}
    return {"source_file": prof.source, "file_sha256": parsed.sha256, "las_version": prof.version,
            "wrap": prof.wrap, "api14": api, "api_status": api_status, "uwi_raw": prof.api["raw"],
            "well_name": parsed.well_value("WELL"), "company": parsed.well_value("COMP"),
            "field": parsed.well_value("FLD"), "service_company": parsed.well_value("SRVC"),
            "log_date": parsed.well_value("DATE"), "latitude_raw": parsed.well_value("LATI", "LAT"),
            "longitude_raw": parsed.well_value("LONG", "LON"), "elev_kb": None, "elev_df": None, "elev_gl": None,
            **elev, "log_measured_from": prof.logged_from, "depth_unit_original": prof.depth_unit,
            "depth_unit": decisions.depth_unit, "depth_datum": decisions.depth_datum,
            "null_value": parsed.null_value, "warnings": "; ".join(prof.warnings)}


def normalize_las(parsed: ParsedLas, decisions: IngestDecisions) -> NormalizedLas:
    """Apply confirmed decisions to one file. Raises DecisionRequired for unresolved choices."""
    prof = profile_las(parsed)
    depth = _depth_series(parsed, prof, decisions)
    api, api_status = _api(prof, decisions)
    kept = {c.mnemonic for c in _kept_curves(prof, decisions)}
    rows, frames = [], []
    for cp in prof.curves:
        unit, scale = _curve_unit(decisions, prof.source, cp)
        values, n_replaced = _clean_values(parsed.data[cp.mnemonic], decisions)
        canonical = values * scale
        rows.append(_catalog_row(prof, cp, unit, scale, n_replaced, canonical, cp.mnemonic in kept))
        if cp.mnemonic in kept:
            frames.append(pd.DataFrame({"api14": api, "source_file": prof.source, "depth": depth,
                                        "family": cp.family, "mnemonic": cp.mnemonic,
                                        "value": canonical, "unit": unit}).dropna(subset=["value", "depth"]))
    long = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["api14", "source_file", "depth", "family", "mnemonic", "value", "unit"])
    long = long.assign(depth_unit=decisions.depth_unit, depth_datum=decisions.depth_datum)
    return NormalizedLas(_header_row(parsed, prof, api, api_status, decisions), pd.DataFrame(rows), long)
