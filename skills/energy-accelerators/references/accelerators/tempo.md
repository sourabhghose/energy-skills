# Databricks Labs Tempo

## Identity

- Name: Databricks Labs Tempo
- Kind: library
- URL: https://github.com/databrickslabs/tempo
- Install doc: https://databrickslabs.github.io/tempo/
- Maintainers: Databricks Labs
- Licence: Databricks License (Labs project)
- Last updated: 2026-07-10
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 8cde1ad

## Use it for

- PySpark time-series utilities: as-of joins, resampling, interpolation, rolling statistics on large sensor / meter / market data

## Do not use it for

- Domain rules such as VEE, DST handling or settlement intervals: use `ami-interval-analytics` / `iso-market-data`

## Data

Any Spark DataFrame with a timestamp and series key.

## Deploy signals

`dbl-tempo` installed; `TSDF` objects in notebooks.

## Smallest path

`%pip install dbl-tempo`, then wrap a DataFrame in `TSDF(df, ts_col=..., partition_cols=[...])`.

## Pitfalls

1. The Scala version is deprecated; use the Python package.

## Pair with Energy Skills

`ami-interval-analytics`, `equipment-pdm`, `iso-market-data`
