# Multi-agent knowledge assistant for field troubleshooting & repair

## Identity

- Name: Multi-agent knowledge assistant for field troubleshooting & repair
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/field-repair-knowledge-assistant
- Install doc: README (Asset Bundle; serverless)
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2026-10-08
- Maturity: maintained
- Reviewed: 2026-10-28 against commit bb2db74

## Use it for

- Turning historical work orders, tickets and resolutions into a cited knowledge base with a Supervisor routing to a Knowledge Assistant and Genie
- Field crews asking "has this failure happened before and how was it fixed?" (lineworkers, field technicians, wellsite maintenance)

## Do not use it for

- Structured NPT classification of drilling reports: use `drilling-report-npt`
- Failure-rate statistics and predictive maintenance: use `equipment-pdm`

## Data

Ships with a synthetic field-repair corpus and a governed glossary; swap in your own corpus.

## Deploy signals

Not documented as fixed names; check `databricks.yml`.

## Smallest path

Deploy as-is on the shipped corpus, then point ingestion at your work-order export.

## Pitfalls

1. Work orders often contain names and addresses; mask before indexing.

## Pair with Energy Skills

`equipment-pdm`, `drilling-report-npt`
