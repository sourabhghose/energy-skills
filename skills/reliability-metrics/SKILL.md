---
name: reliability-metrics
description: >-
  IEEE 1366 distribution reliability indices (SAIDI, SAIFI, CAIDI, CAIFI, ASAI, MAIFI,
  MAIFI_E, CEMI-n, CELID) from OMS outage restoration steps and CIS customers served, with
  Major Event Day (MED) identification by the 2.5 beta method. Handles step restoration
  (customer-minutes per restoration step), sustained vs. momentary classification per step,
  local-day event dating, leap-year ASAI, and cause-code breakdown. Surfaces the decisions a
  reliability engineer owns (sustained threshold, average vs. year-end customers served,
  planned-outage handling, MED exclusion) with their effect on the data before building.
  Reports indices with and without MEDs, writes a run manifest, and emits a Unity Catalog
  metric view over a complete daily fact table. Run by calling the vetted entrypoints in
  scripts/reliability_run.py or scripts/reliability_api.py; do not hand-write SAIDI SQL.
  For a broader energy KPI layer use energy-semantic-builder; for de-identifying customer
  outage records use grid-data-guard.
category: "Power & Utilities"
summary: IEEE 1366 SAIDI/SAIFI/CAIDI/MAIFI with 2.5-beta Major Event Days, step restoration, and a governed metric view.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Reliability Metrics (IEEE 1366)

## Overview

Turns outage-management history into the distribution reliability indices regulators and
benchmarking programs (EIA-861, IEEE DRWG) ask for. The skill computes customer-minutes
**per restoration step**, classifies each step as sustained or momentary, dates events by
the **local** day they began, derives the Major Event Day threshold from the **prior five
years**, and reports every index both **with and without MEDs**. The output is a set of UC
tables (indices, cause breakdown, daily fact, manifest) plus a metric view that keeps
SAIDI/SAIFI/CAIDI correct when sliced by month or circuit.

It runs on the **execution model**: Genie Code calls the entrypoints and reports their
output. It does not write its own SAIDI SQL and does not choose a decision-point value.

## When to Use

- "What was our 2024 SAIDI and SAIFI, with and without major events?"
- "Which days in 2024 were Major Event Days, and what was T_MED?"
- "Rebuild our reliability report from the OMS restoration-step table."
- "How much of our customer-minutes came from vegetation vs. equipment?"
- "Compare reliability under average vs. year-end customer counts before we file."
- "Give us a metric view so Genie can answer SAIDI by circuit and month."
- "Compute MAIFI_E from recloser operation logs."
- "Which customers had more than 3 interruptions (CEMI-3) or an outage longer than 8 hours?"

## Prerequisites

- **Compute**: Python-enabled compute (serverless or a cluster), not a SQL-only warehouse;
  the runner needs a Spark session.
- **Inputs** (see `references/data_contract.md`):
  - restoration steps: `event_id, outage_start, restore_ts, customers_restored, cause_code, is_planned [, circuit_id]`
  - customers served: `period_start, customers_served [, circuit_id]` (monthly preferred)
  - at least one full year of history **before** the reporting year (five years for a
    stable MED threshold)
  - optional: recloser operations (MAIFI_E); customer-level interruptions (CAIFI, CEMI, CELID)
- **Timezone**: the utility's local IANA zone (e.g. `America/Chicago`). Required.

## Quick Start

```python
import sys
sys.path.append('<this-skill-dir>/scripts')
from reliability_run import preview_from_uc, build_confirmed_from_uc

# STEP 1 — READ-ONLY. Shows SAIDI/SAIFI/CAIDI under every decision combination.
out = preview_from_uc("<cat.sch.restoration_steps>", "<cat.sch.customers_served>",
                      reporting_year=2024, tz="America/Chicago",
                      steps_columns={"outage_start": "OUT_TS", "restore_ts": "REST_TS"})
print(out["readout"])

# STEP 2 — ONLY after the user picks each decision.
res = build_confirmed_from_uc("<cat.sch.restoration_steps>", "<cat.sch.customers_served>",
                              reporting_year=2024, tz="America/Chicago",
                              target_prefix="<cat.sch.reliability_2024>",
                              sustained_threshold_min=5, denominator_basis="average",
                              planned_handling="exclude_planned", med_method="ieee_2_5_beta")
print(res["readout"])
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write the calculation, and do not pick a decision-point value yourself.
The steps below describe what the entrypoints do so a reviewer can check them.

### Step 1: Map and validate the inputs

Map physical columns to the canonical names (`steps_columns`, `customers_columns`).
`validate_steps` rejects naive timestamps, restores before outage start, and non-positive
customer counts. Spark returns naive timestamps in the session timezone; the runner
localizes them as UTC and converts to `tz`.

```python
from reliability_core import validate_steps
validate_steps(steps)   # [] when clean
```

### Step 2: Preview the decision points (read-only)

`preview_reliability_options` computes 16 scenarios (threshold × denominator × planned ×
MED) for the reporting year and prints the SAIDI range. Show the table to the user and ask
for each decision. If the data has one row per event (no steps), say so: CMI is overstated
when the utility actually restored in stages.

```python
print(preview_reliability_options(steps, customers, 2024, "America/Chicago")["readout"])
```

### Step 3: Classify steps and build events

Each step's customers × minutes since outage start is its CMI. Steps restored in ≤ threshold
minutes are momentary (they count toward MAIFI, not SAIDI). Events are dated by the local
calendar day of `outage_start`.

### Step 4: Identify Major Event Days

Daily SAIDI for the five years before the reporting year → drop zero days → ln → alpha
(mean), beta (sample std) → `T_MED = exp(alpha + 2.5·beta)`. Days in the reporting year
with daily SAIDI above T_MED are MEDs. Fewer than five history years produces a warning
in the readout. See `references/major_event_days.md`.

### Step 5: Build under confirmed decisions

```python
from reliability_api import build_confirmed_reliability
res = build_confirmed_reliability(steps, customers, 2024, "America/Chicago",
                                  sustained_threshold_min=5, denominator_basis="average",
                                  planned_handling="exclude_planned", med_method="ieee_2_5_beta")
