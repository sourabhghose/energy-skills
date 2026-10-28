# CSRD assistant (csrd_assistant)

## Identity

- Name: CSRD assistant (csrd_assistant)
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/csrd_assistant
- Install doc: repo notebooks
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2024-06-06
- Maturity: stale (>18 months)
- Reviewed: 2026-10-28 against commit 8381da4

## Use it for

- Question answering over the EU CSRD regulation and ESRS reporting standards for sustainability-report authors
- A starting point for sector-specific ESRS (oil and gas, energy production)

## Do not use it for

- Calculating Scope 1/2/3 emissions with versioned factors: use `ghg-emissions-calculator`
- Drafting the report narrative from computed results: use `energy-report-writer`

## Data

Public CSRD / ESRS legal text.

## Deploy signals

Not documented.

## Smallest path

Clone and run the notebooks against the regulation text.

## Pitfalls

1. Last commit June 2024: ESRS sector standards and the EU 'Omnibus' simplification changed the landscape since; verify against current law.

## Pair with Energy Skills

`ghg-emissions-calculator`, `energy-report-writer`
