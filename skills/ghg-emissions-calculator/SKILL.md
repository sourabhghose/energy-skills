---
name: ghg-emissions-calculator
description: >-
  GHG emissions inventory (Scope 1, Scope 2 location- and market-based, Scope 3 category 11) for oil &
  gas, utilities and industrials on Unity Catalog activity data. Computes combustion, flaring, venting,
  pneumatics, tanks and measured methane with EPA Emission Factors Hub, eGRID, Green-e residual mix and
  screening-level Subpart W methods; tags methane by OGMP 2.0 level; reports tCO2e by scope, category,
  gas and facility with full factor lineage (source + vintage) and intensity (tCO2e/kboe, methane
  intensity). SURFACES the analyst's decisions (GWP set AR4/AR5/AR6, factor vintage, consolidation
  approach, flare efficiency tier, tank method, market-based fallback, Scope 2 headline, boe conversion)
  with their effect on the data before building. Run by calling scripts/ghg_inventory.py or
  scripts/ghg_run.py; do not hand-write emission math. For unit conversion questions use unit-guard;
  for KPI metric views use energy-semantic-builder.
category: "Emissions & ESG"
summary: Scope 1, 2 (dual) and 3 cat 11 inventory with versioned factors, Subpart W screening, OGMP 2.0 levels, and full factor lineage.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# GHG Emissions Calculator

## Overview

Turns facility activity data (fuel use, flare volumes, device counts, vent measurements, purchased
electricity, sold products) into a **defensible, reproducible GHG inventory**: tCO2e by scope,
category, gas and facility, with every number traceable to an emission factor id, its source and
vintage. Scope 2 is always reported both location-based and market-based. Methane records carry an
OGMP 2.0 reporting level. Outputs are Unity Catalog tables plus a run manifest.

General coding agents get these inventories wrong in predictable ways: they pick a GWP set silently,
use a 98% flare efficiency that the 2024 Subpart W revision retired, report only one Scope 2 number,
mix gross and equity-share boundaries, or use a factor with no vintage. This skill makes those
choices explicit and refuses to compute without them.

## When to Use

- "Calculate our 2025 Scope 1 and 2 emissions from this fuel and electricity table."
- "What are our flaring and venting methane emissions, and how do they change under the new Subpart W
  flare tiers?"
- "Report Scope 2 location-based and market-based with our REC purchases."
- "Estimate Scope 3 category 11 (use of sold products) from our sales volumes."
- "What share of our methane inventory is OGMP 2.0 Level 4/5?"
- "Give me methane intensity and tCO2e per boe by asset."
- "Restate the 2022 baseline under AR5 GWPs."
- "Compare operational-control vs equity-share totals for our JV portfolio."

## Prerequisites

- **Compute**: Python-enabled compute (serverless or a cluster); the runner uses Spark to read/write UC.
- **Inputs**: an activity table in the long format of `references/input_schema.md`; optional
  production table (`facility_id`, `oil_bbl`, `gas_mcf`, `gas_marketed_mcf`) for intensity.
- **Factors**: `assets/emission_factors.csv` (versioned sets). Add your own sets rather than editing.
- **Permissions**: `SELECT` on inputs; `CREATE TABLE` on the output schema.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from ghg_run import preview, build_confirmed

# STEP 1 — READ-ONLY. Profiles the data and shows each decision's effect. Show it to the user.
print(preview("main.esg.activity_2025", production_table="main.esg.production_2025"))

# STEP 2 — only after the user chooses every decision.
out = build_confirmed(
    "main.esg.activity_2025", "main.esg.ghg_2025", production_table="main.esg.production_2025",
    gwp_set="AR5", factor_sets=["epa_hub_2025", "egrid_2023", "greene_rm_2025", "subpart_w_legacy"],
    consolidation="operational_control", flare_efficiency_tier="tier2_de95",
    tank_method="measured_vent_volume", market_fallback="raise", scope2_headline="market",
    cat11_basis="sold_volumes", boe_mcf_per_boe=6.0)
