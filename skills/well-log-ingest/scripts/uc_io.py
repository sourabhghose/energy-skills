"""Unity Catalog I/O helpers shared by this skill's runners.

Thin Databricks adapter: identifier validation, Spark session discovery, governed
table writes (table + column comments), and run-manifest persistence. Spark and the
Databricks SDK are imported lazily so this module imports offline.

Usage:
    from uc_io import get_spark, validate_identifier, write_table, write_manifest
    spark = get_spark()                       # active session, or Databricks Connect
    name = validate_identifier("main.energy.meter_reads")
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
VOLUME_PATH = re.compile(r"^/Volumes/[A-Za-z0-9_]+/[A-Za-z0-9_]+/[A-Za-z0-9_]+(/[A-Za-z0-9_.\-/]*)?$")


def validate_identifier(name: str) -> str:
    """Return `name` if it is a safe UC identifier (catalog.schema.table), else raise."""
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise ValueError(
            f"Invalid Unity Catalog identifier {name!r}: expected catalog.schema.table "
            "with letters, digits and underscores only."
        )
    return name


def validate_volume_path(path: str) -> str:
    """Return `path` if it is a /Volumes/<catalog>/<schema>/<volume>/... path, else raise."""
    if not isinstance(path, str) or ".." in path or not VOLUME_PATH.match(path):
        raise ValueError(f"Invalid UC Volume path {path!r}: expected /Volumes/<catalog>/<schema>/<volume>/...")
    return path


def quote_identifier(name: str) -> str:
    """Back-quote each part of a validated identifier for SQL text."""
    return ".".join(f"`{part}`" for part in validate_identifier(name).split("."))


def sql_string_literal(text: str) -> str:
    """Escape skill-generated text (never raw user input) as a SQL string literal."""
    return "'" + str(text).replace("\\", "\\\\").replace("'", "\\'") + "'"


def get_spark(profile: str | None = None):
    """Return the active Spark session, else a Databricks Connect session."""
    try:
        from pyspark.sql import SparkSession

        active = SparkSession.getActiveSession()
        if active is not None:
            return active
    except ImportError:
        logger.info("pyspark not importable; trying Databricks Connect")
    try:
        from databricks.connect import DatabricksSession
    except ImportError as exc:
        raise RuntimeError(
            "No Spark session found. Run inside a Databricks notebook / Genie Code with "
            "Python compute, or install databricks-connect and pass profile=."
        ) from exc
    builder = DatabricksSession.builder
    if profile:
        builder = builder.profile(profile)
    return builder.getOrCreate()


def write_table(spark, sdf, name: str, table_comment: str, column_comments: dict[str, str]) -> None:
    """Overwrite a UC table and attach table + column comments."""
    target = quote_identifier(name)
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(validate_identifier(name))
    spark.sql(f"COMMENT ON TABLE {target} IS {sql_string_literal(table_comment)}")
    for column, comment in column_comments.items():
        if column not in sdf.columns:
            continue
        spark.sql(
            f"ALTER TABLE {target} ALTER COLUMN `{column.replace('`', '')}` "
            f"COMMENT {sql_string_literal(comment)}"
        )


def build_manifest(skill: str, version: str, inputs: dict, decisions: dict, extra: dict | None = None) -> dict:
    """Assemble a reproducibility manifest (inputs, decisions, versions, timestamp)."""
    return {
        "skill": skill,
        "skill_version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "decisions": decisions,
        **(extra or {}),
    }


def write_manifest(spark, output_table: str, manifest: dict) -> str:
    """Append the manifest as a JSON row to `<output_table>_manifest`; return that table name."""
    manifest_table = validate_identifier(f"{output_table}_manifest")
    row = [(manifest["skill"], manifest["skill_version"], manifest["created_utc"],
            json.dumps(manifest, sort_keys=True, default=str))]
    sdf = spark.createDataFrame(row, "skill STRING, skill_version STRING, created_utc STRING, manifest_json STRING")
    sdf.write.mode("append").saveAsTable(manifest_table)
    return manifest_table
