"""well-log-ingest runner: LAS files in a UC Volume -> governed Delta tables.

    from las_run import preview_las_ingest, build_confirmed_las_ingest

    # 1. READ-ONLY: profile every LAS file and list the decisions they need.
    print(preview_las_ingest("/Volumes/main/subsurface/raw/las"))

    # 2. Only after the user answered every decision the preview listed.
    print(build_confirmed_las_ingest("/Volumes/main/subsurface/raw/las", "main.subsurface.logs",
          sentinel_policy="common_sentinels", depth_unit="ft", depth_datum="KB",
          family_conflict_policy="keep_all", unit_resolution={"NPHI": "PU"},
          api_zero_pad="pad", overlap_policy="prefer_latest_run"))

Outputs: <prefix>_well_header, <prefix>_curve_catalog, <prefix>_curves_long,
<prefix>_curves_wide (unless overlap_policy='skip_wide'), <prefix>_manifest.
Files are parsed on the driver (UC Volumes are mounted under /Volumes); for more than a few
thousand files, run in batches by sub-folder.
"""

from __future__ import annotations

import logging
import os

import pandas as pd

from las_core import DecisionRequired, IngestDecisions, normalize_las, profile_las
from las_parse import read_las
from las_wide import OVERLAP_POLICIES, to_wide
from uc_io import build_manifest, get_spark, validate_identifier, validate_volume_path, write_manifest, write_table

logger = logging.getLogger(__name__)

SKILL, VERSION = "well-log-ingest", "0.1.0"
MAX_PREVIEW_FILES = 50


def list_las_files(volume_path: str) -> list[str]:
    """All *.las files under a UC Volume path (recursive, sorted)."""
    root = validate_volume_path(volume_path)
    if os.path.isfile(root):
        return [root]
    found = [os.path.join(d, f) for d, _, files in os.walk(root) for f in files if f.lower().endswith(".las")]
    return sorted(found)


def _parse_all(paths: list[str]) -> tuple[list, dict[str, str]]:
    parsed, failed = [], {}
    for path in paths:
        try:
            parsed.append(read_las(path))
        except Exception as exc:  # lasio raises many exception types; record and continue
            logger.warning("Failed to parse %s: %s", path, exc)
            failed[path] = f"{type(exc).__name__}: {exc}"
    return parsed, failed


def _format_profile(prof) -> list[str]:
    lines = [f"{prof.source}  LAS {prof.version}{' WRAP' if prof.wrap else ''}  depth unit={prof.depth_unit}  "
             f"logged from={prof.logged_from}  elevations={ {k: v['value'] for k, v in prof.elevations.items()} }",
             f"  API: {prof.api['raw'] or '(none)'} -> {prof.api['status']} {prof.api['note']}"]
    for c in prof.curves:
        if c.status != "ok" or c.n_sentinel:
            lines.append(f"  {c.mnemonic:10s} {c.family:9s} unit='{c.declared_unit}' status={c.status} "
                         f"median={c.median} proposed={c.proposed_unit} sentinels={c.n_sentinel}")
    if prof.family_conflicts:
        lines.append(f"  family conflicts: {prof.family_conflicts}")
    lines += [f"  WARNING: {w}" for w in prof.warnings]
    needed = prof.decisions_needed()
    lines.append(f"  decisions needed: {needed or 'none beyond the global ones'}")
    return lines


def preview_las_ingest(volume_path: str, max_files: int = MAX_PREVIEW_FILES) -> str:
    """READ-ONLY. Profile LAS files; nothing is written."""
    paths = list_las_files(volume_path)
    parsed, failed = _parse_all(paths[:max_files])
    lines = [f"Found {len(paths)} LAS file(s) under {volume_path}; profiled {len(parsed)}. Nothing was written.", ""]
    for p in parsed:
        lines += _format_profile(profile_las(p)) + [""]
    lines += [f"PARSE FAILED {path}: {err}" for path, err in failed.items()]
    lines += ["Global decisions for build_confirmed_las_ingest:",
              "  sentinel_policy (header_null_only | common_sentinels), depth_unit (ft | m),",
              "  depth_datum (as_logged | KB | DF | GL), family_conflict_policy (keep_all | first_listed),",
              "  unit_resolution {'file::MNEM' or 'MNEM': unit}, api_zero_pad (pad | reject, if listed),",
              f"  overlap_policy {OVERLAP_POLICIES}."]
    return "\n".join(lines)


