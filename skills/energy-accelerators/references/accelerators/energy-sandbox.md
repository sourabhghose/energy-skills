# Energy Sandbox

## Identity

- Name: Energy Sandbox
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/energy-sandbox
- Install doc: each project folder's README (`<project>/README.md`), deployed as a Databricks App with Asset Bundles
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-05-26
- Maturity: maintained
- Reviewed: 2026-10-28 against commit 0ddce23

## Use it for

- Upstream and midstream oil & gas demo apps on Databricks Apps + Lakebase + Foundation Model APIs:
  - **Production Optimizer** (`production-optimizer/`): Arps decline-curve analytics, Genie access, multi-agent recommendation approval
  - **ESP Predictive Maintenance** (`esp-pm/`): electric submersible pump failure prediction with streaming inference
  - **LAS Viewer** (`las-viewer/`): well-log visualization, automated QC, petrophysical advisory
  - **OSDU ADME Connector** (`osdu-app-with-connector/`): ingest OSDU Wellbore / Reservoir / Rock & Fluid records from Azure Data Manager for Energy into Unity Catalog
  - **Drilling Command Center**, **ROP Prediction**, **Pipeline Command Center**, **BOP Guardian**, **CO2-EOR Digital Twin**, **Reservoir Simulator**, **Oil Pump Vibration Monitor**, **Subsea Drone Autopilot**
- A customer-facing O&G demo or a starting UI for one of these workflows

## Do not use it for

- Defensible decline-curve EUR with bounded b-factors and reserves-grade decisions: use `decline-curve-analysis` (the app is a demo UI)
- LAS/DLIS ingestion with unit and depth-reference checks into governed tables: use `well-log-ingest`
- Non-productive time from daily drilling reports: use `drilling-report-npt`
- OSDU/PPDM schema mapping of your own sources: use `osdu-ppdm-mapper` (the connector covers ADME ingestion only)

## Data

Mostly synthetic or public benchmark data per project (e.g. Norne field for the reservoir simulator, MSEEL data for ROP prediction).

## Deploy signals

Databricks Apps named after each project; check each project's `databricks.yml` / `app.yaml`. Not documented centrally.

## Smallest path

Clone the repo as a Git folder, pick one project folder, follow its README (most use `databricks bundle validate` / `databricks bundle deploy`).

## Pitfalls

1. It is a collection, not one product: each project has its own prerequisites (Lakebase, Genie space, model endpoints). Read that project's README first.
2. Several apps reference SAP or SCADA integrations that are simulated in the demo; say so before promising integration.
3. The OSDU connector targets Azure Data Manager for Energy; other OSDU deployments need endpoint and auth changes.

## Pair with Energy Skills

`decline-curve-analysis`, `well-log-ingest`, `equipment-pdm`, `osdu-ppdm-mapper`, `drilling-report-npt`
