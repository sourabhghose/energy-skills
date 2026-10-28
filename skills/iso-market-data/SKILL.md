---
name: iso-market-data
description: >-
  ISO/RTO electricity market prices (CAISO, ERCOT, PJM, MISO, NYISO, ISO-NE, SPP) on Unity Catalog:
  normalizes day-ahead and real-time LMP/SPP data to UTC intervals (hour-ending labels, DST repeated
  and missing hours, interval-beginning vs interval-ending, MISO EST), checks LMP = energy + congestion
  + loss with each ISO's sign convention (NYISO congestion sign, CAISO GHG, ERCOT SPP adders),
  time-weighted hourly prices, on-peak/off-peak blocks (5x16, 2x16, 7x8, wrap) with NERC holidays,
  node-minus-hub basis, DA-RT spread, negative-price flags, and two-settlement revenue for generators
  and batteries. Grounds pricing nodes in the data, never substitutes names. SURFACES decisions
  (timestamp convention, hourly aggregation, peak definition and timezone, price bounds, settlement
  method) with their effect before building. Run via scripts/iso_run.py or iso_entry.py; do not
  hand-write timestamp or settlement logic. For plant performance losses use
  wind-solar-performance; for load forecasting use load-forecaster.
category: "Renewables & Markets"
summary: DST-safe, convention-aware ISO price normalization, peak blocks with NERC holidays, basis, DA-RT spread and two-settlement revenue.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# ISO Market Data

## Overview

Loads and analyzes US wholesale electricity prices without the classic timestamp and settlement
mistakes. Every price row is normalized to `interval_start_utc` / `interval_end_utc` with an explicit
interval length; hour-ending local labels, the repeated fall-back hour, the missing spring-forward
hour and MISO's year-round EST are handled. On top of that it computes time-weighted hourly prices,
peak-block statistics, basis to a hub, DA-RT spreads, and interval-level settlement revenue.

General agents misalign DA and RT by an interval, drop or double the DST hour, average 5-minute
prices with a simple mean over missing intervals, apply PJM's component sign to NYISO, treat ERCOT
SPP as LMP, invent pricing-node names, or multiply hourly average price by hourly MWh. This skill
makes conventions explicit and checks them against the data.

## When to Use

- "Load a year of ERCOT RT settlement point prices for HB_NORTH and our wind node and give me
  on-peak and off-peak averages."
- "What is the basis between our solar node and the hub, by month?"
- "Compute DA-RT spreads at these PJM pnodes for the summer."
- "How often were prices negative at our node last spring?"
- "What would our battery have earned in CAISO real time last month?"
- "Settle our generator's day-ahead award and real-time deviations."
- "Why don't PJM and NYISO congestion components look comparable?"
- "Our hourly RT price doesn't match the ISO's hourly file; why?"

## Prerequisites

- **Compute**: Python-enabled compute for the runner.
- **Inputs**: a raw price table (bronze) with `node`, `lmp` and either a UTC timestamp column or
  `date` + `hour_ending` (+ `interval`, + repeated-hour flag). Optional `energy`, `congestion`,
  `loss`, `ghg`.
- **Settlement**: meter data (`node`, `interval_start_utc`, `mwh`; charging negative) and DA awards
  (`node`, `interval_start_utc`, `mw`).
- **Fetching** (optional, network): `gridstatus` library or ISO APIs (`references/data_sources.md`).

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from iso_run import preview_table, build_table

# STEP 1 — READ-ONLY: registry conventions, timestamp evidence, DST days, node grounding, peak averages.
print(preview_table("main.mkt.ercot_rt_spp_raw", iso="ERCOT", market="RT", time_format="hour_ending",
                    repeated_col="dst_flag", interval_col="interval", nodes=["HB_NORTH", "RN_WIND1"]))

# STEP 2 — only after the user confirms every decision.
out = build_table("main.mkt.ercot_rt_spp_raw", "main.mkt.ercot_rt_2025", iso="ERCOT", market="RT",
                  time_format="hour_ending", repeated_col="dst_flag", interval_col="interval",
                  nodes=["RN_WIND1"], hub="HB_NORTH", hourly_aggregation="time_weighted",
                  peak_definition="5x16", peak_timezone="America/Chicago",
                  price_floor=-251.0, price_cap=5000.0)
```

Pandas-only: `from iso_entry import normalize_prices, preview_market_data,
build_confirmed_price_analysis, build_confirmed_settlement`.

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write timestamp conversion, hourly averaging or settlement arithmetic, and do not
pick a decision-point value yourself. `preview_*` is READ-ONLY; `build_confirmed_*` raises
`DecisionRequired` for any missing decision.

### Step 1: Land the raw data

Load raw ISO files (or `fetch_with_gridstatus`) into a bronze UC table unchanged. Keep the ISO's own
column names for timestamps and DST flags; rename only `node` and `lmp` (and components).

### Step 2: Preview

```python
print(preview_table("main.mkt.pjm_rt_5min_raw", iso="PJM", market="RT", time_format="utc_column",
                    ts_col="datetime_beginning_utc", nodes=["WESTERN HUB", "MY_PNODE"]))
```

Shows the registry entry (marked `verify_before_use`), evidence from the data for interval
beginning vs ending, incomplete node-days and 23/25-hour days, which component sign convention
reconciles, negative-price share, price range, requested nodes found/missing (with suggestions),
and the average LMP under every peak block.

### Step 3: Resolve identity and conventions

Missing nodes: ask the user which of the suggested names (if any) is intended; never substitute.
Timestamp convention: confirm against the report spec when the evidence and the registry disagree.

### Step 4: Ask for each decision and build

```python
out = build_table(..., hourly_aggregation="time_weighted", peak_definition="5x16",
                  peak_timezone="America/New_York", price_floor=-150.0, price_cap=3700.0)
