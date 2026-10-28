"""Render a grid-data-guard plan as Unity Catalog SQL (pure string building, no execution).

- ``internal_view_sql``: dynamic view; sensitive columns visible only to the privileged group
  (``is_account_group_member``), IDs tokenized with a secret-salted SHA-256
  (``secret(scope, key)``), precise points accompanied by a generalized cell.
- ``group_stats_sql``: per-cell customer counts / totals / max customer share for an
  aggregate release (the 15/15 check runs on the result).
- ``column_tag_sql``: ``energy_sensitivity`` tags on the *source* table's columns (opt-in) so
  governance tooling can find CEII / PII.

Identifiers are validated and back-quoted; constants are escaped. Note ``h3_longlatash3``
takes **longitude first**.
"""

from __future__ import annotations

import re

from _uc import quote_identifier, sql_string_literal, validate_identifier

GRAINS = {"month": "month", "day": "day", "hour": "hour"}


def _q(col: str) -> str:
    return quote_identifier(validate_identifier(col))


def _secret_parts(secret: str) -> tuple[str, str]:
    scope, key = secret.split("/", 1)
    if not re.match(r"^[\w.-]+$", scope) or not re.match(r"^[\w.-]+$", key):
        raise ValueError("tokenization_secret must be 'scope/key'")
    return scope, key


def _geo_expr(lat: str, lon: str, method: str, precision: float) -> str:
    if method == "h3":
        return f"h3_longlatash3({_q(lon)}, {_q(lat)}, {int(precision)})"
    d = int(precision)
    return f"concat(round({_q(lat)}, {d}), ',', round({_q(lon)}, {d}))"


def _internal_expr(col: str, action: str, group: str, secret: str | None) -> str:
    q = _q(col)
    member = f"is_account_group_member({sql_string_literal(group)})"
    if action == "tokenize":
        scope, key = _secret_parts(secret or "")
        token = (f"substr(sha2(concat(secret({sql_string_literal(scope)}, "
                 f"{sql_string_literal(key)}), CAST({q} AS STRING)), 256), 1, 16)")
        return f"CASE WHEN {member} THEN CAST({q} AS STRING) ELSE {token} END AS {q}"
    if action == "mask_privileged":
        return f"CASE WHEN {member} THEN {q} ELSE NULL END AS {q}"
    if action == "keep":
        return q
    raise ValueError(f"Action {action!r} is not valid for an internal view")


def internal_view_sql(source: str, output: str, plan: dict[str, dict], privileged_group: str,
                      secret: str | None, geo: tuple[str, str, str, float] | None = None) -> str:
    """``CREATE OR REPLACE VIEW`` with masking, tokenization, and an optional ``geo_cell``."""
    validate_identifier(source, fully_qualified=True)
    validate_identifier(output, fully_qualified=True)
    exprs = [_internal_expr(c, p["action"], privileged_group, secret) for c, p in plan.items()]
    if geo:
        lat, lon, method, precision = geo
        exprs.append(f"{_geo_expr(lat, lon, method, precision)} AS `geo_cell`")
    body = ",\n  ".join(exprs)
    return (f"CREATE OR REPLACE VIEW {quote_identifier(output)} AS\nSELECT\n  {body}\n"
            f"FROM {quote_identifier(source)}")


def group_stats_sql(source: str, group_cols: list[str], customer_col: str, value_col: str,
                    time_col: str | None, time_grain: str | None,
                    geo: tuple[str, str, str, float] | None = None) -> str:
    """Per-customer totals per cell, then cell counts, totals, and max customer value."""
    validate_identifier(source, fully_qualified=True)
    dims = [f"{_q(c)} AS {_q(c)}" for c in group_cols if c != "geo"]
    if "geo" in group_cols:
        if geo is None:
            raise ValueError("Grouping by 'geo' needs (lat_col, lon_col, method, precision).")
        dims.append(f"{_geo_expr(*geo)} AS `geo_cell`")
    if time_col:
        dims.append(f"date_trunc('{GRAINS[time_grain]}', {_q(time_col)}) AS `period`")
    aliases = [d.rsplit(" AS ", 1)[1] for d in dims]
    dim_sql = ", ".join(dims)
    keys = ", ".join(aliases)
    return (
        f"WITH per_customer AS (\n  SELECT {dim_sql}, {_q(customer_col)} AS `customer`, "
        f"sum({_q(value_col)}) AS `value`\n  FROM {quote_identifier(source)}\n  GROUP BY ALL\n)\n"
        f"SELECT {keys}, count(*) AS `n_customers`, sum(`value`) AS `total`, "
        f"max(`value`) AS `max_customer_value`\nFROM per_customer\nGROUP BY {keys}")


def column_tag_sql(table: str, plan: dict[str, dict]) -> list[str]:
    """``ALTER TABLE ... SET TAGS`` statements marking each sensitive column of ``table``."""
    validate_identifier(table, fully_qualified=True)
    sensitive = {c: p["class"] for c, p in plan.items()
                 if p["class"] in ("PII_DIRECT", "PII_ID", "GEO_PRECISE", "CEII_TOPOLOGY",
                                   "CEII_SETTINGS", "CONSUMPTION")}
    return [f"ALTER TABLE {quote_identifier(table)} ALTER COLUMN {_q(c)} SET TAGS "
            f"('energy_sensitivity' = {sql_string_literal(cls.lower())})"
            for c, cls in sensitive.items()]