```

Missing or invalid decisions raise `DecisionRequired` with the options. The result holds
`headline`, `all_days`, `excluding_med`, `major_event_days`, `med_stats`, `cause_breakdown`,
`manifest`, and `readout`.

### Step 6: Persist and expose

`build_confirmed_from_uc` writes `<prefix>_indices`, `<prefix>_daily_fact`,
`<prefix>_causes`, `<prefix>_manifest`, and creates the metric view `<prefix>_mv`.
Smoke-test it:

```sql
SELECT event_month, MEASURE(saidi_min), MEASURE(saidi_excl_med_min), MEASURE(caidi_min)
FROM <cat.sch.reliability_2024_mv> GROUP BY ALL ORDER BY ALL;
```

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `sustained_threshold_min` | `5`, `1` | IEEE 1366 (> 5 min); some state PUC rules (> 1 min) | Which steps count toward SAIDI/SAIFI vs. MAIFI |
| `denominator_basis` | `average`, `year_end` | Utility / regulator reporting rule | N_T for every per-customer index; growing utilities report lower indices on year-end |
| `planned_handling` | `exclude_planned`, `include_planned` | State reporting rules | CMI and CI from pre-notified work |
| `med_method` | `ieee_2_5_beta`, `none` | IEEE 1366 2.5 beta method | Headline indices exclude MED days; both are always reported |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `reporting_year` | (required) | year with ≥ 1 prior year of history | Year reported; T_MED uses the 5 prior years |
| `tz` | (required) | IANA zone | Local day for event dating and MED |
| `target_prefix` | (required for build) | `catalog.schema.name` | Prefix for output tables and metric view |
| `momentary_ops` | `None` | DataFrame | Enables MAIFI_E (5-minute reclosing sequences) |
| `customer_events` | `None` | DataFrame | Enables CAIFI, CEMI_3, CELID_s/t (8 h) |
| `steps_columns` / `customers_columns` | `None` | `{canonical: physical}` | Column mapping |

## Expected Outputs

- Readout: SAIDI / SAIFI / CAIDI / ASAI for all days and excluding MEDs, T_MED with alpha,
  beta, history years, the MED list, and warnings.
- `<prefix>_indices`: one row each for `headline`, `all_days`, `excluding_med`.
- `<prefix>_causes`: events, CI, CMI, CMI share by cause code (non-MED days).
- `<prefix>_daily_fact`: every day × circuit with `customer_minutes`,
  `customers_interrupted`, `momentary_customers`, `customers_served`, `is_med`.
- `<prefix>_manifest`: decisions, timezone, inputs, standard, T_MED, MED dates, version.
- `<prefix>_mv`: metric view with `saidi_min`, `saifi`, `caidi_min`, `maifi`,
  `saidi_excl_med_min`, `saifi_excl_med` as ratio-of-measures.

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `timestamps must be timezone-aware` | Naive timestamps passed to the core | Use the runner (localizes) or `tz_localize` before calling |
| `need prior-year history to set T_MED` | No history before the reporting year | Load prior years, or choose `med_method="none"` and say why |
| SAIDI far above EIA-861 peers | One-row-per-event OMS data, or planned outages included | Check `n_steps`; review `planned_handling` |
| CAIDI in metric view differs from a dashboard | Dashboard averages circuit CAIDIs | Use `MEASURE(caidi_min)` (ratio of sums) |
| Monthly SAIFI × CAIDI ≠ annual SAIDI | CAIDI is not additive across months | Monthly SAIDI sums to annual (N_T fixed for the year); CAIDI must be recomputed per slice |
| Storm split across two days | Events dated in UTC | Pass the correct local `tz` |

## Guardrails

1. Never choose a decision value for the user; show the preview and ask.
2. Always report both all-days and excluding-MED values, with T_MED and the MED list.
3. Do not compute CAIDI or SAIDI by averaging across circuits or months.
4. Customer-level outputs (CEMI, CELID inputs) are customer data: aggregate before sharing;
   use `grid-data-guard` to de-identify.
5. Writing tables and the metric view is an outward action: show the plan and get approval.
6. Avoid retrying a failing build more than 3 times; report the error instead.

## Related Skills

- `energy-semantic-builder` — governed KPI layer; its reliability measures read this skill's daily fact.
- `grid-data-guard` — de-identify customer-level outage data and mask CEII before sharing.
- `wildfire-asset-risk` — PSPS events show up here as planned or weather-cause interruptions.
- `energy-report-writer` — turn the readout and manifest into a regulatory reliability report.
- `skill-eval` — benchmark this skill with and without it loaded.

## References

- `references/ieee1366_indices.md` — index definitions, terms, common mistakes.
- `references/major_event_days.md` — the 2.5 beta method and its pitfalls.
- `references/data_contract.md` — canonical input columns.
- [IEEE Std 1366-2022](https://standards.ieee.org/ieee/1366/7243/) — governing guide (purchase required).
- [EIA-861 reliability data](https://www.eia.gov/electricity/data/eia861/) — peer benchmarking, with and without MED.
- [IEEE PES DRWG](https://cmte.ieee.org/pes-drwg/) — benchmarking and MED methodology background.