print(out["summary"])
```

Pandas-only (no UC): `from ghg_inventory import preview_inventory, build_confirmed_inventory`.

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write the emission calculation, and do not pick a decision-point value yourself.
`preview` / `preview_inventory` is READ-ONLY; `build_confirmed` / `build_confirmed_inventory`
requires every applicable decision and raises `DecisionRequired` otherwise.

### Step 1: Map the source data to the activity schema

Map the customer's tables to `references/input_schema.md` (one row per source and period). Ground
`facility_id`, `egrid_subregion` and fuel keys in what the data and factor table contain. Do not
invent facilities or subregions; ask when a mapping is unclear.

```sql
-- Example mapping view; columns are the customer's, the AS names are the schema's
CREATE OR REPLACE TEMP VIEW activity AS
SELECT site_code AS facility_id, '2025' AS period, 'stationary_combustion' AS source_type,
       'natural_gas' AS fuel_or_product, fuel_gas_mcf AS quantity, 'Mcf' AS unit,
       is_operated AS operational_control, wi_pct / 100 AS equity_share
FROM ops.fuel_gas_monthly WHERE year = 2025
```

### Step 2: Preview (read-only)

```python
print(preview("main.esg.activity_2025"))
```

The readout lists: activity profile by source type and unit, available factor sets with vintages,
the decisions that apply to this data, the **effect of each option** (total tCO2e under AR4/AR5/AR6,
flare CH4 under each tier, Scope 2 location vs market, totals by consolidation approach), and every
row that cannot be computed (ambiguous unit, missing composition, factor without source).

### Step 3: Resolve row issues

Rows with issues are never silently dropped; `build_confirmed` refuses to run while any remain. Fix
the mapping (e.g. convert `m3` with stated reference conditions, add `ef_source`) and preview again.

### Step 4: Ask the user for each decision

Present the Decision Points table with the preview's numbers. Record the user's answers verbatim.

### Step 5: Build confirmed

```python
out = build_confirmed("main.esg.activity_2025", "main.esg.ghg_2025", **user_decisions)
```

Writes `<prefix>_inventory` (record level, with lineage), `<prefix>_summary`, `<prefix>_intensity`
(when production given) and appends a row to `<prefix>_manifest`.

### Step 6: Report

Report the summary table, Scope 2 both ways, OGMP level shares, intensity, and the manifest's
`unverified_factors_used` list. Any factor still `verify_before_use` must be called out before the
numbers are disclosed externally.

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `gwp_set` | `AR4`, `AR5`, `AR6` | IPCC; EPA Table A-1 (AR5 from 2025) | CH4 ×25 / ×28 / ×29.8; N2O ×298 / ×265 / ×273 |
| `factor_sets` | sets in `assets/emission_factors.csv` | EPA Hub, eGRID, Green-e, Subpart W | Factor values and vintages |
| `consolidation` | `operational_control`, `financial_control`, `equity_share` | GHG Protocol Corporate Standard ch. 3 | Which facilities count, at what share |
| `flare_efficiency_tier` | `tier1_de98`, `tier2_de95`, `tier3_de92`, `legacy_ce98`, `measured` | Subpart W 2024 revision | Flare CH4 slip 2%–8% (up to 4×) |
| `tank_method` | `measured_vent_volume`, `flash_factor` | Subpart W tanks | Tank vent volume basis; OGMP level |
| `market_fallback` | `raise`, `location_fallback_flagged` | GHG Protocol Scope 2 Guidance | Behaviour when no residual mix exists |
| `scope2_headline` | `location`, `market` | Scope 2 Guidance (both always reported) | Which Scope 2 enters the Scope 1+2 headline |
| `cat11_basis` | `sold_volumes`, `production_volumes` | Scope 3 Technical Guidance cat 11 | Volume basis recorded; double-count risk |
| `boe_mcf_per_boe` | `6.0`, `5.8` | Energy-equivalence convention | kboe denominator of intensity |

Decisions for sources absent from the data may be `None` and are recorded as `not_applicable`.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `factor_sets` (preview) | all sets | list of set names | Preview may use all; build requires an explicit list |
| `production_table` | `None` | UC table | Enables intensity metrics |
| `output_prefix` | required | `catalog.schema.name` | Output table names |

## Expected Outputs

- `<prefix>_inventory`: `facility_id, period, scope, category, source_type, gas, mass_t, gwp,
  consolidation_share, co2e_t, method, factor_ids, factor_sources, factor_status, ogmp_level,
  scope2_method, note`
- `<prefix>_summary`: `scope1`, `scope2_location`, `scope2_market`, `scope3_cat11`,
  `scope1_plus_scope2_<headline>` in tCO2e
- `<prefix>_intensity`: `kboe, tco2e_scope1_2, tco2e_per_kboe, ch4_scf, methane_intensity_pct,
  methane_intensity_basis`
- `ogmp` (returned): CH4 tonnes and share by OGMP level
- `<prefix>_manifest`: inputs, decisions, factors used, unverified factors, methods, skill version

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `DecisionRequired: 'gwp_set'` | Decision not passed | Ask the user; never default it |
| `Ambiguous unit 'm3'` | Reference conditions unknown | Convert to scf at 60 degF/14.7 psia, stating the source conditions |
| `No factor for purchased_electricity_residual/...` | No residual mix for subregion | Choose `market_fallback`, or add a residual-mix set |
| `Ambiguous factor ...` | Two chosen sets cover the same key | Choose one set for that source type |
| `ef_scf_per_hour + ef_source` error | Component factor without provenance | Add the factor's source (e.g. Subpart W Table W-1A) |
| Equity-share total > operated total | JV interests in non-operated assets | Expected; report the boundary used |
| Methane intensity looks 10× high | Denominator is gross gas, or units in Mcf vs scf | Provide `gas_marketed_mcf`; check basis column |

## Guardrails

1. Never choose a decision-point value on the user's behalf; present the preview and ask.
2. Never use an emission factor without a recorded source and vintage; add a factor set instead.
3. Always report Scope 2 location-based **and** market-based.
4. Call out every `verify_before_use` factor listed in the manifest before external disclosure.
5. Subpart W methods here are screening level: do not present results as a GHGRP filing.
6. Do not add biogenic CO2 to Scope 1 totals; report it separately if present.
7. Ask before building over very large activity tables (>10M rows); aggregate to monthly first.

## Related Skills

- `unit-guard`: unit and heat-content conversions with explicit assumptions
- `energy-semantic-builder`: publish emissions KPIs (intensity, methane intensity) as metric views
- `equipment-pdm`, `drilling-report-npt`: source activity data (flaring events, downtime) from operations
- `energy-report-writer`: turn the inventory and manifest into a disclosure-ready methods section
- `grid-data-guard`: mask facility identifiers before sharing outside the company

## References

- [GHG Protocol Corporate Standard](https://ghgprotocol.org/corporate-standard)
- [GHG Protocol Scope 2 Guidance](https://ghgprotocol.org/scope-2-guidance)
- [GHG Protocol Scope 3 Standard](https://ghgprotocol.org/corporate-value-chain-scope-3-standard)
- [EPA GHG Emission Factors Hub](https://www.epa.gov/climateleadership/ghg-emission-factors-hub)
- [EPA eGRID](https://www.epa.gov/egrid)
- [Green-e Residual Mix](https://resource-solutions.org/2025-residual-mix/)
- [40 CFR 98 Subpart W](https://www.ecfr.gov/current/title-40/chapter-I/subchapter-C/part-98/subpart-W)
- [EPA 2024 Subpart W final rule](https://www.epa.gov/system/files/documents/2024-05/subpart-w-final-preamble-rule-2024.pdf)
- [EPA GWP update to Table A-1](https://www.epa.gov/system/files/documents/2024-07/gwp_update_2024.pdf)
- [OGMP 2.0](https://ogmpartnership.org/)
- [IPCC AR6 WG1 Chapter 7](https://www.ipcc.ch/report/ar6/wg1/chapter/chapter-7/)
- `references/` in this skill: `input_schema.md`, `ghg_protocol_scopes.md`, `subpart_w_screening.md`,
  `ogmp2_levels.md`, `factor_sources.md`
