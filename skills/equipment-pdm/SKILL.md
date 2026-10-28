---
name: equipment-pdm
description: >-
  Predictive maintenance (PdM) and condition monitoring for rotating equipment: ESPs, gas
  compressors, pumps, gas turbines. Grounds PI / AVEVA historian tags through a reviewed tag
  map (unmapped tags excluded, units converted, digital states like "I/O Timeout" dropped),
  resamples with explicit gap limits (linear vs step for analog, hold for state tags), filters
  to steady running (start/stop transients excluded), builds features (rolling mean/std/slope,
  ESP current instability, motor temperature rise, ISO 10816-3 style vibration zones), labels
  failures from CMMS work orders by ISO 14224-style failure modes and a label horizon, splits
  leakage-safe (time with embargo / held-out assets), scores robust-z or isolation-forest
  anomalies, and evaluates alerts by lead time and false alarms per asset-month. Surfaces
  every choice for the user. Call scripts/pdm_run.py entrypoints; do not hand-write PdM code.
  For drilling NPT from reports use drilling-report-npt.
category: "Oil & Gas"
summary: Historian-grounded predictive maintenance for ESPs, compressors, pumps and turbines, with leakage-safe labels and false-alarm-aware alert evaluation.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Equipment Predictive Maintenance

## Overview

Turns historian time series plus maintenance work orders into an anomaly-based early-warning
model for rotating equipment, evaluated the way maintenance planners judge it: how many
failures it catches, how early, and how many false alarms each machine generates per month.
Shortcuts that produce good-looking but useless PdM models are blocked by construction:
guessed tag mappings, bridged historian outages, digital states coerced to zero,
start-up transients scored as faults, labels leaking across the train/test boundary, and
thresholds tuned on test data.

Outputs: `<prefix>_features` (with scores and labels), `<prefix>_alerts`, `<prefix>_evaluation`,
and a run manifest.

## When to Use

- "Can we predict ESP failures from our PI data a few days ahead?"
- "Which compressors are trending toward a vibration trip?"
- "Build an anomaly baseline for our pump fleet and tell me the false-alarm rate."
- "Our PdM model looks 95 % accurate. Is it leaking?"
- "Map these historian tags to equipment and measurements so we can model them."
- "What lead time do we get before motor failures, and at what alert threshold?"
- "Which assets are in ISO vibration zone C or D right now?"

## Prerequisites

- **Compute**: Python-enabled compute with Spark for writes; scikit-learn only for `isolation_forest`.
- **Historian table**: long format `tag, ts (UTC), value[, quality]` (see
  `references/historian_data.md`). Use Lakeflow Connect / PI integrations to land it.
- **Tag map table**: `tag, asset_id, equipment_class, measurement, unit`, curated from PI AF /
  point attributes.
- **Work orders table**: `asset_id, failure_mode, failure_start[, restored, wo_id]`, with CMMS
  codes mapped to the skill's ISO 14224-style codes.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from pdm_run import preview_pdm_options, sweep_alert_thresholds, build_confirmed_pdm, format_result

T = ("ops.pi.samples", "ops.pi.tag_map", "ops.cmms.work_orders")
# 1. READ-ONLY facts behind each decision
print(preview_pdm_options(*T, start="2026-01-01", end="2026-07-01"))
# 2. After the user chooses decisions 1-7: READ-ONLY threshold trade-off on the training period
D = dict(analog_interpolation="linear", running_definition="status_tag", transient_exclusion_minutes=60,
         failure_modes=["ELF", "BRD", "OHE"], label_horizon_hours=168, split_strategy="time",
         anomaly_method="robust_z")
print(sweep_alert_thresholds(*T, start="2026-01-01", end="2026-07-01", **D))
# 3. Build with the user's chosen threshold
res = build_confirmed_pdm(*T, "ops.pdm.esp_v1", start="2026-01-01", end="2026-07-01",
                          alert_threshold=6.0, **D)
print(format_result(res))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the entrypoints in `scripts/pdm_run.py` and report
their output. Do not write your own resampling, labelling, or splitting code, and do not
choose a decision value yourself.

### Step 1: Ground tags (preview)

`preview_pdm_options` joins the historian with the tag map and reports historian tags not in
the map (excluded), map tags with no samples, unknown units, and dropped digital-state or
bad-quality samples by tag. If the tag map is missing, help the user build one from PI AF
attributes and have them review it. Never map tags by name pattern alone.

### Step 2: Choose resampling

The preview's sampling-interval table (median / p95 / max gap per measurement) drives
`params={"freq": ..., "max_gap": ...}` and the `analog_interpolation` decision. State tags are
always held until the next change.

```python
from resample import resample_series   # fills a grid point only if bracketing samples are <= max_gap apart
```

### Step 3: Operating state

`running_definition` (`status_tag`, or `threshold` with `params={"threshold": {"measurement":
"motor_current", "min": 15}}`) and `transient_exclusion_minutes` define the **steady** rows.
Features and scores exist only on steady rows.

### Step 4: Features

