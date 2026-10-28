---
name: ami-interval-analytics
description: >-
  AMI smart-meter interval data VEE (validation, estimation, editing) on Unity Catalog. Turns
  raw head-end or MDM interval reads (kWh per 5/15/30/60 min) or cumulative register reads
  into a validated, DST-safe interval table with per-interval quality codes and a per-meter
  VEE summary. Resolves the repeated fall-back hour and the spring-forward gap,
  interval-ending vs interval-beginning labels, register rollovers and resets, duplicates,
  missing intervals, spikes above service capacity, negative reads (net-metering export vs
  error), flatlines, extended zeros, and upstream estimated reads. Estimates gaps (linear,
  like-day, register-prorated) only within limits the user chooses. Also handles register
  reconciliation and sustained-drop (tamper/vacancy) indicators. Run by calling the vetted
  entrypoints in scripts/ami_run.py; do not hand-write VEE SQL. For load forecasting use
  load-forecaster; for de-identifying meter data use grid-data-guard.
category: "Power & Utilities"
summary: Validate, estimate and quality-flag smart-meter interval data, safely across DST, with user-chosen VEE rules.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# AMI Interval Analytics: DST-Safe VEE for Smart-Meter Data

## Overview

Smart-meter (AMI) interval data reaches the lakehouse with clock, unit and quality problems
that a general coding agent doesn't notice: an hour of energy disappears on the fall-back
Sunday, register reads get summed as if they were interval kWh, negative export on solar
homes gets "cleaned" away, and estimated reads get mixed in with actual ones. This skill
runs a utility-style **VEE** (validation, estimation, editing) pass. Its output is:

- `<output>`: one row per meter × interval on a complete UTC grid, with `raw_kwh`, `kwh`
  (validated or estimated), `quality_code`, `flags`, and local time with its UTC offset
- `<output>_summary`: per-meter completeness (against DST-aware expected counts), quality-code
  counts, and flag counts
- `<output>_manifest`: the run manifest (inputs, every decision, skill version)

## When to Use

- "Clean up our AMI interval reads before we compute monthly usage / load profiles."
- "Our November totals are off by an hour of usage. Check the DST handling."
- "Convert these register (dial) reads into 15-minute interval kWh."
- "Flag meters with spikes, stuck registers, or long zero runs, and estimate short gaps."
- "Which meters are below 98 % complete, and how much of their usage is estimated?"
- "Reconcile interval sums against daily register reads."
- "Find premises whose consumption dropped suddenly (possible tamper or vacancy)."
- "Prepare Green Button / ESPI interval data for analytics."

## Prerequisites

- **Compute:** Python-enabled compute (serverless or a cluster), not a SQL-only warehouse.
  The build runs the tested core per meter with `groupBy(meter).applyInPandas`.
- **Input:** a UC table with a meter id, a timestamp, and a value column (kWh per interval,
  or cumulative register kWh). An optional quality-code column (`A`/`E`) is used if present.
- **Output:** `CREATE TABLE` on the target schema.

## Quick Start

