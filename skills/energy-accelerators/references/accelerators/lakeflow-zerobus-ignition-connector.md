# Ignition OT ingestion connector (Zerobus / Lakebase)

## Identity

- Name: Ignition OT ingestion connector (Zerobus / Lakebase)
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/lakeflow-zerobus-ignition-connector
- Install doc: `DEPLOYMENT.md`; an Ignition Gateway module (`.modl`)
- Maintainers: see repo contributors
- Licence: Apache-2.0
- Last updated: 2026-10-19
- Maturity: maintained
- Reviewed: 2026-10-28 against commit d284f03

## Use it for

- Streaming OT tag events from an Inductive Automation Ignition Gateway (OPC UA, MQTT, PLC drivers, historians behind Ignition) into Delta via Zerobus Ingest or into Lakebase
- Plant, substation, or wellsite SCADA telemetry into the lakehouse without a message bus

## Do not use it for

- AVEVA / OSIsoft PI System without Ignition: see `aveva-connect`
- Tag-to-asset mapping and predictive maintenance: use `equipment-pdm` after ingestion

## Data

Your Ignition tags; an optional local Gateway runtime is in `docker/ignition-gateway/`.

## Deploy signals

Ignition module installed on the Gateway; target Delta table or Lakebase table configured in the module.

## Smallest path

Install the module on a test Gateway, set `sinkMode=zerobus`, point it at a UC table.

## Pitfalls

1. Installing a Gateway module is an OT change: go through the site's OT change control and network segmentation review.
2. Choose one sink mode; they are exclusive.

## Pair with Energy Skills

`equipment-pdm`, `wind-solar-performance`, `databricks-zerobus-ingest` (platform skill)
