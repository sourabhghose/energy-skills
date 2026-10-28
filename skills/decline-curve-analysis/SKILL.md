---
name: decline-curve-analysis
description: >-
  Decline curve analysis (DCA) for oil and gas wells: Arps exponential, hyperbolic, and
  harmonic fits and the modified hyperbolic with a terminal decline, on monthly or daily
  production in Unity Catalog. Bounded b-factor fits on log rate, calendar-day vs
  producing-day rates, shut-in and outlier handling, peak (start-of-decline) selection, EUR to
  an economic limit or max life, nominal vs secant vs tangent effective decline conversions,
  plausibility flags (b at bound, b > 2, no terminal decline), monthly forecasts, and
  P10/P50/P90 type curves using the PRMS convention, with lateral-length normalization.
  Surfaces each engineering decision with its EUR effect before building. For boe roll-ups
  use unit-guard; for well identity and header mapping use osdu-ppdm-mapper.
category: "Oil & Gas"
summary: Bounded Arps / modified-hyperbolic decline fits, EUR, forecasts, and PRMS P10/P50/P90 type curves, with b-factor, terminal decline, and rate basis chosen by the engineer.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Decline Curve Analysis: Bounded, Reproducible EURs

## Overview

Turns well production history into decline parameters, forecasts, and EURs that a reserves
engineer can defend. A general coding agent typically fits an unbounded hyperbolic with
`curve_fit` on arithmetic rates, through the cleanup ramp and the downtime months, and
reports an EUR implied by b ≈ 2 for 50 years. This skill encodes the discipline instead:

- fit from the start of decline, on log rate
- choose the rate basis explicitly (calendar-day or producing-day)
- keep b inside engineer-chosen bounds, and switch to a terminal decline
- stop at an economic limit
- flag implausible results
- label percentiles the PRMS way

Outputs: `<prefix>_fits` (one row per well: qi, Di in three conventions, b, R², EUR, flags),
`<prefix>_forecast` (monthly volumes), optional `<prefix>_type_curve`, and a manifest of
every decision.

## When to Use

- "Fit decline curves and give me EURs for these 200 Permian wells."
- "What's the remaining reserves forecast for this lease if the economic limit is 5 bbl/d?"
- "Build a P10/P50/P90 type curve for the 2023 Wolfcamp A wells, normalized to 10,000 ft."
- "This EUR looks too high. Is the b-factor reasonable?"
- "Convert our 65% first-year decline into the nominal Di for the hyperbolic equation."
- "Forecast monthly gas for the next 30 years for the budget."
- "Compare EUR with and without a terminal decline."

## Prerequisites

- **Compute**: Python-enabled compute (serverless or cluster), not a SQL-only warehouse.
  The core needs numpy and pandas only.
- **Inputs**: a UC table with one row per well per period (well id, period date, volume
  for one stream) and optionally a days-on column and a lateral-length column. One stream
  per run (oil, gas, or water) in a stated unit.
- **Permissions**: `SELECT` on the source; `CREATE TABLE` on the target schema.
- **Scale**: fits run on the driver in pandas (≈ 5–15 ms per well). For more than ~20,000
  wells, run in batches with `wells=[...]`.

## Quick Start