```

Writes `<prefix>_intervals` (normalized, flagged), `<prefix>_hourly`, `<prefix>_peak`,
`<prefix>_basis` (when a hub is given) and a `<prefix>_manifest` row.

### Step 5: Settlement (optional)

```python
from iso_entry import normalize_prices, build_confirmed_settlement
rt = normalize_prices(rt_raw, iso="CAISO", market="RT", time_format="utc_column",
                      ts_col="INTERVALSTARTTIME_GMT", source_timestamp_convention="interval_beginning")
rev = build_confirmed_settlement(rt_meter=meter, settlement="rt_only", rt_prices=rt)
```

### Step 6: Report

Report node, market, convention used, peak block and timezone, incomplete hours, component
mismatches, negative-price share, and the manifest. State that the conventions registry entries are
`verify_before_use`.

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `nodes` | node names present in the data | ISO node lists | What is analysed; missing names raise |
| `source_timestamp_convention` | `interval_beginning`, `interval_ending` (UTC-column input) | ISO report spec | Every interval shifts by one length; DA/RT alignment |
| `hourly_aggregation` | `time_weighted`, `energy_weighted` | Settlement practice | Hourly price definition |
| `peak_definition` | `5x16`, `2x16`, `7x8`, `wrap`, `7x24` | Contract / ICE product spec | Which hours enter the block average |
| `peak_timezone` | IANA timezone of the product definition | Contract | Block boundaries (MISO EST vs EPT) |
| `price_floor`, `price_cap` | $/MWh bounds | ISO offer floor/cap in force | Outlier flags (never drops) |
| `settlement` | `two_settlement`, `rt_only`, `da_only` | ISO tariff | Revenue formula |

Hour-ending inputs are interval-ending by definition, so `source_timestamp_convention` applies only
to `time_format="utc_column"`.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `iso` | required | `CAISO`, `ERCOT`, `PJM`, `MISO`, `NYISO`, `ISONE`, `SPP` | Conventions registry entry |
| `market` | required | `DA`, `RT` | Default interval length |
| `time_format` | required | `utc_column`, `hour_ending` | Timestamp parser |
| `repeated_col` | `None` | column name | Repeated fall-back hour flag (ERCOT `DSTFlag`) |
| `interval_col` | `None` | column name | Sub-hourly interval number within the hour |
| `interval_minutes` | registry | 5, 15, 60 | Override the registry interval length |
| `hub` | `None` | node name | Enables basis |
| `mwh_col` | `None` | column name | Needed for `energy_weighted` |

## Expected Outputs

- `<prefix>_intervals`: node, interval_start_utc, interval_end_utc, interval_minutes, lmp,
  components, component_residual, component_mismatch, flag_negative, flag_outside_bounds
- `<prefix>_hourly`: node, hour_start_utc, lmp, covered_minutes, n_intervals, incomplete
- `<prefix>_peak`: node, avg, min, max, hours, negative_share, block, peak_tz
- `<prefix>_basis`: node, interval_start_utc, lmp, hub_lmp, basis
- Settlement: interval DA/RT revenue, deviation MWh, totals per node
- Manifest: decisions, registry status, row counts, time range, flag counts

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `duplicate intervals ... repeated DST hour is not flagged` | Fall-back hour present twice without a flag | Pass `repeated_col` (ERCOT DSTFlag) or keep ISO-NE `02X` labels |
| `do not exist ... spring-forward gap` | HE3 present on spring DST day | Source data mislabelled; check the ISO file |
| `Nodes not in the data` | Name typo or retired node | Use a suggested name only after the user confirms |
| Component mismatches everywhere | Wrong ISO sign convention or missing GHG column | Read `component_fit` in the preview |
| Hourly RT ≠ ISO hourly file | Missing intervals or simple mean | Check `covered_minutes`; use time-weighted |
| DA and RT off by one interval | Different conventions across reports | Confirm `source_timestamp_convention` per report |

## Guardrails

1. Never substitute a pricing node, hub or zone name; ask.
2. Never drop negative or capped prices; flag them.
3. Never compute settlement from hourly-average prices when interval data exists.
4. Treat ERCOT RT SPP (with adders) and SCED LMPs as different series.
5. State that the conventions registry is `verify_before_use` for the report used.
6. Do not fetch data in tests or without the user's go-ahead; some APIs need keys and have quotas.

## Related Skills

- `wind-solar-performance`: price curtailment and underperformance losses at the node
- `load-forecaster`: load forecasts that drive price scenarios
- `energy-foundation-models`: time-series foundation models for price forecasting
- `energy-semantic-builder`: basis, spread and capture-price KPIs as metric views
- `unit-guard`: MW vs MWh and interval-energy conversions

## References

- [FERC Order 825](https://www.ferc.gov/media/order-no-825)
- [CAISO OASIS](https://www.caiso.com/library/oasis-interface-specification)
- [ERCOT data products](https://www.ercot.com/mp/data-products)
- [PJM Data Miner 2](https://dataminer2.pjm.com/)
- [MISO market reports](https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/)
- [NYISO Market Participant User's Guide](https://www.nyiso.com/documents/20142/3625950/mpug.pdf)
- [ISO Express (ISO-NE)](https://www.iso-ne.com/isoexpress/)
- [SPP Integrated Marketplace](https://marketplace.spp.org/groups/integrated-marketplace)
- [gridstatus](https://github.com/gridstatus/gridstatus)
- `references/` in this skill: `iso_conventions.md`, `peak_definitions.md`, `settlement.md`, `data_sources.md`
