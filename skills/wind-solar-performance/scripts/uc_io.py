"""Unity Catalog I/O for skill runners: validated identifiers, parameterized reads, governed writes.

Spark is imported lazily so this module imports offline (tests, local linting).

    from uc_io import read_table, write_table, write_manifest
    df = read_table("main.energy.activity", where="period_year = :yr", args={"yr": 2025})
    write_table(df, "main.energy.ghg_inventory", comment="ghg-emissions-calculator 0.1.0")
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

IDENT = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")


class IdentifierError(ValueError):
    """A Unity Catalog name failed validation."""


def validate_identifier(name: str) -> str:
    """Return the back-quoted form of a validated `catalog.schema.table` name."""
    if not isinstance(name, str) or not IDENT.match(name):
        raise IdentifierError(f"Invalid Unity Catalog identifier: {name!r}")
    return ".".join(f"`{part}`" for part in name.split("."))


def get_spark():
    """Return the active SparkSession, or a Databricks Connect session when run locally."""
    try:
        from pyspark.sql import SparkSession

        active = SparkSession.getActiveSession()
        if active is not None:
            return active
    except ImportError:
        log.info("pyspark not importable; trying Databricks Connect")
    from databricks.connect import DatabricksSession

    return DatabricksSession.builder.getOrCreate()


def read_table(name: str, where: str | None = None, args: dict | None = None) -> pd.DataFrame:
    """Read a UC table into pandas. `where` may only reference named parameters (:name)."""
    quoted = validate_identifier(name)
    sql = f"SELECT * FROM {quoted}"
    if where:
        if ";" in where or "--" in where:
            raise ValueError("where clause may not contain ';' or comments")
        sql += f" WHERE {where}"
    return get_spark().sql(sql, args=args or {}).toPandas()


def _escape_literal(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def write_table(df: pd.DataFrame, name: str, comment: str,
                column_comments: dict | None = None, mode: str = "overwrite") -> str:
    """Write pandas to a UC Delta table with a table comment and optional column comments."""
    if mode not in {"overwrite", "append"}:
        raise ValueError(f"mode must be overwrite|append, got {mode!r}")
    quoted = validate_identifier(name)
    spark = get_spark()
    spark.createDataFrame(df).write.mode(mode).option("overwriteSchema", "true").saveAsTable(name)
    spark.sql(f"COMMENT ON TABLE {quoted} IS '{_escape_literal(comment)}'")
    for col, text in (column_comments or {}).items():
        if col not in df.columns or not re.match(r"^[A-Za-z0-9_]+$", col):
            log.warning("skipping comment for unknown/invalid column %s", col)
            continue
        spark.sql(f"ALTER TABLE {quoted} ALTER COLUMN `{col}` COMMENT '{_escape_literal(text)}'")
    return name


def write_manifest(manifest: dict, name: str, skill: str, version: str) -> str:
    """Append one run manifest row (JSON payload) to a UC table."""
    row = pd.DataFrame([{
        "skill": skill,
        "skill_version": version,
        "run_ts_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_json": json.dumps(manifest, default=str, sort_keys=True),
    }])
    return write_table(row, name, comment=f"{skill} {version} run manifests", mode="append")
