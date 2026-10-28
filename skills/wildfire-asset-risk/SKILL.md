---
name: wildfire-asset-risk
description: >-
  Wildfire risk for overhead power lines on H3 grids: joins line segments to vegetation
  strike, LANDFIRE FBFM40 fuel models, terrain slope, historical utility ignitions, and
  structure/population exposure; scores likelihood × consequence with user-confirmed
  weights; screens PSPS (Public Safety Power Shutoff) candidate circuits from gridded
  wind gust, humidity, temperature and Fosberg Fire Weather Index forecasts against the
  utility's own thresholds; and ranks covered conductor, undergrounding, and vegetation
  mitigation by risk-spend efficiency under a budget. Uses Databricks H3 SQL
  (h3_coverash3, h3_longlatash3string, h3_polyfillash3, h3_kring) and densified spans so
  no conductor cell is skipped. Weights, consequence basis, PSPS thresholds, and
  mitigation effectiveness/cost are decisions surfaced before building. Run by calling
  scripts/wildfire_run.py or scripts/wildfire_api.py; do not hand-write the scoring.
  Coordinates are CEII-sensitive; for de-identification use grid-data-guard.
category: "Power & Utilities"
summary: H3 wildfire risk for line segments, PSPS candidate screening, and mitigation ranking by risk-spend efficiency.
version: 0.1.0
author: Sourabh Ghose
license: Databricks License
---

# Wildfire Asset Risk

## Overview

Scores every overhead line segment for wildfire risk and turns the scores into two
decisions utilities make every season: which circuits are **PSPS candidates** under the
coming weather, and where mitigation dollars buy the most risk reduction. Segments are
indexed to H3 cells along the whole span (not just at poles), hazard layers are joined
per cell, exposure is summed over a k-ring buffer, and every weight, threshold, and
mitigation assumption is the user's decision, recorded in a run manifest.

It runs on the **execution model**: Genie Code calls the entrypoints and reports their
output. It does not write its own scoring and does not choose weights or thresholds.

## When to Use

- "Rank our overhead segments in the high fire-threat district by wildfire risk."
- "Which circuits would be PSPS candidates under tomorrow's wind forecast?"
- "We have $40M for covered conductor and undergrounding: which miles first?"
- "How sensitive is our top-20 list to how we weight vegetation vs. ignition history?"
- "Join LANDFIRE fuels and slope to our GIS line segments on H3."
- "Compute Fosberg FFWI for each forecast cell and flag hours above our threshold."
- "Give me a map-ready risk layer I can share without exposing asset locations."

## Prerequisites

- **Compute**: Python compute with a Spark session; `%pip install h3` (v4) so k-ring buffers
  use the same cell ids as Databricks H3. Databricks Runtime / SQL with H3 functions.
- **Inputs** (UC tables; see `references/data_sources.md`):
  - segments: `segment_id, circuit_id, lat1, lon1, lat2, lon2 [, hftd_tier]`
  - layers keyed by H3 string `cell`: `vegetation(veg_strike_index)`, `fuel(fbfm40)`,
    `slope(slope_deg)`, `ignitions(n_ignitions)`, `exposure(structures, population)`
  - optional forecast: `cell, valid_ts, wind_gust_mph, wind_sustained_mph, rh_pct, temp_f`
  - optional circuit customers; optional mitigation assumptions table

## Quick Start

```python
import sys
sys.path.append('<this-skill-dir>/scripts')
from wildfire_run import preview_from_uc, build_confirmed_from_uc

layers = {"vegetation": "<cat.sch.veg_h3>", "fuel": "<cat.sch.fbfm40_h3>",
          "slope": "<cat.sch.slope_h3>", "ignitions": "<cat.sch.ignitions_h3>",
          "exposure": "<cat.sch.exposure_h3>"}

# STEP 1 — READ-ONLY: coverage, coordinate checks, ranking sensitivity, PSPS sensitivity.
print(preview_from_uc("<cat.sch.oh_segments>", layers, res=9, buffer_k=2,
                      forecast_table="<cat.sch.forecast_h3>")["readout"])

# STEP 2 — ONLY after the user confirms weights, basis and thresholds.
res = build_confirmed_from_uc("<cat.sch.oh_segments>", layers, res=9, buffer_k=2,
                              target_prefix="<cat.sch.wildfire_2025>",
                              likelihood_weights={"vegetation": 0.4, "fuel": 0.3,
                                                  "slope": 0.1, "ignition_history": 0.2},
                              consequence_basis="structures_and_population",
                              psps_thresholds={"wind_gust_mph": 45, "rh_pct": 20},
                              forecast_table="<cat.sch.forecast_h3>")
print(res["readout"])
```

## Workflow

**⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
output. Do not hand-write the calculation, and do not pick a decision-point value yourself.

### Step 1: Prepare layers on H3

Point layers (ignitions, structures, weather stations) → `point_cells_sql` with
`h3_longlatash3string(lon, lat, res)` (longitude first). Rasters (fuel, slope, canopy) →
aggregate pixel centroids per cell. HFTD polygons → `h3_polyfillash3(wkt, res)` → join to
segments as `hftd_tier`.

```python
from wildfire_run import point_cells_sql
spark.sql(point_cells_sql("<cat.sch.structures>", ["structures"]), args={"res": 9})
```

### Step 2: Index segments along the span

`segment_cells_sql` runs `h3_coverash3` on each `LINESTRING(lon1 lat1, lon2 lat2)` and
returns H3 strings. Offline, `segment_cells` densifies spans to a third of the cell edge.
Indexing poles only misses the conductor between them.

