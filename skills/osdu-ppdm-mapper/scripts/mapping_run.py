"""Databricks runner for osdu-ppdm-mapper: propose -> preview (read-only) -> confirmed build.

Purpose: Genie Code calls these entrypoints instead of hand-writing mapping SQL.
  * propose_mapping_spec(...)    profiles the source and writes a *proposed* YAML spec
  * preview_mapping_options(...) READ-ONLY review report for a spec; builds nothing
  * build_confirmed_mapping(...) needs a spec with status: reviewed and every decision

Usage (Python compute):
    import sys; sys.path.append("<skill-dir>/scripts")
    from mapping_run import propose_mapping_spec, preview_mapping_options, build_confirmed_mapping
    print(propose_mapping_spec("main.raw.well_header", "wellbore", "/Volumes/main/raw/specs/wb.yaml"))
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from mapping_apply import build_canonical, preview_mapping
from mapping_spec import load_spec, profile_source, propose_mapping, spec_hash, spec_to_yaml
from osdu_records import to_osdu_records
from uc_io import build_manifest, markdown, run_sql, validate_fqn, write_manifest, write_table

LOG = logging.getLogger(__name__)
SKILL, VERSION = "osdu-ppdm-mapper", "0.1.0"


def _read(table: str, limit: int, warehouse_id, profile) -> pd.DataFrame:
    return run_sql("SELECT * FROM {t} LIMIT :n", {"n": int(limit)}, tables={"t": validate_fqn(table)},
                   warehouse_id=warehouse_id, profile=profile)


def _spec(spec) -> dict:
    return spec if isinstance(spec, dict) else load_spec(spec)


def propose_mapping_spec(source_table: str, entity: str, spec_path: str | None = None,
                         sample_rows: int = 5000, warehouse_id: str | None = None,
                         profile: str | None = None) -> str:
    """Profile the source and propose a mapping spec (status: proposed). Writes only the YAML file."""
    df = _read(source_table, sample_rows, warehouse_id, profile)
    spec = propose_mapping(df, entity, source_table)
    text = spec_to_yaml(spec)
    if spec_path:
        with open(spec_path, "w", encoding="utf-8") as fh:
            fh.write(text)
    prof = profile_source(df)[["column", "dtype", "null_pct", "distinct", "examples"]]
    rows = [f"| {k} | {v['source'] or '—'} | {v['confidence']:.2f} | {v['reason']} |"
            for k, v in spec["fields"].items()]
    return "\n".join([
        f"# Proposed {entity} mapping for {source_table} ({len(df)} sampled rows)",
        "## Source profile", markdown(prof),
        "## Proposed field mapping (review every row)",
        "| canonical field | source column | confidence | reason |", "|---|---|---|---|", *rows,
        f"\nSpec written to {spec_path}" if spec_path else "\nSpec (YAML):\n" + text,
        "Next: edit the spec (uom, value_map nulls, crs), set status: reviewed, run preview_mapping_options.",
    ])


def _section(title: str, payload) -> str:
    return f"## {title}\n" + (json.dumps(payload, indent=2, default=str) if payload else "none")


def preview_mapping_options(source_table: str, spec, sample_rows: int = 20000,
                            warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Everything the reviewer must resolve before build_confirmed_mapping."""
    spec = _spec(spec)
    rep = preview_mapping(_read(source_table, sample_rows, warehouse_id, profile), spec)
    return "\n".join([
        f"# Mapping preview — {source_table} → {rep['entity']} (spec status: {rep['status']}, READ-ONLY)",
        f"Rows sampled: {rep['rows']}",
        _section("Unmapped required fields", rep["unmapped_required"]),
        _section("Low-confidence mappings (<0.8)", rep["low_confidence"]),
        _section("Cast failures", rep["cast_failures"]),
        _section("Identifier levels (decision source_identifier_level / api_padding)", rep["identifier_levels"]),
        _section("Identifier collisions (same ID, conflicting attributes)", rep["collisions"]),
        _section("Unmapped reference values (fill value_map)", rep["unmapped_reference_values"]),
        _section("Depth fields without uom", rep["depth_fields_missing_uom"]),
        _section("Coordinates (decision source_crs)", rep["coordinates"]),
        _section("Datum values found in source columns", rep["datum_values_in_source"]),
        "\nDecisions for build_confirmed_mapping: source_identifier_level, api_padding, "
        "source_crs, target_standard. NAD27 vs NAD83 cannot be told apart from the numbers.",
    ])


def _write_all(out: dict, output_prefix: str, manifest: dict) -> list[str]:
    comment = f"{SKILL} v{VERSION}; spec_hash={manifest['spec_hash']}"
    names = [k for k in ("canonical", "rejects", "lineage", "ppdm") if out.get(k) is not None]
    written = []
    for name in names:
        df = out[name]
        safe = df.rename(columns=lambda c: c.replace(".", "__")) if name == "ppdm" else df
        written.append(write_table(safe.astype({c: "string" for c in safe.columns if safe[c].dtype == object}),
                                   f"{output_prefix}_{name}", comment))
    write_manifest(manifest, f"{output_prefix}_run_manifest")
    return written


def _osdu(out: dict, entity: str, osdu: dict | None, path: str | None) -> list[dict] | None:
    if not osdu:
        return None
    records = to_osdu_records(out["canonical"], entity, **osdu)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"kind": "osdu:wks:Manifest:1.0.0", "MasterData": records}, fh, indent=2, default=str)
    return records


def build_confirmed_mapping(source_table: str, spec, output_prefix: str, *, source_identifier_level,
                            api_padding, source_crs, target_standard, target_crs: str | None = None,
                            osdu: dict | None = None, osdu_manifest_path: str | None = None,
                            max_rows: int = 5_000_000, warehouse_id: str | None = None,
                            profile: str | None = None, write: bool = True) -> dict:
    """Apply a reviewed spec; write canonical, rejects, lineage, PPDM view, manifest."""
    spec = _spec(spec)
    validate_fqn(output_prefix)
    df = _read(source_table, max_rows, warehouse_id, profile)
    decisions = {"source_identifier_level": source_identifier_level, "api_padding": api_padding,
                 "source_crs": source_crs, "target_standard": target_standard, "target_crs": target_crs}
    out = build_canonical(df, spec, source_identifier_level=source_identifier_level, api_padding=api_padding,
                          source_crs=source_crs, target_standard=target_standard, target_crs=target_crs)
    out = {**out, "osdu_records": _osdu(out, spec["entity"], osdu, osdu_manifest_path)}
    manifest = build_manifest(SKILL, VERSION,
                              {"source_table": source_table, "rows": len(df), "truncated": len(df) >= max_rows},
                              decisions, {"entity": spec["entity"], "spec_hash": spec_hash(spec), "spec": spec,
                                          "canonical_rows": len(out["canonical"]), "rejects": len(out["rejects"])})
    if write:
        manifest = {**manifest, "tables": _write_all(out, output_prefix, manifest)}
    return {"manifest": manifest, **out}


def format_result(result: dict) -> str:
    m = result["manifest"]
    reasons = result["rejects"]["reject_reason"].value_counts().to_dict() if len(result["rejects"]) else {}
    return "\n".join([
        f"# Mapping result — {m['entity']} (spec {m['spec_hash']})",
        f"Decisions: {m['decisions']}",
        f"Canonical rows: {m['canonical_rows']}  Rejected rows: {m['rejects']}  Reasons: {reasons or 'none'}",
        "## Lineage", markdown(result["lineage"]),
    ])
