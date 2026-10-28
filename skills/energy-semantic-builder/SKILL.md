---
name: energy-semantic-builder
description: >-
  Energy KPI semantic layer as Unity Catalog metric views: a canonical, source-agnostic
  measure catalog (73 measures) across upstream oil & gas (boe/d, LOE $/boe, GOR, water cut,
  uptime), generation (net capacity factor, net heat rate Btu/kWh, NERC GADS EAF / EFOR /
  FOR), T&D (line losses, IEEE 1366 SAIDI/SAIFI/CAIDI with and without MED), renewables
  (IEC 61724 performance ratio, availability, specific yield), emissions intensity
  (kgCO2e/MWh, kgCO2e/boe), and retail billing (cents/kWh). Profiles a customer schema,
  drafts a source mapping, and generates conforming views plus CREATE VIEW ... WITH METRICS
  YAML where every rate is a ratio of measures. Surfaces decisions that change the numbers
  (Mcf per boe, GADS unweighted vs. MW-weighted pooling, capacity basis, HHV/LHV) before
  generating. Run scripts/generate_semantic_layer.py; do not hand-write metric view SQL.
  To compute IEEE 1366 indices from outage records use reliability-metrics; for emissions
  inventories use ghg-emissions-calculator.
category: Others
summary: Governed energy KPI layer (73 measures, 6 domains) generated as Unity Catalog metric views from a per-customer mapping.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Energy Semantic Builder

## Overview

A governed semantic layer for energy companies in two parts over one canonical model:
(1) a **measure catalog** of correct, unit-labelled KPI definitions that never change per
customer; and (2) a **build workflow** that profiles a customer's sources, maps them to the
canonical model, and generates Unity Catalog metric views for Genie, AI/BI dashboards, BI
tools, and agents. The only customer-specific input is a mapping file, plus the decisions
that legitimately differ between companies (boe conversion, GADS pooling, capacity and
heating-value basis).

Every rate (boe/d, water cut, capacity factor, heat rate, EAF, SAIDI, PR, ¢/kWh) is a
**composite** `MEASURE(a) / MEASURE(b)`, so it stays correct at any roll-up. Averaging
per-well or per-unit ratios is the most common energy dashboard error.

## When to Use

- "Stand up governed metric views for our production, generation, and reliability KPIs."
- "What is the correct definition of EFOR / net heat rate / water cut, and is it additive?"
- "Map our production accounting tables to a semantic layer for Genie."
- "Our dashboards disagree on boe/d — build one definition everyone uses."
- "Give us fleet EAF both unweighted and MW-weighted like NERC GADS does."
- "Turn the reliability-metrics daily fact into a SAIDI metric view by region."
- "Draft a mapping from our raw schema and show what's missing."

## Prerequisites

- **Tools**: Python 3.10+ with PyYAML; Databricks SDK for profiling / deployment.
- **Inputs**: read access to the source `catalog.schema`; a target `catalog.schema`; a SQL
  warehouse (profiling via SDK) or a Spark session (deployment in a notebook).
- **Runtime**: metric view YAML v1.1 needs Databricks Runtime 17.2+ / a current SQL warehouse.
- **Working directory**: customer mappings and generated SQL live there, never in this skill.

## Quick Start

```bash
# 1. Draft a mapping (or copy an adapter from references/adapters/)
python3 scripts/profile_source.py --catalog <c> --schema <src> --warehouse-id <id> \
    --target-catalog <c> --target-schema energy_semantic
# 2. READ-ONLY preview: scope + decisions needed
python3 scripts/generate_semantic_layer.py --mapping <src>_mapping.yaml --preview
# 3. Generate ONLY after the user confirms each decision
python3 scripts/generate_semantic_layer.py --mapping <src>_mapping.yaml --out generated \
    --decision gas_mcf_per_boe=energy_6 --decision gads_weighting=mw_weighted \
    --decision capacity_basis=net_dependable --decision heat_rate_basis=hhv
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write metric view SQL or measure formulas, and do not pick a
decision-point value yourself.

### Step 1: Assess and draft the mapping

If a `<customer>_mapping.yaml` exists, use it. Otherwise run `profile_source.py`: it reads
`information_schema.columns` (bound parameters) and writes `<schema>_mapping.draft.yaml`
with `# REVIEW` on every synonym match and unmapped required field. Or start from an
adapter (`allocated_production`, `nerc_gads_performance`, `eia923_generation`,
`reliability_metrics_daily_fact`) via `extends:`.

### Step 2: Confirm the mapping

Walk the user through each `# REVIEW`. Convert units in the mapping (m³ → Mcf, kWh → MWh);
canonical units are in `references/canonical_model.yaml`. Joins must be to-one. See
`references/mapping_spec.md`.

```yaml
entities:
  well_day:
    source: main.ops_raw.daily_volumes
    fields: { well_id: uwi, production_date: prod_date, oil_bbl: oil_bbl, gas_mcf: "gas_m3 * 0.0353147" }
```

### Step 3: Preview scope and decisions (read-only)

```python
import sys; sys.path.append('<this-skill-dir>/scripts')
from generate_semantic_layer import preview_semantic_layer
print(preview_semantic_layer("<customer>_mapping.yaml")["readout"])
```

