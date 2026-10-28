"""Databricks runner for ISO/RTO price data: optional fetch, read UC tables, call the core, write outputs.

    import sys; sys.path.append("<skill-dir>/scripts")
    from iso_run import preview_table, build_table
    print(preview_table("main.mkt.ercot_rt_spp", iso="ERCOT", market="RT", time_format="hour_ending",
                        nodes=["HB_NORTH"], repeated_col="dst_flag", interval_col="interval"))
    build_table("main.mkt.ercot_rt_spp", "main.mkt.ercot_rt_2025", iso="ERCOT", market="RT",
                time_format="hour_ending", repeated_col="dst_flag", interval_col="interval",
                nodes=["HB_NORTH"], hourly_aggregation="time_weighted", peak_definition="5x16",
                peak_timezone="America/Chicago", price_floor=-250, price_cap=5000)

Fetching (network; never used by tests): `fetch_with_gridstatus` wraps the open-source gridstatus
library (https://github.com/gridstatus/gridstatus), which handles each ISO's public endpoints. Land
the raw frame in a bronze UC table first, then run the skill on it. Endpoint notes:
references/data_sources.md.
"""

from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from iso_entry import SKILL, VERSION, build_confirmed_price_analysis, preview_market_data  # noqa: E402
from uc_io import read_table, validate_identifier, write_manifest, write_table  # noqa: E402

GRIDSTATUS_CLASSES = {"CAISO": "CAISO", "ERCOT": "Ercot", "PJM": "PJM", "MISO": "MISO", "NYISO": "NYISO",
                      "ISONE": "ISONE", "SPP": "SPP"}


def fetch_with_gridstatus(iso: str, market: str, start: str, end: str, locations: list[str] | None = None,
                          **kwargs) -> pd.DataFrame:
    """Fetch LMPs with gridstatus (pip install gridstatus). Returns the library's raw frame unchanged.

    gridstatus already returns `Interval Start` / `Interval End` columns; normalize with
    time_format="utc_column", ts_col="Interval Start", source_timestamp_convention="interval_beginning"
    after renaming `Location` -> node and `LMP` -> lmp. Some ISOs need API keys (PJM, ERCOT) via
    environment variables documented by gridstatus.
    """
    import gridstatus  # lazy: optional dependency

    if iso not in GRIDSTATUS_CLASSES:
        raise ValueError(f"Unsupported ISO {iso!r}; choose from {sorted(GRIDSTATUS_CLASSES)}")
    client = getattr(gridstatus, GRIDSTATUS_CLASSES[iso])()
    market_name = {"DA": "DAY_AHEAD_HOURLY", "RT": "REAL_TIME_5_MIN"}[market]
    return client.get_lmp(date=start, end=end, market=market_name, locations=locations, **kwargs)


def preview_table(table: str, *, where: str | None = None, args: dict | None = None, **kw) -> str:
    """READ-ONLY."""
    return preview_market_data(read_table(table, where, args), **kw)["readout"]


def build_table(table: str, output_prefix: str, *, where: str | None = None, args: dict | None = None,
                **kw) -> dict:
    """Run build_confirmed_price_analysis and write <prefix>_intervals/_hourly/_peak/_basis/_manifest."""
    validate_identifier(output_prefix)
    out = build_confirmed_price_analysis(read_table(table, where, args), **kw)
    tag = f"{SKILL} {VERSION}"
    write_table(out["prices"], f"{output_prefix}_intervals", f"Normalized interval prices ({tag})",
                {"interval_start_utc": "Interval start, UTC", "lmp": "$/MWh as published (see manifest)",
                 "component_mismatch": "LMP != sum of components under the ISO sign convention"})
    write_table(out["hourly"], f"{output_prefix}_hourly", f"Hourly prices ({tag})")
    write_table(out["peak"], f"{output_prefix}_peak", f"Peak-block statistics ({tag})")
    if not out["basis"].empty:
        write_table(out["basis"], f"{output_prefix}_basis", f"Node minus hub basis ({tag})")
    manifest = {**out["manifest"], "source_table": table, "where": where, "args": args}
    write_manifest(manifest, f"{output_prefix}_manifest", SKILL, VERSION)
    return {**out, "manifest": manifest}
