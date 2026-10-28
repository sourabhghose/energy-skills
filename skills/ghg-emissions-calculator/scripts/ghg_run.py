"""Databricks runner for the GHG calculator: read UC tables, call the core, write governed outputs.

    import sys; sys.path.append("<skill-dir>/scripts")
    from ghg_run import preview, build_confirmed
    print(preview("main.esg.activity_2025", production_table="main.esg.production_2025"))
    out = build_confirmed("main.esg.activity_2025", "main.esg.ghg_2025",
                          production_table="main.esg.production_2025",
                          gwp_set="AR5", factor_sets=["epa_hub_2025", "egrid_2023", "greene_rm_2025"],
                          consolidation="operational_control", flare_efficiency_tier="tier2_de95",
                          tank_method="measured_vent_volume", market_fallback="raise",
                          scope2_headline="market", cat11_basis="sold_volumes", boe_mcf_per_boe=6.0)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ghg_inventory import SKILL, VERSION, build_confirmed_inventory, preview_inventory  # noqa: E402
from uc_io import read_table, validate_identifier, write_manifest, write_table  # noqa: E402

COLUMN_COMMENTS = {
    "mass_t": "Mass of the gas in metric tonnes (before GWP and consolidation)",
    "co2e_t": "tCO2e = mass_t x gwp x consolidation_share",
    "factor_ids": "Emission factor ids used (see assets/emission_factors.csv)",
    "factor_sources": "Factor source and vintage",
    "scope2_method": "location | market (GHG Protocol Scope 2 dual reporting)",
    "ogmp_level": "OGMP 2.0 reporting level assigned from the method (CH4 only)",
}


def preview(activity_table: str, production_table: str | None = None,
            factor_sets: list[str] | None = None) -> str:
    """READ-ONLY. Returns the preview readout; writes nothing."""
    activity = read_table(activity_table)
    production = read_table(production_table) if production_table else None
    return preview_inventory(activity, production, factor_sets)["readout"]


def build_confirmed(activity_table: str, output_prefix: str, production_table: str | None = None,
                    **decisions) -> dict:
    """Build with explicit decisions and write <prefix>_inventory/_summary/_intensity/_manifest."""
    validate_identifier(output_prefix)
    activity = read_table(activity_table)
    production = read_table(production_table) if production_table else None
    result = build_confirmed_inventory(activity, production, **decisions)
    tag = f"{SKILL} {VERSION}"
    manifest = {**result["manifest"], "inputs": {**result["manifest"]["inputs"],
                                                 "activity_table": activity_table,
                                                 "production_table": production_table}}
    written = {
        "inventory": write_table(result["inventory"], f"{output_prefix}_inventory",
                                 f"GHG inventory records ({tag})", COLUMN_COMMENTS),
        "summary": write_table(result["summary"], f"{output_prefix}_summary", f"GHG totals ({tag})"),
        "manifest": write_manifest(manifest, f"{output_prefix}_manifest", SKILL, VERSION),
    }
    if not result["intensity"].empty:
        written["intensity"] = write_table(result["intensity"], f"{output_prefix}_intensity",
                                           f"GHG intensity metrics ({tag})")
    return {"tables": written, "summary": result["summary"], "manifest": manifest}
