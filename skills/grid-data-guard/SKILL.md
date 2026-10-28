---
name: grid-data-guard
description: >-
  CEII and customer energy-data protection on Unity Catalog: classifies grid data columns
  (critical energy infrastructure information such as substation/feeder topology and relay
  or SCADA settings, customer PII, account/premise/meter IDs, precise coordinates, kWh
  consumption), then builds either a governed record-level view for need-to-know internal
  users (privileged-group masking via is_account_group_member, secret-salted SHA-256
  tokens, H3/rounded geo cells) or an aggregate-only release for partners or the public
  that enforces the CPUC 15/15 rule (≥15 customers, no customer >15 % of load) or a k-only
  rule, with complementary suppression. A read-only preview shows suppression by grouping
  and grain. Run by calling scripts/gdg_run.py; do not hand-write masking or aggregation
  SQL. For VEE on raw meter data use ami-interval-analytics; for wildfire asset geospatial
  analysis use wildfire-asset-risk.
category: "Power & Utilities"
summary: Protect CEII and customer meter data with masked internal views or 15/15-checked aggregate releases.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Grid Data Guard: CEII and Customer Energy-Data Protection

## Overview

Utilities share grid and meter data all the time: with planners, vendors, regulators,
researchers, and open-data portals. A general coding agent "anonymizes" by dropping the name
column. It leaves feeder topology and relay settings in place, hashes account numbers
without a salt, counts rows instead of customers, and publishes a ZIP code where one factory
is 80 % of the load. This skill classifies every column, previews the privacy/utility
trade-off on the full table, and builds one of two governed outputs:

- **Internal (record-level):** a dynamic view where CEII, direct PII, and precise coordinates
  are NULL unless the reader is in the privileged group, IDs are secret-salted tokens, and a
  generalized `geo_cell` is added.
- **External / public (aggregate-only):** a table of cells that pass the 15/15 (or k-only)
  rule, with complementary suppression and no largest-customer statistics, plus a
  suppression summary.

Both write a run manifest with the column plan and every decision.

## When to Use

- "We need to share monthly usage by ZIP with a city climate team. Make it compliant."
- "Give the planning vendor feeder data without exposing CEII."
- "Create a view of AMI data our analysts can use without seeing customer names or account
  numbers."
- "Which columns in this table are CEII or PII?"
- "Publish hourly load by neighborhood on our open-data portal."
- "Tokenize premise IDs consistently so we can still join tables."
- "Check whether an aggregate release passes the 15/15 rule."

## Prerequisites

- **Compute:** Python compute (serverless) or a SQL warehouse via the SDK. Aggregates are
  computed in SQL and only cell statistics are pulled.
- **Internal views:** a UC account group for privileged access (map it to the CIP-004 access
  list for CEII), and a Databricks secret (`scope/key`) holding the token salt.
- **Aggregate releases:** a customer identifier column (premise, account, or service point),
  a value column (kWh), and optionally a time column and coordinates.
- **Permissions:** `CREATE VIEW` / `CREATE TABLE` on the target schema. `tag_source_columns`
  needs `APPLY TAG` on the source.

## Quick Start

