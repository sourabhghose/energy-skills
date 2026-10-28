# AVEVA CONNECT ↔ Databricks integration (PI System data)

## Identity

- Name: AVEVA CONNECT ↔ Databricks integration (PI System data)
- Kind: vendor-integration
- URL: https://www.aveva.com/en/perspectives/blog/connect-and-databricks-integration-is-here/
- Install doc: AVEVA documentation; Delta Sharing from AVEVA CONNECT
- Maintainers: AVEVA
- Licence: vendor terms
- Last updated: 2026-10-28
- Maturity: maintained
- Reviewed: 2026-10-28 (page checked, HTTP 200)

## Use it for

- Getting AVEVA PI System (formerly OSIsoft PI) historian data into Databricks through AVEVA CONNECT data services and Delta Sharing

## Do not use it for

- On-prem PI without AVEVA CONNECT: build a custom Lakeflow connector against PI Web API (https://docs.databricks.com/aws/en/ingestion/custom-connectors) or land data via Kafka / object storage
- Ignition-based sites: use `lakeflow-zerobus-ignition-connector`

## Data

PI tags and Asset Framework context shared from AVEVA CONNECT.

## Deploy signals

A Delta Sharing catalog from the AVEVA provider in Unity Catalog.

## Smallest path

Ask the PI owner whether the site is on AVEVA CONNECT; if yes, request a Delta Share to your metastore.

## Pitfalls

1. As of 2026-10-28 there is no managed Lakeflow Connect connector for on-prem PI listed by Databricks; do not promise one.
2. PI tag names are not asset IDs; map through PI Asset Framework before analysis (`equipment-pdm`).

## Pair with Energy Skills

`equipment-pdm`, `wind-solar-performance`
