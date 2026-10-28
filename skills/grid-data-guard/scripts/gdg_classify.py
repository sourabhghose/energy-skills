"""Column classification for grid data: CEII, customer PII, meter consumption, geo. Pure pandas.

Classifies each column from its name and a value sample into one sensitivity class:

| Class | Examples | Default handling |
|-------|----------|------------------|
| PII_DIRECT | customer name, service address, email, phone | drop / privileged mask |
| PII_ID | account number, customer id, premise id, meter id | salted tokenization |
| GEO_PRECISE | latitude / longitude / WKT point | generalize (H3 / rounding) |
| CEII_TOPOLOGY | substation, feeder, circuit, transformer, bus ids | privileged mask; no public grouping |
| CEII_SETTINGS | relay / protection settings, SCADA points, IP addresses | drop outside privileged access |
| CONSUMPTION | kWh, kW, usage, demand | aggregate (15/15) outside privileged access |
| QUASI | ZIP, rate class, tariff, premise type, city | kept; counts toward group checks |
| TIME / OTHER | timestamps / everything else | kept |

    from gdg_classify import classify_columns
    classes = classify_columns(df)            # {column: {"class": ..., "evidence": ...}}
"""

from __future__ import annotations

import re

import pandas as pd

NAME_RULES: list[tuple[str, str]] = [
    ("CEII_SETTINGS", r"relay|protect|pickup|trip|tcc|ct_ratio|pt_ratio|setting|scada|"
                      r"dnp|modbus|ip_?addr|rtu|plc|firmware"),
    ("CEII_TOPOLOGY", r"substation|sub_id|feeder|circuit|transformer|xfmr|bus_?id|"
                      r"breaker|switch_?id|line_?segment|phase_?conn"),
    ("PII_DIRECT", r"(cust|customer|account_?holder|owner)_?name|^name$|first_?name|last_?name|"
                   r"address|street|addr_?line|email|phone|mobile"),
    ("PII_ID", r"account_?(id|no|num|number)?$|acct_?(id|no|num)?$|customer_?id|cust_?id|"
               r"premise_?(id|no|num)$|^premise$|service_?point|^sdp|meter_?(id|no|num)|^meter$|"
               r"esi_?id|mprn|mpan|badge"),
    ("GEO_PRECISE", r"^lat$|latitude|^lon$|^lng$|longitude|geom|wkt|coord|location|^point$"),
    ("CONSUMPTION", r"kwh|kw$|_kw_|kvarh|usage|consumption|demand|load_?(kw|mw)|energy"),
    ("QUASI", r"zip|postal|post_?code|rate_?class|tariff|rate_?code|premise_?type|city|county|"
              r"census|tract|segment|naics|sic"),
    ("TIME", r"time|date|_ts$|^ts$|interval|period|month|year"),
]

VALUE_RULES: list[tuple[str, re.Pattern]] = [
    ("PII_DIRECT", re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")),
    # Phone numbers need separators: a bare 10-digit string is more often an account number.
    ("PII_DIRECT", re.compile(r"^(\+?1[\s.-]?)?(\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}$")),
    ("PII_DIRECT", re.compile(r"^\d{1,6}\s+\w+(\s\w+)*\s(st|street|ave|avenue|rd|road|blvd|dr|"
                              r"drive|ln|lane|ct|court|way|hwy|pkwy)\b", re.I)),
    ("CEII_SETTINGS", re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")),
    ("GEO_PRECISE", re.compile(r"^POINT\s*\(", re.I)),
]

ORDER = ["CEII_SETTINGS", "CEII_TOPOLOGY", "PII_DIRECT", "PII_ID", "GEO_PRECISE", "CONSUMPTION",
         "QUASI", "TIME", "OTHER"]


def _by_name(col: str) -> str | None:
    lowered = col.lower()
    for cls, pattern in NAME_RULES:
        if re.search(pattern, lowered):
            return cls
    return None


def _by_value(series: pd.Series) -> str | None:
    sample = series.dropna().astype(str).head(200)
    if sample.empty:
        return None
    for cls, pattern in VALUE_RULES:
        if sample.map(lambda v: bool(pattern.match(v.strip()))).mean() >= 0.8:
            return cls
    return None


def _looks_like_coordinate(series: pd.Series, col: str) -> bool:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty or values.round(0).eq(values).mean() > 0.5:
        return False
    limit = 90 if "lat" in col.lower() else 180
    decimals = values.astype(str).str.split(".").str[-1].str.len().median()
    return bool(values.abs().le(limit).all() and decimals >= 4)


def classify_column(name: str, series: pd.Series) -> dict:
    """Return ``{"class", "evidence"}`` for one column (value evidence wins over a weak name)."""
    by_value = _by_value(series)
    by_name = _by_name(name)
    if by_value and (by_name is None or ORDER.index(by_value) < ORDER.index(by_name)):
        return {"class": by_value, "evidence": "values"}
    if by_name == "GEO_PRECISE" and not _looks_like_coordinate(series, name) \
            and _by_value(series) != "GEO_PRECISE":
        return {"class": "QUASI", "evidence": "name looks geographic but values are coarse"}
    if by_name:
        return {"class": by_name, "evidence": "name"}
    return {"class": "OTHER", "evidence": "no rule matched"}


def classify_columns(df: pd.DataFrame) -> dict[str, dict]:
    """Classify every column of a (sample) frame."""
    return {col: classify_column(col, df[col]) for col in df.columns}


def apply_overrides(classes: dict[str, dict], overrides: dict[str, str] | None) -> dict[str, dict]:
    """Return a new mapping with user overrides (``{column: CLASS}``) applied."""
    if not overrides:
        return dict(classes)
    unknown = {c for c in overrides.values() if c not in ORDER}
    if unknown:
        raise ValueError(f"Unknown classes in overrides: {sorted(unknown)}; use {ORDER}")
    return {**classes, **{col: {"class": cls, "evidence": "user override"}
                          for col, cls in overrides.items()}}