Rolling mean / std / slope per signal (`params["window"]`, default `2h`), `motor_current_cv`,
`motor_temp_rise`, and `vibration_zone` when `params["vibration_zone_class"]` (for example
`group2_rigid`) or `params["site_vibration_limits"]` is given.

### Step 5: Labels and split

`failure_modes` selects qualifying work orders. Rows within `label_horizon_hours` before a
failure are positive, and outage rows are excluded. `split_strategy` applies a time embargo
equal to the horizon, a deterministic asset hold-out, or both. The preview shows the
pre-failure share for 72 / 168 / 336 h.

### Step 6: Baseline, threshold, build

`anomaly_method` is fitted on healthy steady training rows. `sweep_alert_thresholds` shows
recall, lead time, and false alarms per asset-month at score quantiles on the **training**
period. The user picks `alert_threshold`. `build_confirmed_pdm` evaluates on test rows only.

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `analog_interpolation` | `linear`, `step` | historian compression / step attribute | values between samples |
| `running_definition` | `status_tag`, `threshold` | operating procedure; ISO 13374 data manipulation | which rows are "running" |
| `transient_exclusion_minutes` | integer | OEM start-up guidance | rows excluded around starts/stops |
| `failure_modes` | subset of ELF, BRD, VIB, OHE, LOO, PLU, SER, FTS, STP, OTH | ISO 14224 taxonomy / CMMS coding | what counts as a failure |
| `label_horizon_hours` | integer (72 / 168 / 336 typical) | maintenance lead time; P-F interval | positive rows; embargo; cooldown |
| `split_strategy` | `time`, `asset`, `asset_and_time` | validation practice | leakage protection |
| `anomaly_method` | `robust_z`, `isolation_forest` | — | score model |
| `alert_threshold` | float (from sweep) | false-alarm budget | alerts, recall, false alarms |

All are keyword-only with no defaults. `None` raises `DecisionRequired`.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `start`, `end` | required | timestamps | historian read window |
| `params["freq"]` | `10min` | `1min`–`1h` | grid resolution |
| `params["max_gap"]` | `30min` | ≥ p95 sample gap | longest gap bridged |
| `params["window"]` | `2h` | — | rolling feature window |
| `params["vibration_zone_class"]` | `None` | `group1_rigid`, `group1_flexible`, `group2_rigid`, `group2_flexible` | ISO-style zones |
| `params["site_vibration_limits"]` | `None` | `(ab, bc, cd)` mm/s | overrides generic zones |
| `params["test_fraction"]` | `0.3` | 0.1–0.5 | test share (time or assets) |

## Expected Outputs

- `features`: `asset_id, ts, steady, <signal>_mean/_std/_slope_per_h, motor_current_cv,
  motor_temp_rise, vibration_zone, label, hours_to_failure, split, score`
- `alerts`: `asset_id, alert_ts, score` (deduplicated with a one-horizon cooldown)
- `evaluation`: `failures, caught, recall, median_lead_time_h, alerts, false_alarms,
  false_alarms_per_asset_month, precision, asset_months`
- `run_manifest`: all decisions, params, feature columns, evaluation

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `historian timestamps must be timezone-aware` | naive local timestamps | convert to UTC at ingestion |
| Many unmapped tags | tag map incomplete | extend from PI AF; review before use |
| Features mostly NaN | `max_gap` below the sampling interval, or no steady rows | raise `max_gap`; check `running_definition` |
| `no healthy steady training rows` | split leaves no training data, or all labelled | widen the window; check failure modes |
| Recall 0 with 0 test failures | failures fall in train or embargo | extend `end`; use `asset` split |
| Huge false-alarm rate | threshold too low; transients scored | sweep higher quantiles; raise transient exclusion |

## Guardrails

1. Never map tags, choose failure modes, or set thresholds on the user's behalf.
2. Never tune the alert threshold on test data. Use `sweep_alert_thresholds` (training period).
3. Always report false alarms per asset-month and the number of test failures next to recall.
4. Treat equipment data as operator-confidential. Share aggregates, not raw historian extracts.
5. Confirm before reading more than ~1 billion historian rows (cost). Narrow `start`/`end` first.
6. Don't retry failing calls more than 3 times; report the error.

## Related Skills

- `drilling-report-npt`: rig-equipment NPT context for drilling-rig equipment
- `wind-solar-performance`: turbine performance (power curve) rather than component health
- `energy-foundation-models`: time-series foundation models as an alternative anomaly scorer
- `unit-guard`: unit conversions beyond the built-in table
- `energy-semantic-builder`: publish alert and availability KPIs as metric views
- `skill-eval`: benchmark this skill (see `eval/`)

## References

- `references/historian_data.md`: input contracts, compression, digital states, units
- `references/operating_states_features.md`: steady state, ESP signatures, vibration zones
- `references/labels_validation.md`: ISO 14224 labels, embargo splits, alert metrics
- [ISO 13374-1](https://www.iso.org/search.html?q=ISO%2013374-1): condition-monitoring data processing
- [ISO 14224](https://www.iso.org/search.html?q=ISO%2014224): reliability and maintenance data taxonomy
- [ISO 20816-3](https://www.iso.org/search.html?q=ISO%2020816-3): machine vibration evaluation
