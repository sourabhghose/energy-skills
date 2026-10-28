# Lakehouse industry data models (Vibe Data Modeling)

## Identity

- Name: Lakehouse industry data models (Vibe Data Modeling)
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/lakehouse-industry-data-models
- Install doc: README (`model-agent/`, `model-app/`, `model-installer/`)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-10-21
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 85c4d28

## Use it for

- Generating a governed Silver-layer data model (schemas, foreign keys, metric views, tags, ontology) from a plain-English business description
- Example models for `energy_utilities`, `oil_gas`, and `water_utilities` in `data-models/`

## Do not use it for

- Mapping to the OSDU or PPDM industry standards: use `osdu-ppdm-mapper`
- Standard energy KPIs as UC metric views: use `energy-semantic-builder`

## Data

Generated example models; no customer data.

## Deploy signals

Model app deployed from `model-app/`.

## Smallest path

Browse the gallery (`https://databricks-industry-solutions.github.io/lakehouse-industry-data-models/`) and start from `data-models/energy_utilities` or `data-models/oil_gas`.

## Pitfalls

1. Generated models are not industry standards; for regulated or partner exchange, map to OSDU/PPDM/CIM explicitly.

## Pair with Energy Skills

`osdu-ppdm-mapper`, `energy-semantic-builder`