```python
import sys
sys.path.append("<this-skill-dir>/scripts")
from dca_run import preview_dca_options, build_confirmed_dca

# STEP 1: READ-ONLY. Shows ramp, shut-ins, downtime, and an EUR sensitivity grid.
print(preview_dca_options("main.upstream.monthly_prod", well_col="api14", date_col="prod_month",
                          volume_col="oil_bbl", volume_unit="bbl", period="monthly",
                          days_on_col="days_on", max_wells=10))

# STEP 2: ONLY after the user chose every decision. None has a default.
print(build_confirmed_dca("main.upstream.monthly_prod", "main.upstream.dca_oil_2026q3",
      well_col="api14", date_col="prod_month", volume_col="oil_bbl", volume_unit="bbl",
      period="monthly", days_on_col="days_on",
      rate_basis="producing_day", decline_start="peak", outlier_method="mad",
      b_bounds=(0.0, 1.5), terminal_decline_eff=0.08, econ_limit_rate=5.0, max_life_years=50))
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the entrypoints in `scripts/dca_run.py` and report
their output. Do not write your own `curve_fit`, do not pick a b-bound, terminal decline,
rate basis, economic limit, or life, and do not relabel percentiles.

### Step 1: Identify the stream and its unit

Confirm the well id, date, and volume columns, and the **volume unit** (`bbl`, `Mcf`, `MMcf`,
`m3`, `Sm3`). Fit each stream separately and never fit boe. If the unit isn't clear from
the column name or metadata, ask.

### Step 2: Preview (read-only)

`preview_dca_options` reports, per sampled well:

- periods before peak (the cleanup ramp)
- shut-in and zero periods
- periods with downtime
- peak rate on a calendar-day and a producing-day basis
- cumulative production to date
- an **EUR sensitivity grid** across b_max ∈ {1.0, 1.5, 2.0} × terminal decline ∈ {none,
  6%, 10%}, using a clearly labelled provisional economic limit

Show it to the user.

### Step 3: Ask the user for each decision

Present the Decision Points table with the preview's numbers ("on these wells, b ≤ 1.5 with
an 8% terminal decline gives an EUR about 15% lower than unbounded"). Record the answers.
Reserves policy often fixes b_max and D_min, so ask whether one exists.

### Step 4: Build

Call `build_confirmed_dca(...)` with every decision. A missing decision raises
`DecisionRequired`. That is expected: ask the user, then call again.

### Step 5: Review flags

Report total EUR and each flagged well. Flags mean "a reviewer must look", not "wrong":

- `b_at_upper_bound`: the data wants a higher b. The bound is binding, so check the flow
  regime.
- `b_above_2`: physically implausible for a long-term forecast.
- `hyperbolic_b_ge_1_without_terminal_decline`: EUR is controlled by the economic limit alone.
- `poor_fit_r2_log`, `few_points`: the fit is not reliable.
- `eur_exceeds_15_years_at_peak_rate`: EUR is out of proportion to the well's peak rate.
- `already_below_economic_limit`: the forecast adds nothing.
- `eur_truncated_by_max_life`: EUR was cut off by max life before reaching the economic limit.

### Step 6: Type curve (optional)

```python
from dca_run import build_confirmed_type_curve
print(build_confirmed_type_curve("main.upstream.monthly_prod", "main.upstream.wca_tc",
      well_col="api14", date_col="prod_month", volume_col="oil_bbl", volume_unit="bbl",
      days_on_col="days_on", lateral_col="lateral_ft",
      normalization="lateral_length", reference_lateral_ft=10_000,
      rate_basis="producing_day", decline_start="peak", outlier_method="mad",
      b_bounds=(0.0, 1.5), terminal_decline_eff=0.08, econ_limit_rate=5.0, max_life_years=50,
      min_wells=5))
