# Flood Prediction

## Identity

- Name: Flood Prediction
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/flood-prediction
- Install doc: README + `databricks.yml` (serverless job wiring four notebooks, plus an app)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-07-31
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 1ef8c47

## Use it for

- Per-H3-cell flood probability from a DEM (GeoBrix RasterX lightweight tier), distance to water, historical flood polygons and ERA5 precipitation climatology
- Spatial SQL (`ST_*`, `h3_*`, DBR 17.1+), Spark ML random forest with MLflow and UC registration
- A Databricks App (FastAPI + React + deck.gl) with a rainfall slider

## Do not use it for

- Observed flood extent from satellite imagery: see `energy-foundation-models` (Prithvi Sen1Floods11 head)
- Asset-level exposure scoring for wildfire: use `wildfire-asset-risk`

## Data

Public elevation, water, climate (Open-Meteo ERA5 archive) and historical flood data.

## Deploy signals

Serverless job from `resources/pipeline.yml`; app from `resources/app.yml`.

## Smallest path

`databricks bundle deploy` then run the pipeline job; overlay your substations or well pads on the H3 output.

## Pitfalls

1. Requires DBR 17.1+ spatial SQL functions.
2. See `KNOWN_LIMITATIONS.md` in the repo before using results for siting or hardening decisions.

## Pair with Energy Skills

`wildfire-asset-risk`, `energy-foundation-models`, `geobrix`
