# Planted-Truth Synthetic Data for Energy Tasks

Referenced from SKILL.md Step 1. New for Energy Skills.

A planted-truth dataset is generated so that the correct answer is known **by construction**. You
plant a defect (a trap the naive approach falls into) or a parameter (a known b-factor, a known
Major Event Day), then score the agent's answer against what you planted. This gives exact
deterministic scorers instead of judges guessing at correctness.

## Rules

1. **Seeded and pure.** `generate_data.py` takes a fixed seed, writes to `SKILL_EVAL_DATA_DIR`
   (fallback `OUT_DIR`), and produces byte-identical output on every run.
2. **Answer computed in the generator, written only to the generator's stdout or a sidecar
   the agent can't see.** Copy the planted answers into `expectations.json` by hand once. Never
   write them into the dataset folder the agent reads.
3. **One trap per task where possible.** A task with three traps can't tell you which one the
   skill fixed.
4. **Realistic magnitudes and units.** Use real-world ranges (residential 0.1-5 kW per 15 min,
   Permian wells 300-1,500 bbl/d initial rate, SAIDI 80-200 min/yr). Implausible numbers make
   judges and agents behave differently than on real data.
5. **Label units in column names exactly as a real source would.** If a real source would
   label it ambiguously (`gas_vol`), keep the ambiguity and make it a task.
6. **No real identifiers.** Synthetic meter IDs (`M-0001`), API numbers that cannot be valid
   (state code `99`), fictional facility names. Never reuse customer or operator data.

## Recipes by Domain

### Interval / meter data (ami-interval-analytics, load-forecaster)

| Plant | How | Exact check |
|-------|-----|-------------|
| DST fall-back | Generate in local time `America/Chicago` across 2025-11-02 | That day has 100 15-min intervals (25 h); daily kWh = planted sum |
| DST spring-forward | Same across 2025-03-09 | 92 intervals (23 h); no fabricated 02:00-02:59 rows |
| Estimated reads | Flag 3% of reads `quality='E'` | Agent excludes or reports them separately |
| Cumulative register | Provide `register_kwh` monotone with one rollover at 99,999 | Interval kWh never negative; rollover recovered |
| Duplicate reads | Duplicate 0.5% rows with a later `received_at` | Latest-received wins; counts match |
| Look-ahead leak | Hold out the last 8 weeks; ask for a forecast "using this data" | Backtest split is time-ordered; reported MAPE matches holdout |

```python
import numpy as np, pandas as pd
rng = np.random.default_rng(7)
idx = pd.date_range("2025-11-01", "2025-11-04", freq="15min", tz="America/Chicago", inclusive="left")
kwh = np.round(rng.gamma(2.0, 0.15, len(idx)), 3)
df = pd.DataFrame({"meter_id": "M-0007", "interval_start_local": idx, "kwh": kwh})
# Grouped by local start date: 96 / 100 / 96 intervals. Keep `planted` out of the data folder.
planted = df.groupby(df["interval_start_local"].dt.date)["kwh"].agg(["count", "sum"])
```

### Reliability (reliability-metrics)

Generate customer-interruption events for a year. Plant one storm day whose daily SAIDI exceeds
the IEEE 1366 T_MED threshold computed from the prior five years of daily SAIDI (the 2.5-beta method
on the log of daily SAIDI). Record SAIDI with and without that day; the edge task passes only
if the agent reports both or asks which to use.

### Production / decline (decline-curve-analysis)

Simulate monthly oil rates from a modified-hyperbolic Arps model with known `qi`, `Di`, `b`, and
terminal decline `Dmin`. Add multiplicative lognormal noise (sigma ≈ 0.08) and two shut-in
months with zero production. Exact checks: fitted `b` within ±0.15, EUR within ±10%, shut-in
months excluded from the fit, `b > 1` flagged and terminal decline applied.

### Well logs (well-log-ingest)

Write LAS 2.0 files where one well's depth is in feet and another's in metres, one uses `GR`
and another `GAMMA` for gamma ray, and one has the `-999.25` null value. Checks: depth unit
detected, mnemonics mapped to one canonical curve, nulls never treated as values.

### Free text (drilling-report-npt, equipment-pdm work orders)

Template daily drilling report sentences with planted NPT events of known duration and class,
plus negated distractors ("no losses observed") and offset-well mentions ("offset well lost
circulation"). Checks: planted events found with correct hours, distractors not extracted,
every extracted event has a quote that literally appears in the report.

### Emissions (ghg-emissions-calculator)

Provide fuel-use and electricity rows for fictional facilities. Compute the planted answer with a
named, versioned factor table (e.g. EPA GHG Emission Factors Hub, a specific year) for both
location- and market-based Scope 2. The edge task leaves the method unstated; it passes only if
the agent asks or reports both, and states the factor vintage.

### Markets and renewables (iso-market-data, wind-solar-performance)

Plant 5-minute real-time prices that settle to hourly, including one interval at the price cap
and one negative-price interval; for wind, plant a curtailment flag over a high-wind period.
Checks: hourly averages match the planted settlement rule, negative prices kept, curtailment
separated from underperformance.

## Where to go next

For evaluation across many skills on **public** data (EIA, ERCOT/CAISO, NREL, Equinor Volve,
EPA GHGRP), with covered vs. control tasks and a no-harm check, use
[`benchmarks/energybench`](../../../benchmarks/energybench/README.md). Planted-truth per-skill
evals and EnergyBench answer different questions: "does this skill fix the trap it was built
for?" vs. "does the skill set help on realistic work without hurting unrelated work?"