```

P10 = high case (90th percentile) and P90 = low case. Months with fewer than `min_wells`
wells are truncated to avoid survivor bias.

### Step 7: Report

Give EURs with units and decisions, for example: *"P50 EUR 412 Mbbl per 10,000 ft
(producing-day rates, b ≤ 1.5, D_min 8%, 5 bbl/d limit, 50-yr life; 37 wells, 3 excluded
for missing lateral)."* For boe totals, call unit-guard's `boe_from_gas` with the user's
chosen method.

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `rate_basis` | `calendar_day`, `producing_day` | SPEE Monograph 4 | Downtime months bias b and Di; forecast uptime assumption |
| `decline_start` | `peak`, `first_production` | SPEE practice | Fitting the ramp distorts qi, Di, b |
| `outlier_method` | `none`, `mad` | — | Workover / flush spikes inflate qi or b |
| `b_bounds` | e.g. `(0, 1.0)`, `(0, 1.5)`, `(0, 2.0)`, or fixed `(b, b)` | Arps 1945; company reserves policy | Upper bound often moves EUR by 10–40% |
| `terminal_decline_eff` | e.g. `0.05`–`0.10`, or `"none"` explicitly | Robertson 1988; SPEE | Caps the long tail; large effect when b > 1 |
| `econ_limit_rate` | per day in the stream's unit | lease economics | Where the forecast stops |
| `max_life_years` | from first production | reserves policy / SEC | Truncates long tails |
| `normalization` (type curve) | `none`, `lateral_length` (+ `reference_lateral_ft`) | play practice | Every percentile |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `period` | required | `monthly`, `daily` | Calendar days per period; type curves need monthly |
| `volume_unit` | required | `bbl`, `Mcf`, `MMcf`, `m3`, `Sm3` | Labels every output; boe is refused for fitting |
| `days_on_col` | `None` | column name | Required for `producing_day` |
| `min_wells` (type curve) | `5` | ≥ 3 | Survivor-bias truncation |
| `max_wells` (preview) | `10` | 1–50 | Sample size for the preview |
| `wells` | all | list of ids | Restrict or batch |

## Expected Outputs

- `<prefix>_fits`: well_id, status, volume_unit, qi_per_day, di_nominal_per_yr, di_secant_eff,
  di_tangent_eff, b, d_lim_nominal_per_yr, r2_log, n_points, peak_rate_per_day, cum_to_date,
  remaining, eur, end_reason, first_production, decline_start, exclusions_json, flags
- `<prefix>_forecast`: well_id, month_index, t_start_years, volume, rate_per_day, volume_unit
- `<prefix>_type_curve`: month_index, n_wells, p10_high_rate, p50_rate, p90_low_rate, mean_rate
- `<prefix>_manifest` (and `<prefix>_type_curve_manifest`): inputs, every decision, EUR percentiles

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `DecisionRequired` | A decision wasn't passed | Ask the user; pass it explicitly |
| `duplicate periods for one well` | Multiple rows per month (e.g. per completion) | Aggregate to well-month upstream |
| `needs a days_on column` | `producing_day` without days-on | Use `calendar_day`, or join days-on |
| Many `b_at_upper_bound` | Transient linear flow dominates the history | Discuss b policy; consider a terminal decline or longer history |
| Status `insufficient_data` | < 3 usable points after peak | Wait for more history, or use a type curve as an analog |
| EUR far from a public estimate | Different rate basis, b policy, or econ limit | Compare decisions, not just numbers |

## Guardrails

1. Never invent a decision value. Use the user's, or stop and ask.
2. Never fit boe or mixed streams.
3. Never relabel percentiles: P10 is the high case.
4. Report flagged wells individually. Never hide them in a total.
5. Fits are technical forecasts, not booked reserves (PRMS / SEC classification is out of scope).
6. Confirm before running on more than ~20,000 wells, and avoid retrying more than 3 times.

## Related Skills

- `unit-guard`: boe roll-ups (`boe_from_gas`), bbl ↔ m³, Mcf ↔ Sm³
- `osdu-ppdm-mapper`: well identity (API/UWI), headers, completions
- `well-log-ingest`: petrophysical inputs for analog selection
- `energy-semantic-builder`: governed KPIs (EUR per ft, lifting cost per boe)
- `energy-report-writer` / `presentation-builder`: reserves memos and decks

## Bundled Resources

- `scripts/dca_models.py`: Arps / modified-hyperbolic rate and cumulative, decline conversions
- `scripts/dca_fit.py`: bounded, deterministic log-rate fit
- `scripts/dca_prep.py`: rate basis, shut-ins, peak selection, MAD outliers, time axis
- `scripts/dca_config.py`: decision validation (`DecisionRequired`)
- `scripts/dca_well.py`: per-well EUR, flags, monthly forecast
- `scripts/dca_typecurve.py`: PRMS percentiles, normalization, survivor-bias truncation
- `scripts/dca_preview.py`, `scripts/dca_run.py`, `scripts/uc_io.py`: preview and UC runner
- `references/arps_and_declines.md`: equations, bounded b, terminal decline, decline conventions
- `references/data_conditioning.md`: rate basis, shut-ins, peak, outliers, streams
- `references/type_curves.md`: PRMS percentiles, normalization, Duong / SEPD notes

## References

- [Arps (1945), Analysis of Decline Curves](https://doi.org/10.2118/945228-G)
- [SPE PRMS 2018](https://www.spe.org/en/industry/petroleum-resources-management-system-2018/)
- [SPEE Monograph 4](https://spee.org/): EUR estimation for low-permeability reservoirs
- [Fetkovich (1980), Decline Curve Analysis Using Type Curves](https://doi.org/10.2118/4629-PA)
- [Duong (2011), Rate-decline analysis for fracture-dominated shale reservoirs](https://doi.org/10.2118/137748-PA)
