# Databricks Labs GeoBrix

## Identity

- Name: Databricks Labs GeoBrix
- Kind: library
- URL: https://github.com/databrickslabs/geobrix
- Install doc: https://databrickslabs.github.io/geobrix/
- Maintainers: Databricks Labs
- Licence: Databricks License (Labs project)
- Last updated: 2026-10-28
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 59cc8d4

## Use it for

- Raster I/O and analytics (RasterX: clip, reproject, terrain, spectral indices, H3 tessellation), discrete global grids (GridX), vector extras (VectorX) on Databricks
- Lightweight pure-Python tier runs on serverless; heavyweight Scala + GDAL tier on classic clusters
- Successor to Mosaic (Mosaic reached end of support with DBR 13.3 in August 2026)

## Do not use it for

- Plain vector work covered by built-in `ST_*` / `h3_*` SQL functions (DBR 17.1+): use the built-ins

## Data

Your rasters (DEMs, satellite scenes) and vectors.

## Deploy signals

`gbx_` prefixed SQL functions registered on the cluster.

## Smallest path

Follow the lightweight-tier install in the docs; call `gbx_rst_*` functions from SQL or Python.

## Pitfalls

1. Do not start new work on databrickslabs/mosaic: it is archived and end-of-support.

## Pair with Energy Skills

`wildfire-asset-risk`, `energy-foundation-models` (chip preparation), `flood-prediction`
