#!/usr/bin/env python3
"""Entrypoints: preview the semantic layer a mapping supports, then build it on confirmation.

Purpose
    preview_semantic_layer         READ-ONLY. Validates the catalog, infers scope from the
                                   mapping, lists metric views built / skipped and the
                                   decisions the user must make. Generates nothing.
    build_confirmed_semantic_layer Requires every needed decision. Writes 01_silver.sql,
                                   03_metric_views.sql, plan.md and manifest.json to `out`.

Usage
    python3 scripts/generate_semantic_layer.py --mapping acme_mapping.yaml --preview
    python3 scripts/generate_semantic_layer.py --mapping acme_mapping.yaml --out generated \\
        --decision gas_mcf_per_boe=energy_6 --decision gads_weighting=mw_weighted \\
        --decision capacity_basis=net_summer --decision heat_rate_basis=hhv
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from semantic_core import (
    REFS,
    build_silver,
    check_uc_name,
    load_catalog,
    metric_view_body,
    metric_view_sql,
    plan_scope,
    require_decisions,
    validate_catalog,
)

SKILL_VERSION = "0.1.0"


def load_mapping(path_or_dict) -> dict:
    """Load a mapping (dict or YAML path), resolving `extends:` adapters in order."""
    if isinstance(path_or_dict, dict):
        mapping = path_or_dict
    else:
        mapping = yaml.safe_load(Path(path_or_dict).read_text(encoding="utf-8")) or {}
    merged: dict = {"entities": {}}
    for parent in mapping.get("extends") or []:
        base = load_mapping(REFS / parent)
        merged = {**merged, **base, "entities": {**merged["entities"], **base.get("entities", {})}}
    entities = {**merged.get("entities", {}), **(mapping.get("entities") or {})}
    return {**merged, **mapping, "entities": entities}


def _target(mapping: dict) -> str:
    t = mapping.get("target") or {}
    name = f"{t.get('catalog')}.{t.get('schema')}"
    check_uc_name(name)
    return name


def preview_semantic_layer(mapping) -> dict:
    """READ-ONLY: what would be built, what would be skipped, which decisions are needed."""
    cat = load_catalog()
    report = validate_catalog(cat)
    m = load_mapping(mapping)
    scope = plan_scope(cat, m)
    lines = ["Semantic layer preview — READ-ONLY, nothing generated.",
             f"  catalog: {len(cat.measures)} measures, {len(cat.metric_views)} metric views; "
             f"validation: {len(report.errors)} error(s), {len(report.warnings)} warning(s)"]
    lines += _view_lines(scope["views"])
    lines += ["", "Decisions needed (no defaults):"]
    for name in scope["decisions_needed"]:
        spec = cat.decisions[name]
        opts = ", ".join(f"{k} ({v.get('note', '')})" for k, v in spec["options"].items())
        lines.append(f"  - {name}: {spec['question']} Options: {opts}")
    return {"ok": report.ok, "errors": report.errors, "scope": scope,
            "decisions_needed": scope["decisions_needed"], "readout": "\n".join(lines)}


def _view_lines(views: dict) -> list[str]:
    out = []
    for name, v in views.items():
        if v["built"]:
            extra = f"; skipped {v['skipped']}" if v["skipped"] else ""
            out.append(f"  BUILD {name} ({len(v['measures'])} measures){extra}")
        else:
            out.append(f"  SKIP  {name} — {v['reason']}")
    return out


def build_confirmed_semantic_layer(mapping, decisions: dict | None, out: str | Path) -> dict:
    """Generate SQL under confirmed decisions. Raises DecisionRequired / ValueError."""
    cat = load_catalog()
    report = validate_catalog(cat)
    if not report.ok:
        raise ValueError("Measure catalog failed validation: " + "; ".join(report.errors))
    m = load_mapping(mapping)
    target = _target(m)
    scope = plan_scope(cat, m)
    resolved = require_decisions(cat, scope["decisions_needed"], decisions)
    silver = [build_silver(e, emap, target, cat.entities[e]) for e, emap in m["entities"].items()
              if e in cat.entities]
    mv_sql = [metric_view_sql(f"{target}.{name}",
                              metric_view_body(cat, name, v, target, resolved, SKILL_VERSION))
              for name, v in scope["views"].items() if v["built"]]
    manifest = _manifest(m, decisions, scope, cat.version)
    files = {"01_silver.sql": "\n\n".join(silver) + "\n",
             "03_metric_views.sql": "\n\n".join(mv_sql) + "\n",
             "plan.md": _plan_md(target, scope, decisions),
             "manifest.json": json.dumps(manifest, indent=2, default=str)}
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    return {"files": files, "manifest": manifest, "out": str(out_dir)}


def _plan_md(target: str, scope: dict, decisions: dict | None) -> str:
    lines = ["# Generation plan", "", f"Target: `{target}`", "",
             "## Decisions", ""]
    lines += [f"- `{k}` = `{v}`" for k, v in sorted((decisions or {}).items())]
    lines += ["", "## Metric views", ""] + [f"-{x[1:]}" for x in _view_lines(scope["views"])]
    return "\n".join(lines) + "\n"


def _manifest(mapping: dict, decisions: dict | None, scope: dict, catalog_version: str) -> dict:
    return {"skill": "energy-semantic-builder", "skill_version": SKILL_VERSION,
            "catalog_version": catalog_version,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "mapping_name": mapping.get("name"), "target": mapping.get("target"),
            "decisions": decisions or {},
            "sources": {e: v.get("source") for e, v in mapping["entities"].items()},
            "metric_views": {n: [m["name"] for m in v.get("measures", [])]
                             for n, v in scope["views"].items() if v["built"]}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mapping", required=True)
    ap.add_argument("--out", default="generated")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--decision", action="append", default=[], help="name=option")
    args = ap.parse_args(argv)
    if args.preview:
        print(preview_semantic_layer(args.mapping)["readout"])
        return 0
    decisions = dict(d.split("=", 1) for d in args.decision)
    result = build_confirmed_semantic_layer(args.mapping, decisions, args.out)
    print(f"wrote {sorted(result['files'])} to {result['out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
