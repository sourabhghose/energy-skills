# DAXS — explainable anomaly detection at scale

## Identity

- Name: DAXS — explainable anomaly detection at scale
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/daxs
- Install doc: `RUNME.md`, notebooks `00`–`03`
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-06-01
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 00954ec

## Use it for

- Training thousands of per-asset ECOD anomaly models (e.g. one per turbine) over a billion sensor readings at low cost, with per-sensor explanations
- Fleet-wide condition monitoring where labels are scarce

## Do not use it for

- Failure prediction with work-order labels and remaining useful life: use `equipment-pdm`
- Wind/solar underperformance vs. power curve or PR: use `wind-solar-performance`

## Data

Elevator predictive-maintenance dataset for the single-model notebook; synthetic multi-asset data for scale.

## Deploy signals

Not documented.

## Smallest path

Run `01_explainable.py` on a DBR ML cluster with `pyod` installed.

## Pitfalls

1. ECOD flags statistical outliers, not failures; curtailment, icing and maintenance states look anomalous — filter operating states first.

## Pair with Energy Skills

`equipment-pdm`, `wind-solar-performance`
