# Customer 360 for Utilities

## Identity

- Name: Customer 360 for Utilities
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/customer-360-for-utilities
- Install doc: README (Databricks Asset Bundle: `databricks bundle deploy`, `databricks bundle run customer_360_job`)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-08-14
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 74049b6

## Use it for

- A governed customer data model combining hourly AMI intervals, account and rate history, building characteristics, weather, and complaint / service-call text
- Genie space for natural-language analysis plus an interactive app (map, relationship history, complaint drivers, ML predictions)
- Rate design, EE/DER program targeting, end-use detection (EV, solar, HVAC), complaint root-cause analytics

## Do not use it for

- Validating, estimating and editing raw interval reads (DST, gaps, estimated reads): use `ami-interval-analytics` first
- De-identifying meter data for sharing: use `grid-data-guard`
- Load forecasting: use `load-forecaster`

## Data

Generates demo data on serverless; map your own AMI / CIS tables into its model to go further.

## Deploy signals

Job `customer_360_job`, job `app_focus_set_setup`, app `customer_360` (names from the README's bundle commands).

## Smallest path

`databricks bundle deploy --var catalog=<catalog> --var schema=customer_360` then `databricks bundle run customer_360_job`.

## Pitfalls

1. Interval data in the demo is clean; real AMI needs VEE before it feeds rate design.
2. Customer-level data is personal data; apply UC row filters / masks before sharing the Genie space widely.

## Pair with Energy Skills

`ami-interval-analytics` (before), `grid-data-guard`, `energy-semantic-builder`
