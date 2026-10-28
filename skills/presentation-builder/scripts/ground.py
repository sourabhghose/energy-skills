# Adapted from databricks-industry-solutions/vital-skills (skills/presentation-builder/scripts/ground.py); modified for the energy industry.
"""Grounding for deck content — pull REAL figures, with units, from Unity Catalog artifacts.

A deck is only trustworthy if every number on it came from the data. These helpers are the
bridge between an upstream energy artifact (a reliability index table, a decline-curve
forecast, an emissions inventory, an interval-data roll-up, any UC table or view) and the deck
spec. The agent calls them, drops the returned figures into `metrics` / `bar_chart` slides,
and cites the returned `source`; it never types a number by hand.

Guarantees:
  - GROUNDED: counts, distributions, totals, and summaries come from live SQL over the artifact,
    each returned with the `source` string to print as the slide caption.
  - UNITS: every numeric helper requires the unit and returns a pre-formatted display string
    that carries it ("132 min", "1,240 MWh"). There is no unit inference.
  - SAFE SQL: table and column names are validated identifiers; filter values are passed as
    statement parameters, never spliced into SQL.
  - NO SILENT DISCLOSURE: `column_distribution(..., suppress_below=k)` folds groups smaller
    than k into one "(suppressed)" bar. Customer-level and CEII handling is delegated to the
    grid-data-guard skill (see SKILL.md).

Usage:
    import ground
    head = ground.dataset_summary("main.grid.outages_2025", id_col="outage_id")
    saidi = ground.numeric_summary("main.rel.saidi_daily", "saidi_min", unit="min")
    tiles = ground.tiles_from_facts("/Volumes/main/rel/reports/facts.json", ["y2025_saidi"])
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --- SQL runner (Databricks SDK statement execution) --------------------------

class Q:
    """Run SQL on a warehouse: ambient auth in-workspace, optional `profile=` locally."""

    def __init__(self, catalog=None, schema=None, profile=None, warehouse_id=None):
        from databricks.sdk import WorkspaceClient
        self.w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
        self.wid = warehouse_id or next(wh.id for wh in self.w.warehouses.list())
        self.catalog, self.schema = catalog, schema

    def __call__(self, stmt: str, params: dict | None = None) -> list:
        import time
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState
        r = self.w.statement_execution.execute_statement(
            warehouse_id=self.wid, catalog=self.catalog, schema=self.schema, statement=stmt,
            parameters=[StatementParameterListItem(name=k, value=str(v))
                        for k, v in (params or {}).items()],
            wait_timeout="50s")
        while r.status and r.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(2)
            r = self.w.statement_execution.get_statement(r.statement_id)
        if r.status and r.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{r.status.error} :: {stmt[:200]}")
        return r.result.data_array if r.result else []


# --- identifiers and formatting ------------------------------------------------

def quote_table(table: str) -> str:
    """Validate catalog.schema.table and back-quote each part."""
    parts = str(table).split(".")
    if len(parts) != 3 or not all(IDENT.match(p) for p in parts):
        raise ValueError(f"Expected a fully-qualified catalog.schema.table, got: {table!r}")
    return ".".join(f"`{p}`" for p in parts)


def quote_column(column: str) -> str:
    if not IDENT.match(str(column)):
        raise ValueError(f"Invalid column name: {column!r}")
    return f"`{column}`"


def _require_unit(unit: str) -> str:
    unit = str(unit or "").strip()
    if not unit:
        raise ValueError("unit is required (e.g. 'MWh', 'min', 'bbl/d', 'tCO2e'; '-' for counts)")
    return unit


def format_value(value, unit: str, decimals: int | None = None) -> str:
    """'1,240 MWh' style display string. 0 decimals at >= 100, 1 at >= 10, else 2."""
    if value is None:
        return "n/a"
    number = float(value)
    if decimals is None:
        decimals = 0 if abs(number) >= 100 or number.is_integer() else (1 if abs(number) >= 10 else 2)
    text = f"{number:,.{decimals}f}"
    return text if unit == "-" else f"{text} {unit}"


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if not math.isfinite(f):
        return None
    return int(f) if f == int(f) else round(f, 4)


# --- grounded reads -------------------------------------------------------------

def profile_table(table, profile=None, warehouse_id=None, q=None) -> dict:
    """Row count + column schema. Returns {table, row_count, columns:[{name,type}]}."""
    fq = quote_table(table)
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    cols = []
    for r in q(f"DESCRIBE {fq}"):
        name = (r[0] or "").strip()
        if not name or name.startswith("#"):
            break
        cols = [*cols, {"name": name, "type": (r[1] or "").strip() if len(r) > 1 else ""}]
    n = q(f"SELECT COUNT(*) FROM {fq}")
    return {"table": table, "row_count": int(n[0][0]) if n and n[0] else 0, "columns": cols}


def dataset_summary(table, id_col=None, profile=None, warehouse_id=None, q=None) -> dict:
    """Headline: N rows and N distinct entities (meters, wells, assets, outages).

    Returns {n_rows, n_entities, id_col, source}. `n_entities` is None when no id_col is given.
    """
    fq = quote_table(table)
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    distinct = f"COUNT(DISTINCT {quote_column(id_col)})" if id_col else "NULL"
    r = q(f"SELECT COUNT(*), {distinct} FROM {fq}")[0]
    return {"n_rows": int(r[0]), "n_entities": None if r[1] is None else int(r[1]),
            "id_col": id_col, "source": f"Source: {table}"}


def time_range(table, ts_col, profile=None, warehouse_id=None, q=None) -> dict:
    """First and last timestamp in a column, as returned by the warehouse (state the timezone)."""
    fq, col = quote_table(table), quote_column(ts_col)
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    r = q(f"SELECT CAST(MIN({col}) AS STRING), CAST(MAX({col}) AS STRING) FROM {fq}")[0]
    return {"start": r[0], "end": r[1], "source": f"Source: {table}.{ts_col}"}


def numeric_summary(table, column, unit, profile=None, warehouse_id=None, q=None) -> dict:
    """count / min / max / avg / median for a numeric column, with unit and display strings."""
    unit = _require_unit(unit)
    fq, col = quote_table(table), quote_column(column)
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    r = q(f"SELECT COUNT({col}), MIN({col}), MAX({col}), AVG({col}), "
          f"percentile_approx({col}, 0.5) FROM {fq}")[0]
    stats = {"min": _num(r[1]), "max": _num(r[2]), "avg": _num(r[3]), "median": _num(r[4])}
    return {"count": int(r[0]) if r[0] is not None else 0, **stats, "unit": unit,
            "display": {k: format_value(v, unit) for k, v in stats.items()},
            "source": f"Source: {table}.{column} ({unit})"}


def filtered_total(table, value_col, unit, where=None, profile=None, warehouse_id=None,
                   q=None) -> dict:
    """SUM(value_col) with optional equality filters {column: value} passed as parameters."""
    unit = _require_unit(unit)
    fq, col = quote_table(table), quote_column(value_col)
    where = where or {}
    clauses = [f"{quote_column(k)} = :p{i}" for i, k in enumerate(where)]
    params = {f"p{i}": v for i, v in enumerate(where.values())}
    sql = f"SELECT SUM({col}), COUNT(*) FROM {fq}" + (f" WHERE {' AND '.join(clauses)}" if clauses else "")
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    r = q(sql, params)[0]
    filt = ", ".join(f"{k}={v}" for k, v in where.items())
    return {"total": _num(r[0]), "n_rows": int(r[1]), "unit": unit,
            "display": format_value(_num(r[0]), unit),
            "source": f"Source: {table} · SUM({value_col})" + (f" WHERE {filt}" if filt else "")}


def column_distribution(table, column, profile=None, warehouse_id=None, q=None, top=8,
                        suppress_below=None, value_col=None, unit="-") -> dict:
    """Top-N groups as bar_chart `bars`: COUNT(*) by default, or SUM(value_col) with a unit.

    `suppress_below=k` folds groups with fewer than k rows into one "(suppressed)" bar so small
    groups (a handful of customers on a feeder) are not disclosed.
    """
    fq, col = quote_table(table), quote_column(column)
    measure = f"SUM({quote_column(value_col)})" if value_col else "COUNT(*)"
    unit = _require_unit(unit) if value_col else "-"
    q = q or Q(profile=profile, warehouse_id=warehouse_id)
    rows = q(f"SELECT CAST({col} AS STRING) AS v, {measure} AS m, COUNT(*) AS n FROM {fq} "
             f"GROUP BY 1 ORDER BY m DESC LIMIT {int(top)}")
    kept = [r for r in rows if suppress_below is None or int(r[2]) >= int(suppress_below)]
    dropped = [r for r in rows if r not in kept]
    bars = [{"label": "(null)" if r[0] is None else r[0], "value": _num(r[1])} for r in kept]
    if dropped:
        bars = [*bars, {"label": "(suppressed)", "value": _num(sum(float(r[1]) for r in dropped))}]
    basis = f"SUM({value_col}) ({unit})" if value_col else "COUNT(*)"
    note = f" · groups < {suppress_below} rows suppressed" if suppress_below else ""
    return {"bars": bars, "unit": unit,
            "source": f"Source: {table} · {basis} GROUP BY {column}{note}"}


# --- facts ledger bridge (energy-report-writer facts.json) -----------------------

def tiles_from_facts(path_or_records, fact_ids, labels=None) -> list[dict]:
    """`metrics` tiles from a facts ledger (JSON array of {fact_id, value, unit, source}).

    Shares the format written by energy-report-writer's save_ledger(), so a report and its deck
    show identical figures. Raises KeyError on an unknown fact id.
    """
    records = path_or_records
    if isinstance(path_or_records, (str, Path)):
        records = json.loads(Path(path_or_records).read_text(encoding="utf-8"))
    by_id = {r["fact_id"]: r for r in records}
    missing = [f for f in fact_ids if f not in by_id]
    if missing:
        raise KeyError(f"facts not in ledger: {missing}")
    labels = labels or {}
    return [{"value": format_value(by_id[f]["value"], _require_unit(by_id[f]["unit"]),
                                   by_id[f].get("decimals")),
             "label": labels.get(f, f.replace("_", " ")),
             "caption": f"Source: {by_id[f]['source']}"} for f in fact_ids]
