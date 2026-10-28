---
name: wind-solar-performance
description: >-
  Wind turbine SCADA and solar PV performance analysis on Unity Catalog data. Wind: 10-minute SCADA
  filtering (curtailment, derate, stuck anemometer, icing), IEC 61400-12-1 air-density normalization
  and 0.5 m/s binned power curves vs warranted curve, AEP ratio, lost-production split (availability,
  external, curtailment, underperformance), time- vs energy-based availability, yaw misalignment. Solar:
  POA-based performance ratio (IEC 61724-1, temperature-corrected, NREL weather-corrected), clipping
  and curtailment separation, inverter availability, soiling screen, year-on-year degradation
  (RdTools-style). Curtailment is never counted as underperformance. SURFACES decisions (reference
  curve and density, availability basis, external downtime, PR method, clipping, downtime in PR,
  timestamp convention) with their effect before building. Run via scripts/perf_run.py (or
  wind_perf.py / solar_perf.py); do not hand-write the analysis. For ISO prices use
  iso-market-data; for equipment failure prediction use equipment-pdm.
category: "Renewables & Markets"
summary: Wind power-curve, availability and lost-production split; solar PR, clipping, soiling and degradation; curtailment always kept separate.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Wind & Solar Performance

## Overview

Answers the asset manager's two questions — *is the plant performing to spec, and where did the
energy go?* — from SCADA and monitoring data. For wind it builds density-normalized power curves,
compares them with the warranted curve, and splits lost energy into availability, external,
curtailment and underperformance. For solar it computes a POA-based performance ratio, separates
curtailment and clipping, and estimates soiling and degradation.

General agents get these wrong in repeatable ways: counting curtailment as underperformance,
computing "PR" from GHI, ignoring air density, using the wrong timestamp convention, or computing
availability without saying whether grid outages count. This skill makes those choices explicit.

## When to Use

- "Is turbine T07 underperforming against its warranted power curve?"
- "Split last year's lost production into availability, curtailment and performance losses."
- "What was our contractual availability, excluding grid outages?"
- "Do any turbines have a static yaw misalignment?"
- "What is the PR of the Mesa solar site for 2025, temperature corrected?"
- "How much energy did we lose to clipping vs ISO curtailment?"
- "What is the degradation rate of this array over three years?"
- "Is soiling costing us energy this summer?"

## Prerequisites

- **Compute**: Python-enabled compute (serverless or cluster) for the runner.
- **Inputs**: wind SCADA or PV monitoring tables in the schema of `references/data_schema.md`;
  for wind a warranted curve table (`ws_ms`, `power_kw`), rated power; for solar DC (kWp) and AC
  (kW) capacity and the module temperature coefficient `gamma_pmax_per_c`.
- **Status mapping**: vendor status codes mapped to the skill's state vocabulary (customer-specific;
  ask, never guess).

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from perf_run import preview_wind_table, build_wind_table

# STEP 1 — READ-ONLY. Shows flag shares, density range, AEP ratio and availability per option.
print(preview_wind_table("main.ops.scada_10min", rated_kw=2050,
                         warranted_curve_table="main.ops.warranted_curve"))

# STEP 2 — only after the user picks every decision.
out = build_wind_table("main.ops.scada_10min", "main.ops.wtg_perf_2025", rated_kw=2050,
                       warranted_curve_table="main.ops.warranted_curve",
                       timestamp_convention="interval_beginning", reference_curve="warranted",
                       ref_density=1.225, turbine_control="pitch", availability_basis="energy",
                       external_downtime="exclude_from_availability")
```

Solar: `preview_solar_table(...)` then `build_solar_table(..., pr_method=..., clipping_handling=...,
availability_in_pr=..., timestamp_convention=...)`. Pandas-only: `wind_perf.py`, `solar_perf.py`.

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write the power curve, PR or loss calculation, and do not pick a decision-point
value yourself. `preview_*` is READ-ONLY; `build_*` requires every decision and raises
`DecisionRequired` otherwise.

### Step 1: Map the data

Map SCADA / monitoring columns to `references/data_schema.md`. Map vendor status codes to states
with a UC lookup table supplied by the customer. Confirm the timezone and whether timestamps mark
the start or end of each interval (check the vendor export spec, or look at the first and last
timestamps of a day).

### Step 2: Preview

```python
print(preview_wind_table("main.ops.scada_10min", rated_kw=2050, warranted_curve_table="main.ops.wc"))
print(preview_solar_table("main.ops.pv_15min", dc_kwp=5000, ac_capacity_kw=4200, gamma_pmax_per_c=-0.0035))
```

Wind preview: flag shares, air density range, AEP ratio under each reference density, fleet
availability under each basis × external-downtime choice. Solar preview: daylight flag shares and
PR under every method × clipping × downtime option.

### Step 3: Ask the user for each decision

Present the Decision Points table with the preview numbers. Typical guidance: use the density the
warranted curve is quoted at; contractual availability usually excludes external downtime; NREL
weather-corrected PR for capacity tests.

### Step 4: Build confirmed

```python
out = build_solar_table("main.ops.pv_15min", "main.ops.pv_perf_2025", dc_kwp=5000, ac_capacity_kw=4200,
                        gamma_pmax_per_c=-0.0035, timestamp_convention="interval_ending",
                        pr_method="nrel_weather_corrected", clipping_handling="exclude_intervals",
                        availability_in_pr="include_downtime")