def ingest_parsed(parsed: list, decisions: IngestDecisions) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """Pure-pandas batch: (headers, catalog, long, errors). DecisionRequired propagates."""
    headers, catalogs, longs, errors = [], [], [], {}
    for p in parsed:
        try:
            norm = normalize_las(p, decisions)
        except DecisionRequired:
            raise
        except ValueError as exc:
            logger.warning("Skipping %s: %s", p.source, exc)
            errors[p.source] = str(exc)
            continue
        headers.append(norm.header)
        catalogs.append(norm.catalog)
        longs.append(norm.long)
    concat = (lambda frames: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())
    return pd.DataFrame(headers), concat(catalogs), concat(longs), errors


def build_confirmed_las_ingest(volume_path: str, output_prefix: str, *, sentinel_policy: str, depth_unit: str,
                               depth_datum: str, family_conflict_policy: str, unit_resolution: dict,
                               api_zero_pad: str | None, overlap_policy: str, depth_step: float | None = None,
                               profile: str | None = None) -> str:
    """Parse, normalize, and write all LAS files under volume_path with the user's decisions."""
    decisions = IngestDecisions.from_kwargs(
        sentinel_policy=sentinel_policy, depth_unit=depth_unit, depth_datum=depth_datum,
        family_conflict_policy=family_conflict_policy, unit_resolution=unit_resolution, api_zero_pad=api_zero_pad)
    if overlap_policy not in OVERLAP_POLICIES:
        raise DecisionRequired("overlap_policy", OVERLAP_POLICIES, "which run wins where runs overlap")
    validate_identifier(output_prefix)
    parsed, failed = _parse_all(list_las_files(volume_path))
    headers, catalog, long, errors = ingest_parsed(parsed, decisions)
    step = depth_step or (0.5 if depth_unit == "ft" else 0.1524)
    wide = to_wide(long, headers, overlap_policy, step) if not headers.empty else pd.DataFrame()
    spark = get_spark(profile)
    _write_outputs(spark, output_prefix, headers, catalog, long, wide)
    manifest = build_manifest(SKILL, VERSION, {"volume_path": volume_path, "files": len(parsed) + len(failed)},
                              {**decisions.as_dict(), "overlap_policy": overlap_policy, "depth_step": step},
                              {"parse_failed": failed, "skipped": errors})
    write_manifest(spark, output_prefix, manifest)
    return (f"Ingested {len(headers)} file(s) -> {output_prefix}_well_header, _curve_catalog, _curves_long"
            f"{', _curves_wide' if not wide.empty else ''}. {len(long):,} curve samples. "
            f"Parse failures: {len(failed)}; skipped: {len(errors)} {list(errors.items())[:5]}")


def _write_outputs(spark, prefix: str, headers, catalog, long, wide) -> None:
    tag = f"{SKILL} {VERSION}"
    write_table(spark, spark.createDataFrame(headers), f"{prefix}_well_header",
                f"One row per LAS file (well header, datum, API check) by {tag}",
                {"api14": "14-digit US API number (10-digit + 0000) or Canadian DLS UWI",
                 "depth_datum": "Datum of all depths in the curve tables"})
    write_table(spark, spark.createDataFrame(catalog), f"{prefix}_curve_catalog",
                f"Curve inventory with family, unit mapping and QC counts by {tag}",
                {"scale": "Multiplier from declared unit to unit_canonical"})
    write_table(spark, spark.createDataFrame(long), f"{prefix}_curves_long",
                f"Tidy curve samples in canonical units by {tag}",
                {"value": "Curve value in `unit` (canonical per family)", "depth": "Depth in depth_unit below depth_datum"})
    if not wide.empty:
        write_table(spark, spark.createDataFrame(wide), f"{prefix}_curves_wide",
                    f"One column per curve family; overlaps resolved per manifest by {tag}", {})