```python
import sys
sys.path.append('<this-skill-dir>/scripts')
from gdg_run import preview_guard_options, build_confirmed_guard

# STEP 1: READ-ONLY. Column classes, coordinate uniqueness, suppression by grouping.
print(preview_guard_options("main.ami.monthly_usage", customer_col="premise_id",
                            value_col="kwh", time_col="read_month", lat_col="lat",
                            lon_col="lon",
                            candidate_groupings=[["zip"], ["rate_class", "zip"], ["geo"]]))

# STEP 2: ONLY after the user (or privacy officer) has decided.
print(build_confirmed_guard("main.ami.monthly_usage", "main.share.usage_by_zip_month",
                            release_audience="public", aggregation_rule="15_15",
                            group_by=["zip"], time_grain="month",
                            customer_col="premise_id", value_col="kwh",
                            time_col="read_month"))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call `preview_guard_options` and then
`build_confirmed_guard`, and report their output. Do not write masking or aggregation SQL
yourself, and do not choose the audience, rule, grouping, grain, or geo precision.

### Step 1: Classify columns

Name and value rules assign each column to `PII_DIRECT`, `PII_ID`, `GEO_PRECISE`,
`CEII_TOPOLOGY`, `CEII_SETTINGS`, `CONSUMPTION`, `QUASI`, `TIME`, or `OTHER`. Value rules
catch misnamed columns (emails, phone numbers, street addresses, IP addresses, WKT points).
Show the classes and accept corrections through `class_overrides={"col": "CLASS"}`.

### Step 2: Preview the risk (read-only)

For each candidate grouping (and H3 7 / H3 8 / 2-decimal rounding when grouping by `geo`),
the preview runs an aggregated read over the **full** table and reports cells, suppressed
cells, the % of energy suppressed, and the reasons. It also reports how many coordinates are
unique (precise points identify premises). **Show this to the user and ask for the
decisions.**

### Step 3: Plan per audience

The plan comes from `references/protection_methods.md`. Public releases cannot group by
grid topology, and no external release can group by IDs, direct PII, or settings.

### Step 4a: Internal: governed view

A `CREATE OR REPLACE VIEW` masks columns with `is_account_group_member(<group>)`, tokenizes
with `sha2(concat(secret(scope, key), col))`, and adds `geo_cell` when coordinates exist.

### Step 4b: External / public: aggregate release

Per-customer totals are computed per cell, followed by customer counts and the max customer
share, then the rule and complementary suppression within each period. Only passing cells
(`n_customers`, `total_<value>`) are written. The largest-customer statistics are never
published.

### Step 5: Report

The skill prints the column plan, what was masked or tokenized or how many cells were
released and suppressed, and the manifest id. Remind the user that the release decision
belongs to their privacy/CIP owner.

## Decision Points

| Decision | Options | Governing practice | What changes |
|----------|---------|--------------------|--------------|
| `release_audience` | `internal_need_to_know`, `external_partner`, `public` | Data-sharing agreement, CEII/NDA status | Record-level vs aggregate-only |
| `privileged_group` | UC account group | NERC CIP-004 access list / data owner | Who sees CEII and direct PII |
| `tokenization_secret` | `scope/key` | Key management policy | Token stability and reversibility |
| `aggregation_rule` | `15_15`, `k_only` (+ `k_min`) | CPUC 15/15; other commissions' k-rules | Which cells are suppressed |
| `group_by` | quasi columns and/or `geo` (topology for partners only) | Use case vs re-identification risk | Cell size |
| `time_grain` | `month`, `day`, `hour` | Finer = higher load-shape risk | Cell size, utility |
| `geo_method` / `geo_precision` | `h3` (res 7, 8, …) or `round` (decimals) | Planning need vs premise identification | Spatial resolution |

## Key Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `class_overrides` | `None` | Correct the classifier per column |
| `tag_source_columns` | `False` | Add `energy_sensitivity` tags to the source table columns |
| `complementary_suppression` (config) | `True` | Prevent recovery of a suppressed cell by subtraction |
| `sample_rows` (preview) | `50 000` | Rows sampled for classification only (risk uses the full table) |

## Expected Outputs

- Internal: view `<output>` with masked and tokenized columns plus `geo_cell`
- External/public: table `<output>` (`<group cols>`, `period`, `n_customers`,
  `total_<value>`) and `<output>_suppression` (cell counts by reason)
- `<output>_manifest`: column plan, decisions, inputs, outputs

## Common Recipes

### Recipe: Classification only

```python
from gdg_classify import classify_columns
classify_columns(spark.table("main.gis.assets").limit(5000).toPandas())
```

### Recipe: Check an existing aggregate against 15/15

```python
from gdg_core import group_stats, apply_rule, risk_summary
risk_summary(apply_rule(group_stats(pdf, ["zip", "month"], "premise_id", "kwh"), "15_15", 15, 15))
```

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `DecisionRequired` | Missing decision for this audience | Ask the user or their privacy officer |
| "15/15 fixes k=15 and share=15 %" | Custom k with `15_15` | Use `aggregation_rule='k_only'` with `k_min` |
| "would publish grid topology (CEII)" | Public release grouped by feeder/substation | Group by ZIP, H3, or rate class |
| Most cells suppressed | Grain too fine | Coarser time or geography; merge rate classes |
| Column misclassified | Name/value heuristics | Pass `class_overrides` and re-run the preview |
| `secret` function error | Scope/key missing or no READ permission | Create the secret; grant READ to the view owner |

## Guardrails

1. Never choose the audience or the rule yourself, and never present this skill as legal
   sign-off.
2. Never release record-level customer data outside `internal_need_to_know`.
3. Never hash IDs without the secret salt, and never print the salt.
4. Never publish largest-customer values or shares.
5. Don't copy raw sensitive data to a new table. Internal access goes through the view.
6. Retry at most 3 times; ask before previewing more than ~10 candidate groupings.

## Related Skills

- `ami-interval-analytics`: VEE before aggregation
- `load-forecaster`: forecasting on protected aggregates
- `wildfire-asset-risk`: asset geospatial analysis (CEII-heavy inputs)
- `energy-semantic-builder`: governed KPIs on top of the released tables
- `energy-report-writer`: regulatory filings that cite aggregated data

## Bundled Resources

- `scripts/gdg_run.py`: entrypoints (`preview_guard_options`, `build_confirmed_guard`)
- `scripts/gdg_classify.py`: column classification rules
- `scripts/gdg_core.py`: plan, 15/15, complementary suppression, geo, tokens, risk summary
- `scripts/gdg_sql.py`: governed-view, group-statistics, and tag SQL
- `scripts/gdg_decisions.py`: audience-dependent decisions, config, manifest
- `references/regulatory_basis.md`, `references/protection_methods.md`

## References

- [18 CFR 388.113 (CEII)](https://www.ecfr.gov/current/title-18/chapter-I/subchapter-X/part-388/subpart-B/section-388.113) and [FERC CEII](https://www.ferc.gov/ceii)
- [NERC CIP standards](https://www.nerc.com/pa/Stand/Pages/ReliabilityStandards.aspx) (CIP-004, CIP-011)
- [CPUC energy data access](https://www.cpuc.ca.gov/industries-and-topics/electrical-energy/infrastructure/energy-data-access) (15/15 rule; D.14-05-016)
- [Article 29 WP Opinion 12/2011 on smart metering](https://ec.europa.eu/justice/article-29/documentation/opinion-recommendation/files/2011/wp183_en.pdf)
- [Databricks row filters and column masks](https://docs.databricks.com/en/data-governance/unity-catalog/filters-and-masks/)
