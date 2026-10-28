"""Vetted entrypoints: preview the decisions, then build a confirmed GHG inventory.

    from ghg_inventory import preview_inventory, build_confirmed_inventory
    print(preview_inventory(activity_df, production_df)["readout"])      # READ-ONLY
    result = build_confirmed_inventory(activity_df, production_df, gwp_set="AR5", ...)

Activity input (long format, one row per source/period):
    facility_id, period, source_type, fuel_or_product, quantity, unit, plus source columns
    (ch4_mol_frac, device_count, operating_hours, egrid_subregion, rec_mwh, measured_ch4_kg,
    equity_share, operational_control, financial_control, ...). See references/input_schema.md.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ghg_core import DENSITY_KG_PER_SCF, GWP_SETS, DecisionRequired, available_factor_sets, gwp, load_factors, require
from ghg_sources import FLARE_TIERS, TANK_METHODS, compute_emissions

SKILL, VERSION = "ghg-emissions-calculator", "0.1.0"
CONSOLIDATION = ("operational_control", "financial_control", "equity_share")
MARKET_FALLBACK = ("raise", "location_fallback_flagged")
SCOPE2_HEADLINE = ("location", "market")
CAT11_BASIS = ("sold_volumes", "production_volumes")
BOE_MCF_PER_BOE = (6.0, 5.8)
CONSOLIDATION_COLUMN = {"operational_control": "operational_control",
                        "financial_control": "financial_control", "equity_share": "equity_share"}


def _has(activity: pd.DataFrame, source_type: str) -> bool:
    return bool((activity["source_type"] == source_type).any())


def validate_decisions(activity: pd.DataFrame, production: pd.DataFrame | None, **d) -> dict:
    """Every decision explicit; decisions for absent sources may be None ('not_applicable')."""
    elec = _has(activity, "purchased_electricity")
    out = {
        "gwp_set": require("gwp_set", d.get("gwp_set"), list(GWP_SETS)),
        "consolidation": require("consolidation", d.get("consolidation"), CONSOLIDATION),
        "flare_efficiency_tier": require("flare_efficiency_tier", d.get("flare_efficiency_tier"),
                                         list(FLARE_TIERS), _has(activity, "flare")),
        "tank_method": require("tank_method", d.get("tank_method"), TANK_METHODS, _has(activity, "tank_vent")),
        "market_fallback": require("market_fallback", d.get("market_fallback"), MARKET_FALLBACK, elec),
        "scope2_headline": require("scope2_headline", d.get("scope2_headline"), SCOPE2_HEADLINE, elec),
        "cat11_basis": require("cat11_basis", d.get("cat11_basis"), CAT11_BASIS, _has(activity, "sold_product")),
        "boe_mcf_per_boe": require("boe_mcf_per_boe", d.get("boe_mcf_per_boe"), BOE_MCF_PER_BOE,
                                   production is not None),
    }
    sets = d.get("factor_sets")
    if not sets:
        raise DecisionRequired("factor_sets", list(available_factor_sets()["factor_set"].unique()))
    out["factor_sets"] = sorted(sets)
    col = CONSOLIDATION_COLUMN[out["consolidation"]]
    if col not in activity.columns:
        raise ValueError(f"consolidation={out['consolidation']} needs column {col!r} in activity data")
    return out


def _facility_share(activity: pd.DataFrame, consolidation: str) -> pd.Series:
    col = CONSOLIDATION_COLUMN[consolidation]
    per_fac = activity.groupby("facility_id")[col].first()
    if consolidation == "equity_share":
        if ((per_fac < 0) | (per_fac > 1)).any():
            raise ValueError("equity_share must be a fraction in [0, 1]")
        return per_fac.astype(float)
    return per_fac.astype(bool).astype(float)


def apply_co2e(records: pd.DataFrame, activity: pd.DataFrame, d: dict) -> pd.DataFrame:
    share = _facility_share(activity, d["consolidation"])
    return records.assign(
        gwp=records["gas"].map(lambda g: gwp(g, d["gwp_set"])),
        consolidation_share=records["facility_id"].map(share).fillna(0.0),
    ).assign(co2e_t=lambda x: x["mass_t"] * x["gwp"] * x["consolidation_share"])


def summarize(inv: pd.DataFrame, headline: str) -> pd.DataFrame:
    """Totals by scope; Scope 2 is reported both ways, the headline uses the chosen method."""
    s1 = inv.loc[inv.scope == 1, "co2e_t"].sum()
    s2 = {m: inv.loc[(inv.scope == 2) & (inv.scope2_method == m), "co2e_t"].sum()
          for m in SCOPE2_HEADLINE}
    s3 = inv.loc[inv.scope == 3, "co2e_t"].sum()
    head = s2.get(headline, 0.0) if headline in SCOPE2_HEADLINE else 0.0
    rows = [("scope1", s1), ("scope2_location", s2["location"]), ("scope2_market", s2["market"]),
            ("scope3_cat11", s3), (f"scope1_plus_scope2_{headline}", s1 + head)]
    return pd.DataFrame(rows, columns=["metric", "tco2e"])


def ogmp_breakdown(inv: pd.DataFrame) -> pd.DataFrame:
    """Share of CH4 mass by OGMP 2.0 reporting level (screening assignment by method)."""
    ch4 = inv[inv.gas == "CH4"]
    if ch4.empty:
        return pd.DataFrame(columns=["ogmp_level", "ch4_t", "share"])
    grouped = ch4.groupby(ch4["ogmp_level"].fillna(0).astype(int))["mass_t"].sum().rename("ch4_t").reset_index()
    return grouped.assign(share=lambda x: x["ch4_t"] / x["ch4_t"].sum())


def intensity(inv: pd.DataFrame, production: pd.DataFrame | None, d: dict) -> pd.DataFrame:
    """Per-facility tCO2e/kboe (Scope 1 + headline Scope 2) and methane intensity (% of gas)."""
    if production is None:
        return pd.DataFrame()
    head = d["scope2_headline"]
    keep = (inv.scope == 1) | ((inv.scope == 2) & (inv.scope2_method == head))
    co2e = inv[keep].groupby("facility_id")["co2e_t"].sum()
    ch4_scf = inv[inv.gas == "CH4"].groupby("facility_id")["mass_t"].sum() * 1000 / DENSITY_KG_PER_SCF["CH4"]
    gas_basis = "gas_marketed_mcf" if "gas_marketed_mcf" in production.columns else "gas_mcf"
    p = production.set_index("facility_id")
    boe = p["oil_bbl"].fillna(0) + p["gas_mcf"].fillna(0) / d["boe_mcf_per_boe"]
    return pd.DataFrame({
        "kboe": boe / 1000,
        "tco2e_scope1_2": co2e.reindex(p.index).fillna(0.0),
        "ch4_scf": ch4_scf.reindex(p.index).fillna(0.0),
        "gas_basis_mcf": p[gas_basis],
    }).assign(
        tco2e_per_kboe=lambda x: x["tco2e_scope1_2"] / x["kboe"],
        methane_intensity_pct=lambda x: 100 * x["ch4_scf"] / (x["gas_basis_mcf"] * 1000),
        methane_intensity_basis=gas_basis,
    ).reset_index()


def build_manifest(activity: pd.DataFrame, production: pd.DataFrame | None, d: dict,
                   inv: pd.DataFrame) -> dict:
    return {
        "skill": SKILL, "skill_version": VERSION, "built_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {"activity_rows": len(activity), "production_rows": 0 if production is None else len(production),
                   "facilities": sorted(map(str, activity["facility_id"].unique()))},
        "decisions": d,
        "factors_used": sorted({fid for ids in inv["factor_ids"] for fid in ids.split(";") if fid}),
        "unverified_factors_used": sorted({fid for ids, st in zip(inv["factor_ids"], inv["factor_status"])
                                           if "verify_before_use" in st for fid in ids.split(";") if fid}),
        "methods_used": sorted(inv["method"].unique()),
    }


def build_confirmed_inventory(activity: pd.DataFrame, production: pd.DataFrame | None = None, *,
                              gwp_set=None, factor_sets=None, consolidation=None,
                              flare_efficiency_tier=None, tank_method=None, market_fallback=None,
                              scope2_headline=None, cat11_basis=None, boe_mcf_per_boe=None) -> dict:
    """Build the inventory. Every decision must be explicit (no defaults); raises on any row issue."""
    d = validate_decisions(activity, production, gwp_set=gwp_set, factor_sets=factor_sets,
                           consolidation=consolidation, flare_efficiency_tier=flare_efficiency_tier,
                           tank_method=tank_method, market_fallback=market_fallback,
                           scope2_headline=scope2_headline, cat11_basis=cat11_basis,
                           boe_mcf_per_boe=boe_mcf_per_boe)
    factors = load_factors(d["factor_sets"])
    records, issues = compute_emissions(activity, factors, d)
    if not issues.empty:
        raise ValueError(f"{len(issues)} activity row(s) could not be computed:\n{issues.to_string(index=False)}")
    inv = apply_co2e(records, activity, d)
    return {
        "inventory": inv,
        "summary": summarize(inv, d["scope2_headline"]),
        "by_facility_scope_gas": inv.groupby(["facility_id", "scope", "scope2_method", "gas"], dropna=False)
                                    ["co2e_t"].sum().reset_index(),
        "ogmp": ogmp_breakdown(inv),
        "intensity": intensity(inv, production, d),
        "manifest": build_manifest(activity, production, d, inv),
    }


# ----------------------------------------------------------------------------- preview

def _probe_decisions(activity: pd.DataFrame, factor_sets: list[str]) -> dict:
    cons = next((c for c in CONSOLIDATION if CONSOLIDATION_COLUMN[c] in activity.columns), None)
    return {"gwp_set": "AR5", "factor_sets": factor_sets, "consolidation": cons or "operational_control",
            "flare_efficiency_tier": "tier3_de92", "tank_method": "measured_vent_volume",
            "market_fallback": "location_fallback_flagged", "scope2_headline": "location",
            "cat11_basis": "sold_volumes", "boe_mcf_per_boe": 6.0}


def _consequences(activity: pd.DataFrame, records: pd.DataFrame, probe: dict) -> dict:
    gross = records[records["scope2_method"].fillna("") != "market"]  # avoid Scope 2 double count
    out: dict = {"gwp_set_gross_tco2e": {
        g: round(float((gross["mass_t"] * gross["gas"].map(GWP_SETS[g])).sum()), 3) for g in GWP_SETS}}
    flares = records[(records.source_type == "flare") & (records.gas == "CH4")]
    if not flares.empty:
        de_probe = FLARE_TIERS[probe["flare_efficiency_tier"]][0]
        unburned = flares["mass_t"].sum() / (1 - de_probe)
        out["flare_ch4_t_by_tier"] = {t: round(unburned * (1 - de), 4)
                                      for t, (de, _) in FLARE_TIERS.items() if de is not None}
    s2 = records[records.scope == 2].groupby("scope2_method")["mass_t"].sum()
    if not s2.empty:
        out["scope2_co2_t"] = {k: round(v, 3) for k, v in s2.items()}
    for c in CONSOLIDATION:
        if CONSOLIDATION_COLUMN[c] in activity.columns:
            inv = apply_co2e(records, activity, {**probe, "consolidation": c})
            out.setdefault("consolidation_total_tco2e", {})[c] = round(inv["co2e_t"].sum(), 3)
    return out


def preview_inventory(activity: pd.DataFrame, production: pd.DataFrame | None = None,
                      factor_sets: list[str] | None = None) -> dict:
    """READ-ONLY. Profiles the activity data and shows each decision's effect on THIS data."""
    sets_table = available_factor_sets()
    sets = factor_sets or sorted(sets_table["factor_set"].unique())
    probe = _probe_decisions(activity, sets)
    records, issues = compute_emissions(activity, load_factors(sets), probe)
    profile = activity.groupby(["source_type", "unit"]).size().rename("rows").reset_index()
    needed = [k for k, v in validate_decisions_applicability(activity, production).items() if v]
    consequences = _consequences(activity, records, probe) if not records.empty else {}
    readout = "\n".join([
        "## GHG inventory preview (nothing built)",
        f"Facilities: {activity['facility_id'].nunique()}  Activity rows: {len(activity)}",
        "### Activity profile", profile.to_string(index=False),
        "### Available factor sets (source, vintage)", sets_table.to_string(index=False),
        f"### Decisions you must make: {', '.join(needed)}",
        "### Effect of each option on this data", _fmt(consequences),
        f"### Rows that cannot be computed: {len(issues)}",
        issues.to_string(index=False) if not issues.empty else "(none)",
    ])
    return {"profile": profile, "issues": issues, "consequences": consequences,
            "decisions_needed": needed, "factor_sets": sets_table, "readout": readout}


def validate_decisions_applicability(activity: pd.DataFrame, production: pd.DataFrame | None) -> dict:
    elec = _has(activity, "purchased_electricity")
    return {"gwp_set": True, "factor_sets": True, "consolidation": True,
            "flare_efficiency_tier": _has(activity, "flare"), "tank_method": _has(activity, "tank_vent"),
            "market_fallback": elec, "scope2_headline": elec,
            "cat11_basis": _has(activity, "sold_product"), "boe_mcf_per_boe": production is not None}


def _fmt(consequences: dict) -> str:
    lines = []
    for key, values in consequences.items():
        lines.append(f"- {key}: " + ", ".join(f"{k}={v}" for k, v in values.items()))
    return "\n".join(lines) or "(no computable rows)"
