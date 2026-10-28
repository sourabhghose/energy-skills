# COMTRADE fault detection

## Identity

- Name: COMTRADE fault detection
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/comtrade-accelerator
- Install doc: `RUNME.py` notebook (creates a multi-step job)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2024-01-26
- Maturity: stale (>18 months)
- Reviewed: 2026-10-28 against commit 092db50

## Use it for

- Distributed parsing of IEEE COMTRADE oscillography / fault records from relays and DFRs
- Fault-detection model training and a streaming (DLT) detection pipeline

## Do not use it for

- PMU / synchrophasor streams in C37.118 (not COMTRADE): needs a custom reader
- Outage reliability indices: use `reliability-metrics`

## Data

Sample COMTRADE files; uses `comtrade` and `comtradehandlers` (MIT) libraries.

## Deploy signals

Job created by `RUNME.py`; not otherwise documented.

## Smallest path

Clone as a Git folder, attach `RUNME` to a cluster and Run All.

## Pitfalls

1. Last commit January 2024: expect library and runtime drift (DLT → Lakeflow Declarative Pipelines naming, newer DBR).
2. RUNME-style accelerators assume classic clusters.

## Pair with Energy Skills

`equipment-pdm`, `reliability-metrics`