```python
import sys
sys.path.append('<this-skill-dir>/scripts')
from ami_run import preview_vee_options, build_confirmed_vee

# STEP 1: READ-ONLY. Profiles a sample of meters; builds nothing. Show the output to the user.
print(preview_vee_options("main.ami.interval_reads", meter_col="meter_id", ts_col="read_ts",
                          value_col="kwh", quality_col="read_quality",
                          source_timezone="America/Chicago"))

# STEP 2: ONLY after the user has answered every decision in the preview.
print(build_confirmed_vee("main.ami.interval_reads", "main.ami.interval_vee",
                          interval_minutes=15, source_timezone="America/Chicago",
                          timestamp_basis="local_naive", interval_convention="ending",
                          read_type="interval", net_metering_policy="negative_is_export",
                          linear_max_gap_intervals=4, long_gap_method="like_day",
                          max_estimation_gap_hours=72, spike_max_kw=48,
                          meter_col="meter_id", ts_col="read_ts", value_col="kwh",
                          quality_col="read_quality"))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call `preview_vee_options` and then `build_confirmed_vee`,
and report their output. Do not write your own VEE SQL or pandas, and do not pick a
decision-point value yourself. The steps below describe what the entrypoints do so you can
explain them. They are not a recipe to re-code.

### Step 1: Preview (read-only)

`preview_vee_options` samples up to 200 meters and reports what it detects (interval length,
read type, timezone awareness, duplicates, negatives, zeros), a histogram of gap lengths,
how many intervals each linear-gap limit would estimate, spike counts at several kW
ceilings, and DST fall-back/spring-forward anomalies. It ends with the list of decisions.
**Show the preview to the user and ask them to decide.**

### Step 2: Place every read in time

Labels are localized **in record order** (the first `01:xx` on fall-back Sunday is DST, the
second is standard time), converted to UTC, and only then shifted back one interval if they
are interval-ending. Labels in the spring-forward gap are flagged and dropped. See
`references/dst_and_interval_conventions.md`.

### Step 3: Register reads → interval kWh (if `read_type='register'`)

Consecutive deltas become interval kWh. A drop from near the dial capacity to near zero is a
rollover, and the delta is corrected by `register_rollover_kwh`. Any other drop is a
reset/exchange and is invalidated. A delta spanning missing reads is kept to prorate the gap.

### Step 4: Grid, deduplicate, validate

Each meter is reindexed onto a complete UTC grid, so missing intervals become explicit rows.
Duplicates are collapsed; conflicting duplicates are invalidated. Value rules (spike,
negative, flatline, extended zero, source estimated) set `flag_*`. See
`references/vee_rules.md`.

### Step 5: Estimate within the confirmed limits

Linear interpolation runs for short gaps, like-day estimation for longer ones up to the cap,
and register proration to conserve metered energy. Everything else stays `MISSING`.

### Step 6: Write and report

The runner writes the validated table with column comments, the summary, and the manifest,
and prints the decisions and per-meter summary. Report completeness and estimated share, and
point out meters that need a field order.

## Decision Points

| Decision | Options | Governing practice | What changes |
|----------|---------|--------------------|--------------|
| `interval_minutes` | 5, 15, 30, 60 (preview detects) | Meter channel config | Grid and expected counts |
| `source_timezone` | IANA zone | Meter clock setting | Where DST transitions fall |
| `timestamp_basis` | `local_naive`, `utc`, `offset_aware` | Head-end export format | Whether DST resolution is needed |
| `interval_convention` | `ending`, `beginning` | Head-end vs MDM convention | One-interval shift of every read |
| `read_type` | `interval`, `register` (+ `register_rollover_kwh`) | Channel type | Differencing and rollover handling |
| `net_metering_policy` | `negative_is_export`, `negative_is_error`, `per_meter` (+ `net_metered_meter_ids`) | Tariff / DER interconnection records | Whether negatives are kept; mixed fleets need `per_meter` |
| `linear_max_gap_intervals` | e.g. 4 (1 h at 15 min), 8 | Utility VEE rulebook | Which gaps get straight lines |
| `long_gap_method` | `like_day`, `leave_missing` | Utility VEE rulebook | Whether long gaps are estimated |
| `max_estimation_gap_hours` | e.g. 24, 72, 168 | Billing estimation limits | Longest gap that may be estimated |
| `spike_max_kw` | service capacity, e.g. 48 kW for 200 A at 240 V | Service size / transformer rating | What counts as impossible demand |

## Key Parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `flatline_min_hours` | `4.0` | Identical non-zero run length that invalidates (raise for 0.1 kWh-resolution meters) |
| `extended_zero_hours` | `24.0` | Zero run length that is flagged (not invalidated) |
| `like_days` / `like_day_lookback_days` | `4` / `21` | Like-day estimator window |
| `reconciliation_tolerance_pct` | `1.0` | Register vs interval-sum tolerance |
| `sample_meters` (preview) | `200` | Meters profiled by the preview |

## Expected Outputs

- Validated interval table with columns `meter_id, interval_start_utc, interval_start_local,
  local_date, raw_kwh, kwh, quality_code, flags, gap_length_intervals`
- Per-meter summary: quality-code counts, flag counts, `intervals_expected_full_days`
  (92/96/100 per day, DST-aware), `actual_pct`, `total_kwh`
- Run manifest JSON, with a printed readout of decisions and the first 20 meters

## Common Recipes

### Recipe: Register reconciliation

```python
from ami_estimate import reconcile_to_register   # intervals: interval_start_utc, kwh
rec = reconcile_to_register(intervals_pdf, register_pdf, tolerance_pct=1.0)
rec[~rec["within_tolerance"]]
```

### Recipe: Sustained-drop indicator (tamper / vacancy screening)

```python
from ami_estimate import consumption_drop_indicator
consumption_drop_indicator(meter_pdf, "America/Chicago")   # ratio of last 30 d vs prior 90 d
```

This is an **indicator for field review**, not evidence of theft. Never label a customer
from it.

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `DecisionRequired` | A decision was not given | Ask the user; never fill it in yourself |
| 4 "missing" intervals every March | Grid built in local time | Use this skill; it grids in UTC and counts 92 intervals on that day |
| Fall-back day is 1 h short or long | `drop_duplicates` on local labels | Keep record order; this skill resolves the repeat by order |
| Many `dst_ambiguous_single` flags | Source dropped one copy of the repeated hour | Ask whether the export has offsets; use `offset_aware` if so |
| Many flatlines | Coarse value resolution (0.1 kWh) | Raise `flatline_min_hours` after showing the user |
| Spikes on commercial meters | `spike_max_kw` set for residential service | Use per-class ceilings or run per class |
| Build fails on a SQL warehouse | Needs Spark | Select serverless Python compute |

## Guardrails

1. Never pick a decision value; the preview exists so the user can choose.
2. Never present estimated intervals as actuals. Always report the estimated share.
3. Never drop negative reads without the user's net-metering decision. In a mixed fleet, use
   `per_meter` with the premise/DER table, not a single fleet-wide policy.
4. Don't estimate past `max_estimation_gap_hours`; long outages need field action.
5. Treat meter-level data as customer data: share aggregates, or use grid-data-guard.
6. Retry at most 3 times; ask before running on more than ~10 000 meters for the first time.

## Related Skills

- `load-forecaster`: forecasting and weather normalization on the validated output
- `grid-data-guard`: de-identify or aggregate meter data before sharing
- `energy-semantic-builder`: governed KPIs (usage, load factor) on top of the VEE table
- `unit-guard`: kWh/MWh/kW conversions
- `reliability-metrics`: outage-derived reliability indices (meter last-gasp events)

## Bundled Resources

- `scripts/ami_run.py`: Databricks entrypoints (`preview_vee_options`, `build_confirmed_vee`)
- `scripts/ami_pipeline.py`: per-meter VEE pipeline, summary, preview profile
- `scripts/ami_time.py`: DST-safe localization, interval conventions, expected counts
- `scripts/ami_validate.py`: register differencing, gridding, validation rules
- `scripts/ami_estimate.py`: estimation, register proration, reconciliation, drop indicator
- `scripts/ami_decisions.py`: decision registry, `DecisionRequired`, config, manifest
- `scripts/_uc.py`: UC identifier validation, reads, writes
- `references/vee_rules.md`, `references/dst_and_interval_conventions.md`,
  `references/data_standards.md`

## References

- [AEIC](https://aeic.org/): VEE guidelines (Meter & Service Technical Committee)
- [IESO Smart Metering Entity](https://www.ieso.ca/en/Sector-Participants/Smart-Metering-Entity): Ontario MDM/R VEE standard
- [Green Button Alliance](https://www.greenbuttonalliance.org/) and [NAESB REQ.21 ESPI](https://www.naesb.org/ESPI_Standards.asp)
- [ANSI C12 series (NEMA)](https://www.nema.org/): meter data tables and accuracy classes
- [IANA Time Zone Database](https://www.iana.org/time-zones)
