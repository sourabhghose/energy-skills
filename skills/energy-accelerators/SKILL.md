---
name: energy-accelerators
description: >-
  Energy solution accelerator router for Databricks - maps a power, utility, oil and gas,
  renewables or emissions request to a verified databricks-industry-solutions accelerator,
  Databricks Labs library, Brickbuilder partner solution or vendor integration (Energy
  Sandbox O&G apps, Customer 360 for Utilities, ARMOR asset risk, UK half-hourly smart
  meter forecasting, Flood Prediction, Many Models Forecasting, COMTRADE, Ignition OT
  connector, Digital Twin, DAXS, GeoBrix, Tempo, AVEVA CONNECT for PI data) and decides
  between accelerator, Energy Skill, or both. Ends with a precise next step and flags stale
  accelerators and licence traps. Consult before building an O&G app, AMI data model, asset
  risk model, OT ingestion path or forecasting framework from scratch. For packaging an
  open-weight model use energy-foundation-models.
category: Others
summary: Route energy tasks to a verified Databricks accelerator, library or partner solution — or to an Energy Skill — with the exact next step.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Energy Accelerators

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/accelerators/SKILL.md); modified for the energy industry. -->

## Overview

Databricks publishes industry solution accelerators under
[databricks-industry-solutions](https://github.com/databricks-industry-solutions), Databricks Labs libraries
under [databrickslabs](https://github.com/databrickslabs), and partner Brickbuilder solutions.
Many energy requests ("an O&G production dashboard", "a utility customer 360", "pole
replacement planning", "get Ignition tags into Delta") are already partly solved by one of
them. A general coding agent does not know they exist and rebuilds them. This skill routes
the request to a **verified** accelerator (or to an Energy Skill, or both) and ends with a
precise next step.

The skill is instructions only; it installs nothing. Per-accelerator facts live in
`references/accelerators/<name>.md`; the routing index is `references/accelerators/index.md`.
Every card was checked against the live repo or page on 2026-10-28.

## When to Use

- "Is there a Databricks accelerator for <utility / O&G / renewables / emissions problem>?"
- A user is about to build an O&G demo app, AMI customer data model, asset-risk model,
  flood map, or many-series forecasting framework from scratch
- "How do we get PI / Ignition / SCADA data into Databricks?"
- "What can we show a utility (or an operator) on Databricks next week?"
- The user names an accelerator and wants to know whether it fits, is current, and what to run first
- The user asks whether to use an accelerator or an Energy Skill for a task

## Key Concepts

### Steer, do not rebuild
Recommend the matching accelerator first; it saves days and avoids known failure modes.

### Accelerator vs Energy Skill
Accelerators are **end-to-end demos and reference implementations** (apps, pipelines,
data models). Energy Skills are **disciplined analysis steps** (decision points, units,
DST, reproducible manifests) that Genie Code runs on the user's own data. Often the answer
is both: e.g. clean AMI data with `ami-interval-analytics`, then load it into Customer 360.

### Precise next step
Every answer ends with **Next step**: one concrete command or action the user can take
now, and any admin action with the role that performs it. A link alone is not a next step.

### Verified only
List only accelerators in `references/accelerators/index.md`. If nothing fits, say so; do
not invent repo names. Flag cards marked **stale (>18 months)** and expect runtime drift.

### Not supported products
Accelerators are provided as-is without SLAs; issues go to the repo's GitHub Issues.
Partner solutions carry commercial terms.

## Decision Framework

```
What is the user trying to do?
├── Power & Utilities
│   ├── AMI + billing + complaints customer analytics → customer-360-for-utilities (+ ami-interval-analytics first)
│   ├── Pole / transformer replacement plan, risk $ per feeder → asset-risk-and-capital-planning (ARMOR)
│   ├── Reported SAIDI/SAIFI with MED exclusion → reliability-metrics (skill, not an accelerator)
│   ├── UK MHHS half-hourly forecasting → half-hourly-energy-data
│   ├── Transformer overload from AMI → ibm-transformer-load-management (partner) or ami-interval-analytics + energy-semantic-builder
│   ├── Relay / DFR fault records → comtrade-accelerator (stale)
│   ├── Drone imagery of assets → utilities-cv (stale); satellite imagery → energy-foundation-models
│   └── Flood exposure of assets → flood-prediction (+ wildfire-asset-risk for fire)
├── Oil & Gas
│   ├── Demo app (production optimizer, ESP PdM, LAS viewer, drilling, pipeline twin) → energy-sandbox
│   ├── OSDU / ADME into Unity Catalog → energy-sandbox/osdu-app-with-connector (+ osdu-ppdm-mapper)
│   └── Reserves-grade decline curves, LAS ingestion, NPT → decline-curve-analysis / well-log-ingest / drilling-report-npt
├── OT / historian ingestion
│   ├── Ignition Gateway → lakeflow-zerobus-ignition-connector
│   └── AVEVA PI System → aveva-connect (Delta Sharing); on-prem PI without CONNECT → custom Lakeflow connector
├── Equipment health
│   ├── Unlabelled per-asset anomaly detection at fleet scale → daxs
│   ├── Labelled failure prediction / RUL → equipment-pdm (skill)
│   └── Semantic twin + low-latency app → digital-twin
├── Forecasting at scale → many-model-forecasting (licence-check foundation models with energy-foundation-models)
├── Trading → lovelytics-energylytics (partner) + iso-market-data (skill)
├── Data model for a new domain → lakehouse-industry-data-models (+ osdu-ppdm-mapper for standards)
├── Field knowledge from work orders → field-repair-knowledge-assistant
├── ESG reporting text (CSRD/ESRS) → csrd-assistant (stale); emissions numbers → ghg-emissions-calculator
└── Geospatial / time-series building blocks → geobrix, tempo
```

| Task | Route | Smallest path | Reference |
|---|---|---|---|
| O&G production / ESP / LAS demo app | Energy Sandbox project folder | `databricks bundle deploy` in the project | `references/accelerators/energy-sandbox.md` |
| Utility customer 360 | Customer 360 for Utilities | `databricks bundle run customer_360_job` | `references/accelerators/customer-360-for-utilities.md` |
| Asset replacement capital plan | ARMOR | `databricks bundle run armor_demo` | `references/accelerators/asset-risk-and-capital-planning.md` |
| UK half-hourly meter forecasting | half-hourly-energy-data | `src/00_project_setup.ipynb` | `references/accelerators/half-hourly-energy-data.md` |
| Flood probability on H3 | Flood Prediction | bundle deploy + pipeline job | `references/accelerators/flood-prediction.md` |
| Thousands of series to forecast | Many Models Forecasting | `pip install mmf_sa[...]` on DBR 18 ML+ | `references/accelerators/many-model-forecasting.md` |
| COMTRADE fault records | COMTRADE accelerator | `RUNME.py` | `references/accelerators/comtrade-accelerator.md` |
| Drone images of poles / transformers | Utilities CV | `RUNME.py` on GPU | `references/accelerators/utilities-cv.md` |
| Simulated feeder faults | Electrical fault detection (MATLAB) | notebook 03 on existing data | `references/accelerators/electrical-fault-detection-matlab.md` |
| Ignition tags into Delta | Ignition OT connector | install module, `sinkMode=zerobus` | `references/accelerators/lakeflow-zerobus-ignition-connector.md` |
| Asset digital twin app | Digital Twin | `databricks bundle run setup_solution_accelerator` | `references/accelerators/digital-twin.md` |
| Fleet anomaly detection | DAXS | `01_explainable.py` on DBR ML | `references/accelerators/daxs.md` |
| Work-order knowledge assistant | Field repair knowledge assistant | deploy on shipped corpus | `references/accelerators/field-repair-knowledge-assistant.md` |
| Generated energy data model | Lakehouse industry data models | start from `data-models/energy_utilities` | `references/accelerators/lakehouse-industry-data-models.md` |
| CSRD / ESRS Q&A | CSRD assistant | repo notebooks | `references/accelerators/csrd-assistant.md` |
| Rasters, grids, H3 tessellation | GeoBrix | lightweight tier on serverless | `references/accelerators/geobrix.md` |
| As-of joins, resampling at scale | Tempo | `%pip install dbl-tempo` | `references/accelerators/tempo.md` |
| Energy trading solution | Energylytics (partner) | contact partner | `references/accelerators/lovelytics-energylytics.md` |
| Transformer load from AMI | IBM Transformer Load Management (partner) | contact partner | `references/accelerators/ibm-transformer-load-management.md` |
| PI System historian data | AVEVA CONNECT integration | request a Delta Share | `references/accelerators/aveva-connect.md` |

## Decision Points

| Decision | Options | Who decides | What changes |
|---|---|---|---|
| Route | accelerator, Energy Skill, both, none fits | user, after the recommendation | what gets built |
| Path | smallest path vs full install | user (and workspace admin) | admin rights, cost, time |
| Stale accelerator | use and update, or build with Energy Skills | user | expected runtime / dependency fixes |
| Partner solution | engage partner vs build | user (procurement) | commercial terms |
| Data | demo data vs own tables | user / data owner | governance review needed for own data |

## Best Practices

1. **Route before writing code**: match the Decision Framework, then read only that card.
2. **Check whether it is already deployed**: ask, or look for the card's deploy signals.
3. **Prefer the smallest path**: one notebook or one bundle job before a full install.
4. **Name blockers precisely**: Lakebase, Databricks Apps, GPU serving, Genie, MATLAB licences, OT change control — and who enables them.
5. **Cite the repo and file**: give the URL and the README / notebook to open.
6. **Pair with skills**: say which Energy Skill to run before or after (e.g. VEE before Customer 360).

## Troubleshooting

1. **Nothing in the index fits**: say so and name the Energy Skill to use; do not invent a repo.
2. **Stale accelerator fails on a current runtime**: pin the runtime the README names, or port the logic using the paired Energy Skill.
3. **Install blocked on a gated feature** (Apps, Lakebase, GPU serving): list the feature and the admin role from the card.
4. **Cloud-specific settings**: GPU workload types differ by cloud (e.g. no `GPU_MEDIUM` serving on Azure); ask which cloud first.
5. **OT ingestion stalls in review**: Gateway modules and PI access are OT changes; involve the site OT owner early.

## Workflow

1. **Step 1: Classify the request** against the Decision Framework. No match → say so and route to an Energy Skill.
2. **Step 2: Read the card** `references/accelerators/<name>.md` for use / do-not-use, data, deploy signals, smallest path, pitfalls.
3. **Step 3: Check current state**: already deployed? which cloud and compute? admin access?
4. **Step 4: Answer** with the route, why, the paired Energy Skill, and a **Next step**: the first command or action, then any admin action with the role that performs it.

## Protocol Guidelines

1. One card per accelerator: copy `references/accelerator-template.md`, fill every field, add an index row.
2. Verify before listing: open the repo (record the commit) or the page (HTTP 200) and record the review date.
3. Mark maturity: `stale (>18 months)` when the last commit is older than 18 months.
4. Update this file only for routing: add a Decision Framework branch and a table row.

## Guardrails

1. Do not install or deploy accelerators on the user's behalf; give the commands.
2. Do not claim an accelerator supports a model, format, protocol or cloud unless its card or repo documents it.
3. Do not list accelerators that are not in the index; never invent repository names or URLs.
4. Treat accelerator outputs (risk scores, forecasts, predicted reliability contributions) as analysis, not regulatory filings.
5. Never suggest deleting accelerator resources by hand; use the accelerator's destroy / teardown job.
6. Avoid retrying more than 3 times; collect logs and point to the repo's GitHub Issues.

## References

- [databricks-industry-solutions on GitHub](https://github.com/databricks-industry-solutions) — all published solution accelerators
- [Databricks solution accelerators](https://www.databricks.com/solutions/accelerators)
- [Brickbuilder partner solutions](https://www.databricks.com/partners/consulting-and-si/partner-solutions)
- [Databricks Labs GeoBrix](https://github.com/databrickslabs/geobrix) and [Tempo](https://github.com/databrickslabs/tempo)
- [Lakeflow custom connectors](https://docs.databricks.com/aws/en/ingestion/custom-connectors)
- [Vital Skills accelerators skill](https://github.com/databricks-industry-solutions/vital-skills/tree/main/skills/accelerators) — the HLS skill this adapts

## Related Skills

- `energy-foundation-models` — package an open-weight model no accelerator ships; licence checks for MMF foundation models
- `ami-interval-analytics` — VEE before Customer 360 or half-hourly forecasting
- `reliability-metrics` — reported IEEE 1366 indices (ARMOR predicts contributions)
- `decline-curve-analysis`, `well-log-ingest`, `drilling-report-npt`, `osdu-ppdm-mapper` — disciplined O&G steps behind the Energy Sandbox demos
- `equipment-pdm` — labelled failure prediction after OT ingestion
- `wildfire-asset-risk` — fire exposure alongside Flood Prediction
- `ghg-emissions-calculator` — emissions numbers for CSRD / ESRS disclosures
