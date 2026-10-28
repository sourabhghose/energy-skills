# ARMOR — Asset Risk Modeling and Optimized Renewal

## Identity

- Name: ARMOR — Asset Risk Modeling and Optimized Renewal
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/asset-risk-and-capital-planning
- Install doc: README 'Installation' (`scripts/bundle.sh`, `databricks bundle run armor_demo`)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-10-22
- Maturity: maintained
- Reviewed: 2026-10-28 against commit ab6abc9

## Use it for

- Distribution asset (pole, transformer, device) end-of-life probability × customers affected → expected SAIFI/SAIDI contribution and risk dollars by feeder
- 10-year replacement plan under a budget with an exact MILP optimizer or rules, budget frontier, Monte Carlo uncertainty
- Life-curve fitting with out-of-sample backtests; optional Genie over the governed tables

## Do not use it for

- Computing reported IEEE 1366 SAIDI/SAIFI with Major Event Day exclusion from outage history: use `reliability-metrics`
- Wildfire ignition risk along lines: use `wildfire-asset-risk`

## Data

Runs on a fictional demo utility generated in the workspace; map your asset tables to its asset data model ('Make it yours').

## Deploy signals

Jobs `armor_demo` and `armor`; a Databricks App backed by a serverless SQL warehouse.

## Smallest path

`databricks bundle run armor_demo --var catalog=<catalog> --profile <profile>` (about 10 minutes on serverless per the README).

## Pitfalls

1. Predicted SAIFI/SAIDI contributions are model outputs, not reported reliability indices; label them so in regulatory material.
2. Needs Unity Catalog, serverless, Databricks Apps and a SQL warehouse; Lakebase and Genie are optional.

## Pair with Energy Skills

`reliability-metrics`, `wildfire-asset-risk`, `energy-report-writer`
