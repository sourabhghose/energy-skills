#!/usr/bin/env python3
"""Draft a source mapping from a schema's column inventory (every guess flagged # REVIEW).

Purpose
    draft_mapping(columns, target)  pure: {table: [columns]} -> mapping YAML text. For each
                                    canonical entity, picks the table with the most field
                                    matches (exact name, then synonyms) and binds fields.
    fetch_columns(catalog, schema)  Databricks: reads information_schema.columns with bound
                                    parameters via the SDK statement API.

Usage
    python3 scripts/profile_source.py --catalog main --schema ops_raw --warehouse-id <id> \\
        --target-catalog main --target-schema energy_semantic [--profile <p>]
"""

from __future__ import annotations

import argparse
import sys

from semantic_core import check_uc_name, load_catalog

MIN_REQUIRED_SHARE = 0.5


def _match(field: str, spec: dict, cols: list[str]) -> tuple[str | None, str]:
    lower = {c.lower(): c for c in cols}
    if field.lower() in lower:
        return lower[field.lower()], "exact"
    for syn in spec.get("synonyms") or []:
        if syn.lower() in lower:
            return lower[syn.lower()], f"synonym '{syn}'"
    return None, ""


def _best_table(fields: dict, columns: dict) -> tuple[str | None, dict]:
    best, best_hits = None, {}
    for table, cols in columns.items():
        hits = {f: _match(f, spec, cols) for f, spec in fields.items()}
        hits = {f: h for f, h in hits.items() if h[0]}
        if len(hits) > len(best_hits):
            best, best_hits = table, hits
    return best, best_hits


def _entity_block(entity: str, spec: dict, table: str, hits: dict) -> list[str]:
    lines = [f"  {entity}:", f"    source: {table}", "    fields:"]
    for field, fspec in spec["fields"].items():
        unit = f" [{fspec['unit']}]" if fspec.get("unit") else ""
        if field in hits:
            col, how = hits[field]
            flag = "" if how == "exact" else f"  # REVIEW: matched by {how}; confirm unit{unit}"
            lines.append(f"      {field}: {col}{flag}")
        elif fspec.get("required"):
            lines.append(f"      # {field}:   # REVIEW: required{unit}, unmapped")
    return lines


def draft_mapping(columns: dict[str, list[str]], target_catalog: str, target_schema: str,
                  name: str = "draft") -> str:
    cat = load_catalog()
    out = [f"name: {name}", "description: DRAFT from profile_source.py — review every # REVIEW",
           "target:", f"  catalog: {target_catalog}", f"  schema: {target_schema}", "entities:"]
    for entity, spec in cat.entities.items():
        table, hits = _best_table(spec["fields"], columns)
        required = [f for f, s in spec["fields"].items() if s.get("required")]
        share = sum(f in hits for f in required) / max(len(required), 1)
        if table is None or share < MIN_REQUIRED_SHARE:
            out.append(f"  # {entity}: no table covers its required fields — omitted")
            continue
        out.extend(_entity_block(entity, spec, table, hits))
    return "\n".join(out) + "\n"


def fetch_columns(catalog: str, schema: str, warehouse_id: str, profile: str | None = None) -> dict:
    """information_schema.columns for one schema, with bound parameters."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem

    check_uc_name(f"{catalog}.{schema}")
    w = WorkspaceClient(profile=profile)
    resp = w.statement_execution.execute_statement(
        warehouse_id=warehouse_id, wait_timeout="50s",
        statement=(f"SELECT table_name, column_name FROM {check_uc_name(catalog)}."
                   "information_schema.columns WHERE table_schema = :schema "
                   "ORDER BY table_name, ordinal_position"),
        parameters=[StatementParameterListItem(name="schema", value=schema)])
    if resp.status.error:
        raise RuntimeError(f"information_schema query failed: {resp.status.error.message}")
    columns: dict[str, list[str]] = {}
    for table, column in (resp.result.data_array or []):
        columns.setdefault(f"{catalog}.{schema}.{table}", []).append(column)
    return columns


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for flag in ("--catalog", "--schema", "--warehouse-id", "--target-catalog", "--target-schema"):
        ap.add_argument(flag, required=True)
    ap.add_argument("--profile")
    args = ap.parse_args(argv)
    cols = fetch_columns(args.catalog, args.schema, args.warehouse_id, args.profile)
    text = draft_mapping(cols, args.target_catalog, args.target_schema, args.schema)
    path = f"{args.schema}_mapping.draft.yaml"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {path} ({text.count('# REVIEW')} items to review)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
