"""unit-guard runner: audit a Unity Catalog table's units, then convert confirmed columns.

Two entrypoints (Databricks: Python compute; Spark is discovered at call time):

    from units_run import preview_unit_audit, build_confirmed_conversion

    # 1. READ-ONLY: lint column names, profile numeric ranges, list decisions per conversion.
    print(preview_unit_audit("main.ops.daily_production",
                             proposed=[{"column": "gas_mcf", "from_unit": "Mcf", "to_unit": "MSm3"}]))

    # 2. Only after the user has chosen every decision the preview listed.
    print(build_confirmed_conversion(
        "main.ops.daily_production", "main.ops.daily_production_si",
        conversions=[{"column": "gas_mcf", "from_unit": "Mcf", "to_unit": "MSm3", "new_column": "gas_msm3"}],
        decisions={"scf_standard_conditions": "60F_14.696psia"}))
"""

from __future__ import annotations

import logging
import re

from uc_io import build_manifest, get_spark, validate_identifier, write_manifest, write_table
from units_core import DecisionRequired, conversion_factor, dimension_of, required_decisions
from units_lint import lint_columns

logger = logging.getLogger(__name__)

SKILL, VERSION = "unit-guard", "0.1.0"
COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_conversions(conversions: list[dict], columns: list[str]) -> list[dict]:
    if not conversions:
        raise ValueError("conversions must list at least one {column, from_unit, to_unit}")
    checked = []
    for conv in conversions:
        column, new = conv.get("column"), conv.get("new_column") or conv.get("column")
        for name in (column, new):
            if not name or not COLUMN.match(name):
                raise ValueError(f"Invalid column name {name!r}")
        if column not in columns:
            raise ValueError(f"Column {column!r} not in table; available: {sorted(columns)}")
        dimension_of(conv["from_unit"])
        dimension_of(conv["to_unit"])
        checked.append({**conv, "new_column": new})
    return checked


def plan_conversions(conversions: list[dict], decisions: dict) -> list[dict]:
    """Resolve (scale, offset) per conversion; raises DecisionRequired for missing choices."""
    plan = []
    for conv in conversions:
        for name in required_decisions(conv["from_unit"], conv["to_unit"]):
            if decisions.get(name) is None:
                raise DecisionRequired(name, ("see preview_unit_audit",),
                                       f"needed to convert {conv['column']} {conv['from_unit']} -> {conv['to_unit']}")
        scale, offset = conversion_factor(conv["from_unit"], conv["to_unit"], decisions)
        plan.append({**conv, "scale": scale, "offset": offset})
    return plan


def _profile_numeric(sdf, max_columns: int = 40) -> list[str]:
    from pyspark.sql import functions as F

    numeric = [f.name for f in sdf.schema.fields
               if f.dataType.typeName() in ("double", "float", "integer", "long", "decimal", "short")]
    numeric = numeric[:max_columns]
    if not numeric:
        return []
    aggs = []
    for c in numeric:
        aggs += [F.min(c).alias(f"{c}__min"), F.expr(f"percentile_approx(`{c}`, 0.5)").alias(f"{c}__p50"),
                 F.max(c).alias(f"{c}__max")]
    row = sdf.agg(*aggs).collect()[0].asDict()
    return [f"  {c:32s} min={row[c + '__min']}  p50={row[c + '__p50']}  max={row[c + '__max']}" for c in numeric]


def preview_unit_audit(table: str, proposed: list[dict] | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Lint column units, profile ranges, and list decisions for proposed conversions."""
    spark = get_spark(profile)
    sdf = spark.table(validate_identifier(table))
    lines = [f"Unit audit for {table} ({len(sdf.columns)} columns). Nothing was written."]
    findings = lint_columns(sdf.columns)
    lines.append(f"\nColumn-name findings ({len(findings)}):")
    lines += [f"  [{f.severity}] {f.column}: {f.issue} -> {f.suggestion}" for f in findings] or ["  none"]
    lines.append("\nNumeric ranges (sanity-check magnitudes against the claimed unit):")
    lines += _profile_numeric(sdf) or ["  no numeric columns"]
    for conv in _validate_conversions(proposed or [], sdf.columns) if proposed else []:
        needed = required_decisions(conv["from_unit"], conv["to_unit"])
        lines.append(f"\n{conv['column']}: {conv['from_unit']} -> {conv['to_unit']} "
                     f"needs decisions: {needed or 'none'}")
    lines.append("\nAsk the user to confirm each decision, then call build_confirmed_conversion.")
    return "\n".join(lines)


def build_confirmed_conversion(table: str, output_table: str, conversions: list[dict],
                               decisions: dict, profile: str | None = None) -> str:
    """Write `output_table` with converted columns, column comments, and a run manifest.

    `decisions` has no default: pass {} only when preview_unit_audit listed none.
    """
    if decisions is None:
        raise DecisionRequired("decisions", ("dict from preview_unit_audit",), "pass {} if none were listed")
    from pyspark.sql import functions as F

    spark = get_spark(profile)
    sdf = spark.table(validate_identifier(table))
    plan = plan_conversions(_validate_conversions(conversions, sdf.columns), decisions)
    out = sdf
    for step in plan:
        out = out.withColumn(step["new_column"], F.col(step["column"]) * F.lit(step["scale"]) + F.lit(step["offset"]))
    comments = {s["new_column"]: f"unit={s['to_unit']}; from {s['column']} [{s['from_unit']}] "
                                 f"x {s['scale']:.10g} + {s['offset']:.10g}; {SKILL} {VERSION}" for s in plan}
    write_table(spark, out, validate_identifier(output_table),
                f"Unit-converted copy of {table} by {SKILL} {VERSION}", comments)
    manifest = build_manifest(SKILL, VERSION, {"table": table, "rows": out.count()}, decisions,
                              {"conversions": plan, "output_table": output_table})
    manifest_table = write_manifest(spark, output_table, manifest)
    lines = [f"Wrote {output_table} ({manifest['inputs']['rows']} rows); manifest in {manifest_table}."]
    lines += [f"  {s['new_column']} = {s['column']} x {s['scale']:.10g} + {s['offset']:.10g} "
              f"[{s['from_unit']} -> {s['to_unit']}]" for s in plan]
    return "\n".join(lines)