```

### Step 5: Report

Wind: power-curve table with complete/incomplete bins, AEP ratio, losses by category per turbine,
availability (with basis), yaw flags. Solar: PR (with method), monthly PR, lost energy by cause,
inverter availability, soiling screen, degradation with its 68% interval. Always state that nacelle
anemometry makes wind results relative, and that the soiling number is a screen.

## Decision Points

| Decision | Options | Governing reference | What changes |
|---|---|---|---|
| `timestamp_convention` | `interval_beginning`, `interval_ending` | Vendor export spec | Which day/month each interval lands in |
| `reference_curve` | `warranted`, `site_baseline` (+ `baseline_end`) | Turbine supply agreement / IEC 61400-12-1 | What "expected" power means |
| `ref_density` | `site_mean`, `iso_1.225`, or the warranted curve's density (kg/m3) | IEC 61400-12-1 | AEP ratio, a few % at warm or high sites |
| `turbine_control` | `pitch`, `stall` | IEC 61400-12-1 | Normalize wind speed vs power |
| `availability_basis` | `time`, `energy` | IEC 61400-26 | Availability value; contracts differ |
| `external_downtime` | `exclude_from_availability`, `count_as_unavailable` | IEC 61400-26 / contract | Grid outages in or out |
| `pr_method` | `iec_61724_uncorrected`, `temperature_corrected_stc`, `nrel_weather_corrected` | IEC 61724-1; NREL TP-5200-57991 | Seasonal temperature effect in PR |
| `clipping_handling` | `exclude_intervals`, `include` | Practice / contract | Health PR vs as-built PR |
| `availability_in_pr` | `include_downtime`, `exclude_downtime` | IEC 61724-1 vs O&M contracts | Whether inverter downtime lowers PR |

Curtailment handling is **not** a decision: it is always excluded from PR and underperformance and
reported as its own loss.

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|---|---|---|---|
| `rated_kw` | required | turbine nameplate | Range checks, curtailment detection, clip |
| `site_elevation_m` | `None` | m | Barometric pressure when `pressure_hpa` is missing |
| `mean_ws_for_aep` | measured mean | m/s | Rayleigh mean wind speed for AEP comparison |
| `dc_kwp`, `ac_capacity_kw` | required | kW | PR reference yield; clipping threshold |
| `gamma_pmax_per_c` | required for corrected PR | −0.0026 to −0.0045 | Temperature correction |
| `min_poa_wm2` | `50` | 20–200 | Daylight threshold for PR and availability |
| `t_ref_c` | irradiance-weighted period mean | degC | NREL weather-corrected PR reference (use typical-year value for contracts) |

## Expected Outputs

- Wind: `power_curve` (bin_ms, ws_mean, power_kw, n, complete), `losses` (per turbine: expected,
  actual, lost_availability, lost_external, lost_curtailment, performance_gap, kWh), `availability`,
  `yaw` (median offset, flag, loss band %), `flags`, `aep` (measured, reference, ratio), manifest.
- Solar: `pr`, `monthly_pr`, `inverter_availability`, `lost_energy` (curtailment, clipping,
  inverter fault kWh), `soiling`, `degradation` (Rd %/yr, 68% CI, pairs), manifest.

## Troubleshooting

| Problem | Cause | Solution |
|---|---|---|
| `must be timezone-aware` | Naive SCADA timestamps | Localize to the site timezone (or UTC) with the customer |
| `Unknown state values` | Vendor codes not mapped | Build the code → state table; do not guess |
| `IrradianceBasisError` | Only GHI available | Transpose to POA (e.g. pvlib) and state the model, or use a POA sensor |
| AEP ratio ~0.9 on a healthy turbine | Reference density mismatch | Use the warranted curve's density |
| Many incomplete bins | Short period or curtailment-heavy data | Extend the period; report incomplete bins |
| Degradation skipped | < 1 year + 30 days of data | Collect more data; do not extrapolate |
| PR > 1 | Irradiance sensor fault or wrong DC capacity | Check sensor and kWp before reporting |

## Guardrails

1. Never count curtailment or derating as underperformance.
2. Never compute PR from GHI.
3. Never choose a decision-point value on the user's behalf; present the preview and ask.
4. State that nacelle-anemometer power curves are relative, not IEC-certified.
5. Do not quote the soiling screen as a measured soiling loss.
6. Ask before running over multi-year, fleet-wide 1-second data; aggregate to 10-minute first.

## Related Skills

- `iso-market-data`: price the lost energy (curtailment vs underperformance) with nodal LMPs
- `equipment-pdm`: predict component failures behind availability losses
- `energy-semantic-builder`: publish availability, PR and capacity factor as metric views
- `energy-foundation-models`: time-series foundation models for production forecasting
- `energy-report-writer`: monthly asset performance reports

## References

- [IEC 61400-12-1 power performance](https://webstore.iec.ch/en/publication/68499)
- [IEC 61400-26-1 availability](https://webstore.iec.ch/en/publication/32855)
- [IEC 61724-1 PV performance monitoring](https://webstore.iec.ch/en/publication/65561)
- [NREL Weather-Corrected Performance Ratio (TP-5200-57991)](https://www.nrel.gov/docs/fy13osti/57991.pdf)
- [NREL RdTools](https://github.com/NREL/rdtools)
- [NREL OpenOA](https://github.com/NREL/OpenOA)
- [Kelmarsh open SCADA dataset (Zenodo)](https://zenodo.org/records/5841834)
- `references/` in this skill: `data_schema.md`, `wind_methods.md`, `solar_methods.md`
