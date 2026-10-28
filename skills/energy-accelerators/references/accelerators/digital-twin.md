# Digital Twin

## Identity

- Name: Digital Twin
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/digital-twin
- Install doc: README (`databricks bundle deploy`, `databricks bundle run setup_solution_accelerator`)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2025-12-06
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 035a894

## Use it for

- IoT ingestion with Zerobus, RDF/OWL semantic modelling, sensor-to-twin mapping pipelines, Lakebase sync for low-latency reads, and a knowledge-graph app
- Shipped example is a ball-bearing production line; README lists energy grid monitoring as a reuse scenario

## Do not use it for

- Ready-made O&G twins (pipelines, BOP, CO2-EOR): see `energy-sandbox`
- Network models of the electric grid (CIM, power flow): not covered

## Data

Synthetic line sensor data generator (`line_data_generator/`).

## Deploy signals

Jobs `setup_solution_accelerator` / `teardown_solution_accelerator`.

## Smallest path

`databricks bundle deploy` then `databricks bundle run setup_solution_accelerator`.

## Pitfalls

1. The ontology is manufacturing-specific; an energy twin needs its own RDF model (e.g. derived from CIM classes).
2. Requires Lakebase and Databricks Apps.

## Pair with Energy Skills

`equipment-pdm`, `energy-sandbox`