### Step 3: Preview the decisions (read-only)

`preview_wildfire_risk` checks coordinates (swapped lat/lon, zero-length spans), reports
layer coverage of segment cells, shows top-N overlap between three example weightings,
and counts circuits flagged by three example PSPS threshold sets. Show the readout; ask
for each decision.

### Step 4: Score segments

`likelihood = Σ w × {vegetation, fuel, slope, ignition_history}` on fixed 0–1 scales;
`consequence` = log-scaled structures and/or population within k rings;
`risk = likelihood × consequence`. Missing hazard data is flagged per segment.
See `references/risk_model.md`.

### Step 5: Screen PSPS candidates (optional)

Forecast hours where gust ≥ threshold and RH ≤ threshold (and FFWI ≥ threshold if given)
on segment cells in an HFTD flag the circuit. FFWI uses sustained wind.
See `references/psps_screening.md`.

### Step 6: Plan mitigation (optional)

With `mitigation_assumptions` (effectiveness, cost per mile) and `budget_usd`, the best-RSE
option per segment is chosen, then segments are taken in RSE order while they fit.

### Step 7: Persist and share

`build_confirmed_from_uc` writes `<prefix>_segment_risk`, `_circuit_risk`,
`_psps_candidates`, `_mitigation_plan`, `_shareable_cells`, `_manifest`. Only
`_shareable_cells` (H3 res 7, no asset ids or coordinates) is suitable for wide sharing.

## Decision Points

| Decision | Options | Governing reference | What changes |
|----------|---------|---------------------|--------------|
| `likelihood_weights` | weights over vegetation, fuel, slope, ignition_history (sum to 1) | Utility risk model / WMP methodology | Which segments rank highest |
| `consequence_basis` | `structures`, `population`, `structures_and_population` | WMP consequence definition | Urban-interface vs. rural emphasis |
| `psps_thresholds` | `wind_gust_mph`, `rh_pct` [, `ffwi`] | Utility de-energization protocol | Number of circuits and customers flagged |
| `mitigation_assumptions` | per option: `effectiveness` (0–1), `cost_per_mile_usd` | Utility WMP / GRC filings | Mitigation choice and plan miles |

## Key Parameters

| Parameter | Default | Range / Options | Effect |
|-----------|---------|-----------------|--------|
| `res` | (required) | H3 5–11; 9 ≈ 0.17 km edge | Spatial detail; finer = more cells |
| `buffer_k` | (required) | 0–5 rings | Exposure / ignition search radius (≈ k × √3 × edge) |
| `budget_usd` | `None` | $ | Enables the mitigation plan |
| `top_n` | `20` | 5–100 | Ranking-overlap window in the preview |
| `hftd_only` | `True` | bool | PSPS screening limited to HFTD segments |

## Expected Outputs

- Segment risk table: components, `likelihood`, `consequence`, `risk`, `risk_rank`,
  `missing_hazard_data`, `length_mi`.
- Circuit roll-up: total risk, miles, `risk_per_mile`.
- PSPS candidates: flagged segments, first/last hour (local), peak gust, min RH, peak FFWI.
- Mitigation plan: chosen option, cost, risk reduction, RSE per $M, `selected`.
- Shareable cells (res 7) and a run manifest with grid backend, resolution, k, decisions.

## Troubleshooting

| Problem | Cause | Solution |
|---------|-------|----------|
| `latitude ... out of range; are lat/lon swapped?` | Columns swapped, or Databricks arg order used in python | Fix mapping; Databricks is (lon, lat) |
| All segments score 0 on fuel | FBFM40 codes stored as integers (e.g. 145) | Map numeric codes to FBFM40 letters before joining |
| FFWI implausibly low in summer | Temperatures in °C | Convert to °F; wind to mph |
| Runner: `Install python h3` | Fallback grid cannot buffer Databricks cells | `%pip install h3`, restart Python |
| Few cells per segment | Only pole points indexed | Use `segment_cells_sql` (h3_coverash3) |
| Plan spends less than budget | Large items skipped by greedy | Expected; report it, or split long segments |

## Guardrails

1. Never choose weights, thresholds, effectiveness, or costs; show the preview and ask.
2. Present PSPS output as screening, not a de-energization decision.
3. Do not publish segment coordinates, ids, or circuit topology; share `shareable_cells`
   only, and route anything else through `grid-data-guard`.
4. State that greedy RSE selection is a heuristic.
5. Writing UC tables is an outward action: confirm the target prefix first.
6. Avoid retrying more than 3 times; report the error.

## Related Skills

- `grid-data-guard` — mask CEII (coordinates, topology) and customer data before sharing.
- `reliability-metrics` — PSPS events appear in reliability reporting.
- `equipment-pdm` — asset condition can extend the likelihood components.
- `energy-report-writer` — draft WMP-style narrative from the readout and manifest.
- `skill-eval` — benchmark this skill with and without it loaded.

## References

- `references/risk_model.md` — likelihood, consequence, roll-ups, RSE, assumptions.
- `references/data_sources.md` — layers, units, pitfalls, CEII.
- `references/psps_screening.md` — screening logic and threshold choices.
- [Databricks H3 functions](https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-h3-geospatial-functions)
- [LANDFIRE](https://landfire.gov/) and [Scott & Burgan 2005, RMRS-GTR-153](https://www.fs.usda.gov/rm/pubs_series/rmrs/gtr/rmrs_gtr153.pdf)
- [California OEIS Wildfire Mitigation Plans](https://energysafety.ca.gov/) · [CPUC PSPS](https://www.cpuc.ca.gov/psps)