Lists every metric view to BUILD or SKIP (with reasons), measures dropped for unmapped
fields, and the decisions needed with their options. Ask the user for each decision.

### Step 4: Generate under confirmed decisions

```python
from generate_semantic_layer import build_confirmed_semantic_layer
res = build_confirmed_semantic_layer("<customer>_mapping.yaml",
        {"gas_mcf_per_boe": "energy_6", "gads_weighting": "mw_weighted",
         "capacity_basis": "net_dependable", "heat_rate_basis": "hhv"}, "generated")
```

Missing decisions raise `DecisionRequired`. Output: `01_silver.sql`, `03_metric_views.sql`,
`plan.md`, `manifest.json`.

### Step 5: Justify, deploy, and smoke-test

Present `plan.md` for sign-off. On explicit approval:

```python
from semantic_run import deploy_generated
print(deploy_generated("generated"))          # runs both files, then SELECT MEASURE(...) per view
```

### Step 6: Expose

Add the metric views to a Genie space and dashboards; see `references/consumption.md`.

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `gas_mcf_per_boe` | `energy_6`, `energy_5_8` | Operator reporting policy (NI 51-101 uses 6:1) | Every boe measure and boe-based intensity |
| `gads_weighting` | `unweighted`, `mw_weighted` | NERC GADS DRI Appendix F | Fleet EAF / EFOR / FOR; small units weigh less when MW-weighted |
| `capacity_basis` | `nameplate`, `net_summer`, `net_winter`, `net_dependable` | EIA-860; GADS NMC | Capacity factor; recorded in the manifest, delivered by the mapping |
| `heat_rate_basis` | `hhv`, `lhv` | EIA-923 (HHV) | Heat rate (~10% apart for gas); recorded in the manifest |

Decisions are required only when an in-scope measure or mapped field needs them.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `--mapping` | (required) | path | Per-customer mapping |
| `--out` | `generated` | path | Output directory |
| `--preview` | off | flag | Read-only scope + decisions |
| `--decision` | none | `name=option`, repeatable | Confirmed decisions |
| mapping `scope.domains` | all mappable | `upstream`, `generation`, `grid`, `renewables`, `emissions`, `customer` | Restrict domains |

## Expected Outputs

- `01_silver.sql` — one conforming view per mapped entity (unit conversion, enum CASE,
  to-one joins, defaults for unmapped NGL).
- `03_metric_views.sql` — `mv_<domain>__<entity>` metric views (YAML v1.1) with measure
  comments carrying definition and unit.
- `plan.md` — built vs. skipped with reasons, and the decisions used.
- `manifest.json` — decisions, sources, catalog and skill versions, measures per view.
- `references/catalog.md` — human-readable catalog (regenerate with `render_catalog.py`).

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `UNRESOLVED_COLUMN` on deploy | Mapping names a column that does not exist | Fix the mapping; regenerate |
| A metric view is missing | Entity not mapped | Check `plan.md` skip reason |
| A measure is missing | An optional field it needs is unmapped | Map it or accept reduced coverage |
| Fleet EAF differs from GADS reports | Different pooling | Check `gads_weighting` in the manifest |
| Field boe/d disagrees with a dashboard | Dashboard averages per-well daily rates | Use `MEASURE(boe_per_day)` (total boe ÷ calendar days) |
| SAIDI by region too low | Daily fact missing zero-outage days | Use the reliability-metrics daily fact (complete grid) |
| `Invalid Unity Catalog identifier` | Placeholder `<catalog>` left in an adapter | Set real names |

## Guardrails

1. Never invent a measure inline; add it to `references/measure_catalog/`, run
   `validate_catalog.py` (0 errors) and `render_catalog.py`, then regenerate.
2. Rates are always composites (`MEASURE()/MEASURE()`), never stored or averaged ratios.
3. Never choose a decision for the user; show the preview and ask.
4. Customer mappings and generated SQL stay in the working directory.
5. Deploying views and creating Genie spaces are outward actions: get explicit approval.
6. Avoid retrying a failing deploy more than 3 times; report the error.

## Related Skills

- `reliability-metrics` — builds the complete daily fact the grid reliability view reads.
- `ghg-emissions-calculator` — produces the facility emissions the emissions view reads.
- `wind-solar-performance` — plant-interval inputs (POA insolation, lost energy) for renewables.
- `decline-curve-analysis` / `osdu-ppdm-mapper` — upstream volumes and well identity.
- `unit-guard` — vetted unit conversions for mapping expressions.
- `skill-eval` — benchmark this skill with and without it loaded.

## References

- `references/canonical_model.yaml` — entity contract (grains, fields, units).
- `references/decisions.yaml` — decision registry.
- `references/measure_catalog/*.yaml` — measure source of truth; `references/catalog.md` rendered view.
- `references/mapping_spec.md` · `kpi_pitfalls.md` · `consumption.md` — workflow notes.
- `references/adapters/*.yaml` — starter mappings.
- [Databricks metric views](https://docs.databricks.com/aws/en/metric-views/)
- [NERC GADS Appendix F](https://www.nerc.com/globalassets/programs/rapa/gads/conventional/appendix_f_equations_2026.pdf)
- [EIA electricity data (860 / 861 / 923)](https://www.eia.gov/electricity/data.php)
