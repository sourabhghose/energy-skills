"""Databricks entrypoints for ami-interval-analytics — EXECUTION model.

Genie Code CALLS these two functions and reports their output. It does not hand-write VEE SQL
and does not choose a decision-point value itself.

    import sys; sys.path.append('<this-skill-dir>/scripts')
    from ami_run import preview_vee_options, build_confirmed_vee

    print(preview_vee_options("main.ami.interval_reads", source_timezone="America/Chicago"))
    # ...user answers every decision shown in the preview...
    print(build_confirmed_vee("main.ami.interval_reads", "main.ami.interval_vee",
                              interval_minutes=15, source_timezone="America/Chicago",
                              timestamp_basis="local_naive", interval_convention="ending",
                              read_type="interval", net_metering_policy="negative_is_export",
                              linear_max_gap_intervals=4, long_gap_method="like_day",
                              max_estimation_gap_hours=72, spike_max_kw=48))

``preview_vee_options`` is READ-ONLY. ``build_confirmed_vee`` requires every decision.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ami_decisions  # noqa: E402
import ami_estimate  # noqa: E402
import ami_pipeline  # noqa: E402
import ami_time  # noqa: E402
import ami_validate  # noqa: E402
from _uc import (get_spark, quote_identifier, read_query, ship_modules_by_value,  # noqa: E402
                 validate_identifier, write_manifest, write_table)
from ami_decisions import DECISIONS, SKILL_VERSION, build_manifest, make_config  # noqa: E402
from ami_pipeline import OUTPUT_SCHEMA, preview_profile, vee_meter, vee_summary  # noqa: E402

COLUMN_COMMENTS = {
    "interval_start_utc": "Interval start (interval-beginning convention), UTC",
    "interval_start_local": "Interval start in meter local time with UTC offset (DST explicit)",
    "local_date": "Local calendar date of interval start (23/25-hour days on DST transitions)",
    "raw_kwh": "Value as received after register differencing, kWh per interval",
    "kwh": "Validated / estimated energy, kWh per interval (NULL when MISSING)",
    "quality_code": "ACTUAL | SOURCE_ESTIMATED | ESTIMATED_LINEAR | ESTIMATED_LIKE_DAY | "
                    "ESTIMATED_REGISTER_PRORATED | MISSING",
    "flags": "Pipe-separated validation flags raised on this interval",
}


def _select_sql(table: str, cols: dict[str, str | None], sample_meters: int | None) -> str:
    validate_identifier(table, fully_qualified=True)
    exprs = [f"CAST({quote_identifier(src)} AS STRING) AS {alias}" if alias == "meter_id"
             else f"{quote_identifier(src)} AS {alias}"
             for alias, src in cols.items() if src]
    sql = f"SELECT {', '.join(exprs)} FROM {quote_identifier(table)}"
    if sample_meters:
        meter = quote_identifier(cols["meter_id"])
        sql += (f" WHERE {meter} IN (SELECT DISTINCT {meter} FROM {quote_identifier(table)} "
                f"ORDER BY {meter} LIMIT {int(sample_meters)})")
    return sql


def _format_preview(profile: dict) -> str:
    lines = ["AMI VEE PREVIEW (read-only — nothing was built)", ""]
    lines += [f"  {k}: {json.dumps(v, default=str)}" for k, v in profile.items()]
    lines += ["", "DECISIONS REQUIRED before build_confirmed_vee (ask the user; do not pick):"]
    lines += [f"  - {name}: {spec['options']}  — {spec['why']}" for name, spec in DECISIONS.items()]
    if profile.get("detected_read_type") == "register":
        lines.append("  - register_rollover_kwh: dial capacity (e.g. 100000 for 5 dials)")
    return "\n".join(lines)


def preview_vee_options(table: str, *, meter_col: str = "meter_id", ts_col: str = "read_ts",
                        value_col: str = "kwh", quality_col: str | None = None,
                        source_timezone: str | None = None, sample_meters: int = 200,
                        warehouse_id: str | None = None, profile: str | None = None) -> str:
    """READ-ONLY. Profile a sample of meters and list every decision with its effect."""
    cols = {"meter_id": meter_col, "read_ts": ts_col, "value": value_col, "quality": quality_col}
    raw = read_query(_select_sql(table, cols, sample_meters),
                     warehouse_id=warehouse_id, profile=profile)
    return _format_preview(preview_profile(raw, source_timezone))


def build_confirmed_vee(table: str, output_table: str, *, interval_minutes=None,
                        source_timezone=None, timestamp_basis=None, interval_convention=None,
                        read_type=None, net_metering_policy=None, linear_max_gap_intervals=None,
                        long_gap_method=None, max_estimation_gap_hours=None, spike_max_kw=None,
                        register_rollover_kwh=None, net_metered_meter_ids=None,
                        meter_col: str = "meter_id",
                        ts_col: str = "read_ts", value_col: str = "kwh",
                        quality_col: str | None = None) -> str:
    """Materialize ``output_table`` (validated intervals), ``<output>_summary`` and a manifest.

    Every decision argument is required; ``None`` raises ``DecisionRequired``.
    """
    cfg = make_config(
        interval_minutes=interval_minutes, source_timezone=source_timezone,
        timestamp_basis=timestamp_basis, interval_convention=interval_convention,
        read_type=read_type, net_metering_policy=net_metering_policy,
        linear_max_gap_intervals=linear_max_gap_intervals, long_gap_method=long_gap_method,
        max_estimation_gap_hours=max_estimation_gap_hours, spike_max_kw=spike_max_kw,
        register_rollover_kwh=register_rollover_kwh,
        net_metered_meter_ids=net_metered_meter_ids)
    validate_identifier(output_table, fully_qualified=True)
    cols = {"meter_id": meter_col, "read_ts": ts_col, "value": value_col, "quality": quality_col}
    spark = get_spark()
    if spark is None:
        raise RuntimeError("build_confirmed_vee needs Python compute with Spark (serverless).")
    ship_modules_by_value(ami_decisions, ami_time, ami_validate, ami_estimate, ami_pipeline)
    source = spark.sql(_select_sql(table, cols, None))
    validated = source.groupBy("meter_id").applyInPandas(lambda g: vee_meter(g, cfg),
                                                         schema=OUTPUT_SCHEMA)
    validated.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(output_table)
    _comment_columns(spark, output_table)
    out = spark.table(output_table).toPandas() if _small(spark, output_table) else None
    summary = _summary_table(spark, output_table, cfg, out)
    manifest = build_manifest(cfg, {"table": table, "rows": source.count()},
                              {"validated": output_table, "summary": f"{output_table}_summary"})
    write_manifest(manifest, f"{output_table}_manifest")
    return _format_build(summary, manifest)


def _small(spark, fqn: str, limit: int = 2_000_000) -> bool:
    return spark.table(fqn).count() <= limit


def _comment_columns(spark, fqn: str) -> None:
    from _uc import sql_string_literal

    quoted = quote_identifier(fqn)
    spark.sql(f"COMMENT ON TABLE {quoted} IS "
              f"{sql_string_literal(f'AMI VEE output (ami-interval-analytics {SKILL_VERSION})')}")
    for col, text in COLUMN_COMMENTS.items():
        spark.sql(f"ALTER TABLE {quoted} ALTER COLUMN {quote_identifier(col)} "
                  f"COMMENT {sql_string_literal(text)}")


def _summary_table(spark, fqn: str, cfg, out):
    if out is None:
        sql = (f"SELECT meter_id, quality_code, count(*) AS intervals, sum(kwh) AS kwh "
               f"FROM {quote_identifier(fqn)} GROUP BY ALL")
        summary = spark.sql(sql).toPandas()
    else:
        summary = vee_summary(out, cfg)
    write_table(summary, f"{fqn}_summary",
                table_comment=f"Per-meter VEE summary (ami-interval-analytics {SKILL_VERSION})")
    return summary


def _format_build(summary, manifest: dict) -> str:
    lines = ["AMI VEE BUILD COMPLETE", f"  run_id: {manifest['run_id']}",
             f"  outputs: {manifest['outputs']}", "  decisions:"]
    lines += [f"    {k} = {v}" for k, v in manifest["decisions"].items()]
    lines += ["", "  summary (first 20 meters):", summary.head(20).to_string(index=False)]
    return "\n".join(lines)
