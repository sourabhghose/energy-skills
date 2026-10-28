"""Databricks runner: deploy generated SQL and smoke-test every metric view.

Purpose
    deploy_generated(out_dir)   executes 01_silver.sql then 03_metric_views.sql statement by
                                statement in the active Spark session (or via the SDK
                                statement API with warehouse_id), then runs one
                                SELECT MEASURE(...) per metric view as a smoke test.
    Deploying is an outward action: run only after the user approved plan.md.

Usage
    from semantic_run import deploy_generated
    report = deploy_generated("generated")            # in a notebook / Genie Code
    report = deploy_generated("generated", warehouse_id="<id>", profile="<p>")  # locally
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

LOG = logging.getLogger(__name__)
VIEW_RE = re.compile(r"CREATE OR REPLACE VIEW (`[^`]+`(?:\.`[^`]+`){0,2})\s+WITH METRICS")


def split_statements(sql: str) -> list[str]:
    """Split on ';' at line end, keeping $$ ... $$ YAML bodies intact."""
    statements, buf, in_body = [], [], False
    for line in sql.splitlines():
        if "$$" in line:
            in_body = not in_body
        buf.append(line)
        if not in_body and line.rstrip().endswith(";"):
            statements.append("\n".join(buf).rstrip().rstrip(";"))
            buf = []
    tail = "\n".join(buf).strip()
    return [s for s in statements + ([tail] if tail else []) if s.strip()]


def _executor(warehouse_id: str | None, profile: str | None):
    if warehouse_id is None:
        from pyspark.sql import SparkSession

        spark = SparkSession.getActiveSession()
        if spark is None:
            raise RuntimeError("No Spark session: pass warehouse_id to use a SQL warehouse.")
        return lambda s: spark.sql(s).collect()
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient(profile=profile)

    def run(statement: str):
        resp = w.statement_execution.execute_statement(
            statement=statement, warehouse_id=warehouse_id, wait_timeout="50s")
        if resp.status.error:
            raise RuntimeError(resp.status.error.message)
        return resp.result.data_array if resp.result else []
    return run


def deploy_generated(out_dir: str | Path, warehouse_id: str | None = None,
                     profile: str | None = None) -> dict:
    out = Path(out_dir)
    run = _executor(warehouse_id, profile)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    executed = 0
    for name in ("01_silver.sql", "03_metric_views.sql"):
        for statement in split_statements((out / name).read_text(encoding="utf-8")):
            run(statement)
            executed += 1
    smoke = {}
    mv_sql = (out / "03_metric_views.sql").read_text(encoding="utf-8")
    for view in VIEW_RE.findall(mv_sql):
        short = view.split(".")[-1].strip("`")
        first = manifest["metric_views"][short][0]
        try:
            smoke[short] = run(f"SELECT MEASURE(`{first}`) FROM {view}")
        except Exception as exc:  # report every failing view, do not stop at the first
            LOG.error("smoke test failed for %s: %s", view, exc)
            smoke[short] = f"ERROR: {exc}"
    return {"statements_executed": executed, "smoke_tests": smoke}
