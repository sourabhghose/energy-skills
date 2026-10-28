"""Unity Catalog helpers for this skill's runners.

Identifier validation, quoting, Spark / Databricks SDK access, and table + manifest writes.
Spark and the SDK are imported lazily so this module (and the core it sits next to) imports
offline for unit tests.

    from _uc import validate_identifier, read_table, write_table, write_manifest
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
FQN = re.compile(r"^[A-Za-z0-9_]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")


def validate_identifier(name: str, *, fully_qualified: bool = False) -> str:
    """Return ``name`` if it is a safe UC identifier, else raise ``ValueError``."""
    pattern = FQN if fully_qualified else IDENTIFIER
    if not isinstance(name, str) or not pattern.match(name):
        kind = "catalog.schema.table" if fully_qualified else "identifier"
        raise ValueError(f"Invalid Unity Catalog {kind}: {name!r}")
    return name


def quote_identifier(name: str) -> str:
    """Back-quote each part of a validated identifier."""
    validate_identifier(name)
    return ".".join(f"`{part}`" for part in name.split("."))


def sql_string_literal(text: str) -> str:
    """Escape a constant string for a SQL literal (used only for COMMENT text)."""
    escaped = str(text).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def get_spark():
    """Return the active SparkSession, or ``None`` when Spark is unavailable."""
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    return SparkSession.getActiveSession()


def read_table(fqn: str, columns: list[str] | None = None, limit: int | None = None,
               *, warehouse_id: str | None = None, profile: str | None = None):
    """Read a UC table into pandas via Spark when present, else the SDK statement API."""
    validate_identifier(fqn, fully_qualified=True)
    cols = ", ".join(quote_identifier(c) for c in columns) if columns else "*"
    statement = f"SELECT {cols} FROM {quote_identifier(fqn)}"
    if limit is not None:
        statement += f" LIMIT {int(limit)}"
    return read_query(statement, warehouse_id=warehouse_id, profile=profile)


def read_query(statement: str, *, warehouse_id: str | None = None, profile: str | None = None):
    """Run a SELECT built only from validated identifiers; return pandas.

    Callers must build ``statement`` from ``quote_identifier`` output and integer literals
    only, never from free user text.
    """
    spark = get_spark()
    if spark is not None:
        return spark.sql(statement).toPandas()
    return _read_via_sdk(statement, warehouse_id=warehouse_id, profile=profile)


def execute_sql(statement: str, *, warehouse_id: str | None = None,
                profile: str | None = None) -> None:
    """Run a DDL / DML statement built from validated identifiers and escaped constants."""
    spark = get_spark()
    if spark is not None:
        spark.sql(statement)
        return
    _read_via_sdk(statement, warehouse_id=warehouse_id, profile=profile)


def ship_modules_by_value(*modules) -> None:
    """Pickle skill modules by value so Spark workers need not import them from sys.path."""
    from pyspark import cloudpickle

    for module in modules:
        cloudpickle.register_pickle_by_value(module)


def _pick_warehouse(w) -> str:
    warehouses = list(w.warehouses.list())
    running = [wh for wh in warehouses if str(getattr(wh, "state", "")).endswith("RUNNING")]
    chosen = (running or warehouses)
    if not chosen:
        raise RuntimeError("No SQL warehouse available; pass warehouse_id=")
    return chosen[0].id


def _read_via_sdk(statement: str, *, warehouse_id: str | None, profile: str | None):
    import pandas as pd
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    wh = warehouse_id or _pick_warehouse(w)
    resp = w.statement_execution.execute_statement(statement=statement, warehouse_id=wh,
                                                   wait_timeout="50s")
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        detail = resp.status.error.message if resp.status.error else resp.status.state
        raise RuntimeError(f"SQL failed: {detail}")
    if resp.manifest is None or resp.manifest.schema is None:
        return pd.DataFrame()
    names = [c.name for c in resp.manifest.schema.columns]
    rows = list(resp.result.data_array or []) if resp.result else []
    chunk = resp.result.next_chunk_index if resp.result else None
    while chunk is not None:
        part = w.statement_execution.get_statement_result_chunk_n(resp.statement_id, chunk)
        rows.extend(part.data_array or [])
        chunk = part.next_chunk_index
    return pd.DataFrame(rows, columns=names)


def require_spark(purpose: str):
    """Return the active SparkSession or raise a clear error naming ``purpose``."""
    spark = get_spark()
    if spark is None:
        raise RuntimeError(
            f"{purpose} needs Python compute with Spark (serverless or a cluster). "
            "A SQL-only warehouse cannot run it.")
    return spark


def write_table(pdf, fqn: str, *, table_comment: str,
                column_comments: dict[str, str] | None = None, mode: str = "overwrite") -> str:
    """Write a pandas DataFrame to a UC table with table + column comments."""
    validate_identifier(fqn, fully_qualified=True)
    spark = require_spark("Writing results to Unity Catalog")
    sdf = spark.createDataFrame(pdf)
    (sdf.write.mode(mode).option("overwriteSchema", "true").saveAsTable(fqn))
    quoted = quote_identifier(fqn)
    spark.sql(f"COMMENT ON TABLE {quoted} IS {sql_string_literal(table_comment)}")
    for col, comment in (column_comments or {}).items():
        if col in pdf.columns:
            spark.sql(f"ALTER TABLE {quoted} ALTER COLUMN {quote_identifier(col)} "
                      f"COMMENT {sql_string_literal(comment)}")
    return fqn


def write_manifest(manifest: dict[str, Any], fqn: str) -> str:
    """Append one run manifest (JSON) row to ``fqn`` (created if absent)."""
    import pandas as pd

    row = pd.DataFrame([{"run_id": manifest["run_id"], "created_utc": manifest["created_utc"],
                         "skill": manifest["skill"], "manifest_json": json.dumps(manifest)}])
    return write_table(row, fqn, mode="append",
                       table_comment="Run manifests (inputs, decisions, versions) for skill runs")
