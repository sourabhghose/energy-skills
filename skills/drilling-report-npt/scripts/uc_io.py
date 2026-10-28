"""Thin Unity Catalog I/O helpers shared by this skill's runner.

Purpose: validate UC identifiers, run parameterized SQL (Spark when present, else the
Databricks SDK statement API), write pandas results to UC tables with comments, and
persist run manifests. Spark and the SDK are imported lazily so this module imports
offline (unit tests never touch a workspace).

Usage:
    from uc_io import validate_fqn, run_sql, write_table, write_manifest
    rows = run_sql("SELECT * FROM {t} WHERE well_id = :w", {"w": "W-1"}, tables={"t": "c.s.t"})
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

LOG = logging.getLogger(__name__)
FQN_PATTERN = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
ENDPOINT_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]+$")


def validate_fqn(name: str) -> str:
    """Return `name` if it is a safe catalog.schema.table identifier, else raise."""
    if not isinstance(name, str) or not FQN_PATTERN.match(name):
        raise ValueError(f"Invalid Unity Catalog identifier: {name!r}")
    return name


def quote_fqn(name: str) -> str:
    """Back-quote each part of a validated identifier for SQL text."""
    return ".".join(f"`{part}`" for part in validate_fqn(name).split("."))


def validate_endpoint(name: str) -> str:
    """Serving endpoint names are inlined into ai_query(), so they must be strictly validated."""
    if not isinstance(name, str) or not ENDPOINT_PATTERN.match(name):
        raise ValueError(f"Invalid serving endpoint name: {name!r}")
    return name


def get_spark():
    """Return the active SparkSession, or None when running outside Databricks."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    return SparkSession.getActiveSession()


def _render(sql: str, tables: dict | None) -> str:
    quoted = {k: quote_fqn(v) for k, v in (tables or {}).items()}
    return sql.format(**quoted) if quoted else sql


def run_sql(sql: str, params: dict | None = None, tables: dict | None = None,
            warehouse_id: str | None = None, profile: str | None = None):
    """Run parameterized SQL and return a pandas DataFrame.

    `tables` maps `{placeholder}` names in `sql` to UC identifiers (validated + quoted).
    `params` are bound as named parameter markers (`:name`); values are never spliced.
    """
    statement = _render(sql, tables)
    spark = get_spark()
    if spark is not None:
        return spark.sql(statement, args=params or {}).toPandas()
    return _run_sql_sdk(statement, params or {}, warehouse_id, profile)


def _param(item_cls, name: str, value):
    """Typed statement parameter: ints/floats keep numeric SQL types (e.g. for LIMIT)."""
    if isinstance(value, bool):
        return item_cls(name=name, value=str(value).lower(), type="BOOLEAN")
    if isinstance(value, int):
        return item_cls(name=name, value=str(value), type="BIGINT")
    if isinstance(value, float):
        return item_cls(name=name, value=repr(value), type="DOUBLE")
    return item_cls(name=name, value=None if value is None else str(value), type="STRING")


def _run_sql_sdk(statement: str, params: dict, warehouse_id: str | None, profile: str | None):
    import pandas as pd
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    wh = warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not wh:
        raise ValueError("No Spark session: pass warehouse_id= or set DATABRICKS_WAREHOUSE_ID")
    resp = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=wh, wait_timeout="50s",
        parameters=[_param(StatementParameterListItem, k, v) for k, v in params.items()],
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        detail = resp.status.error.message if resp.status.error else resp.status.state
        raise RuntimeError(f"SQL failed: {detail}")
    cols = [c.name for c in resp.manifest.schema.columns]
    return pd.DataFrame((resp.result.data_array or []) if resp.result else [], columns=cols)


def write_table(pdf, fqn: str, table_comment: str, column_comments: dict | None = None) -> str:
    """Overwrite a UC table from pandas and attach table + column comments. Requires Spark."""
    spark = get_spark()
    if spark is None:
        raise RuntimeError("Writing UC tables needs Python compute with Spark (serverless or cluster)")
    target = quote_fqn(fqn)
    spark.createDataFrame(pdf).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn)
    spark.sql(f"COMMENT ON TABLE {target} IS :c", args={"c": table_comment})
    for col, text in (column_comments or {}).items():
        if col in pdf.columns:
            spark.sql(f"ALTER TABLE {target} ALTER COLUMN `{col}` COMMENT :c", args={"c": text})
    return fqn


def markdown(df) -> str:
    """Render a DataFrame as markdown, falling back to plain text when tabulate is absent."""
    try:
        return df.to_markdown(index=False)
    except ImportError:
        return df.to_string(index=False)


def build_manifest(skill: str, version: str, inputs: dict, decisions: dict, extra: dict | None = None) -> dict:
    """Assemble a reproducible run manifest (inputs, decisions, versions, timestamp)."""
    return {
        "skill": skill,
        "skill_version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs,
        "decisions": decisions,
        **(extra or {}),
    }


def write_manifest(manifest: dict, fqn: str) -> str:
    """Append the manifest as one JSON row to a UC table `<fqn>` (created if absent)."""
    import pandas as pd

    row = pd.DataFrame([{"skill": manifest["skill"], "created_utc": manifest["created_utc"],
                         "manifest_json": json.dumps(manifest, default=str, sort_keys=True)}])
    spark = get_spark()
    if spark is None:
        raise RuntimeError("Persisting the manifest needs Spark; save manifest_json manually instead")
    spark.createDataFrame(row).write.mode("append").saveAsTable(validate_fqn(fqn))
    LOG.info("manifest appended to %s", fqn)
    return fqn
