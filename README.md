# Energy Skills

Agent skills for the energy industry: power & utilities, oil & gas, renewables, markets, and
emissions. Each skill guides [Databricks Genie Code](https://docs.databricks.com/aws/en/genie-code/)
(or any agent that reads the open [Agent Skills](https://agentskills.io) format) through an
end-to-end workflow, from smart-meter validation to decline-curve EUR to Scope 1–3 inventories,
and runs on the Databricks Data Intelligence Platform with Unity Catalog governance.

Modelled on [Vital Skills](https://github.com/databricks-industry-solutions/vital-skills) for
Health & Life Sciences.

## Why skills

General coding agents write code that runs but skips the domain's rules:

- drop or double-count the repeated hour when daylight saving time ends in interval meter data
- convert gas to boe at 6:1 without saying so, or mix MW and MWh
- compute SAIDI without excluding IEEE 1366 Major Event Days
- fit an Arps curve with an unbounded b-factor and report a 60-year EUR
- choose a Scope 2 method and an emission-factor vintage silently
- leak the future into a load forecast with a random train/test split

Every skill here follows the **Energy Skill Contract** ([AGENTS.md](AGENTS.md)):

1. **Execute, don't reimplement.** The agent calls tested entrypoints in `scripts/`.
2. **Ask before assuming.** A read-only `preview_*` puts each decision point (with its effect
   on *your* data) in front of the user; `build_confirmed_*` refuses to run without it.
3. **Units, time, and identity are explicit.** Units on every number, timezone-aware
   timestamps, no hallucinated well/meter/node IDs.
4. **Reproducible.** Every run writes a manifest of inputs, decisions, and factor versions.
5. **Governed.** Unity Catalog outputs, parameterized SQL, CEII and customer data protected.
6. **Proven.** Offline unit tests plus a with/without-skill benchmark
   ([EnergyBench](benchmarks/energybench/README.md)).

## Skills

<!-- skill-catalog:start -->
| Skill | Category | What it does |
|-------|----------|--------------|
| [**ami-interval-analytics**](skills/ami-interval-analytics/SKILL.md) | Power & Utilities | Validate, estimate and quality-flag smart-meter interval data, safely across DST, with user-chosen VEE rules. |
| [**grid-data-guard**](skills/grid-data-guard/SKILL.md) | Power & Utilities | Protect CEII and customer meter data with masked internal views or 15/15-checked aggregate releases. |
| [**load-forecaster**](skills/load-forecaster/SKILL.md) | Power & Utilities | Day-ahead and week-ahead load forecasts with leakage-safe backtests, a naive benchmark, and weather-normalized energy. |
| [**reliability-metrics**](skills/reliability-metrics/SKILL.md) | Power & Utilities | IEEE 1366 SAIDI/SAIFI/CAIDI/MAIFI with 2.5-beta Major Event Days, step restoration, and a governed metric view. |
| [**wildfire-asset-risk**](skills/wildfire-asset-risk/SKILL.md) | Power & Utilities | H3 wildfire risk for line segments, PSPS candidate screening, and mitigation ranking by risk-spend efficiency. |
| [**decline-curve-analysis**](skills/decline-curve-analysis/SKILL.md) | Oil & Gas | Bounded Arps / modified-hyperbolic decline fits, EUR, forecasts, and PRMS P10/P50/P90 type curves, with b-factor, terminal decline, and rate basis chosen by the engineer. |
| [**drilling-report-npt**](skills/drilling-report-npt/SKILL.md) | Oil & Gas | Classify drilling NPT and invisible lost time from DDR remarks and activity codes, with span-grounded evidence and 24-hour reconciliation. |
| [**equipment-pdm**](skills/equipment-pdm/SKILL.md) | Oil & Gas | Historian-grounded predictive maintenance for ESPs, compressors, pumps and turbines, with leakage-safe labels and false-alarm-aware alert evaluation. |
| [**osdu-ppdm-mapper**](skills/osdu-ppdm-mapper/SKILL.md) | Oil & Gas | Map vendor well, wellbore, completion and production data to OSDU / PPDM with a reviewed spec, grounded API IDs, explicit datums, and lineage. |
| [**well-log-ingest**](skills/well-log-ingest/SKILL.md) | Oil & Gas | LAS logs to governed Delta tables with standardized mnemonics, verified units, explicit depth datum, API number checks, and run-overlap policy. |
| [**iso-market-data**](skills/iso-market-data/SKILL.md) | Renewables & Markets | DST-safe, convention-aware ISO price normalization, peak blocks with NERC holidays, basis, DA-RT spread and two-settlement revenue. |
| [**wind-solar-performance**](skills/wind-solar-performance/SKILL.md) | Renewables & Markets | Wind power-curve, availability and lost-production split; solar PR, clipping, soiling and degradation; curtailment always kept separate. |
| [**ghg-emissions-calculator**](skills/ghg-emissions-calculator/SKILL.md) | Emissions & ESG | Scope 1, 2 (dual) and 3 cat 11 inventory with versioned factors, Subpart W screening, OGMP 2.0 levels, and full factor lineage. |
| [**energy-accelerators**](skills/energy-accelerators/SKILL.md) | Others | Route energy tasks to a verified Databricks accelerator, library or partner solution — or to an Energy Skill — with the exact next step. |
| [**energy-foundation-models**](skills/energy-foundation-models/SKILL.md) | Others | Package, validate against seasonal naive, register & deploy open-weight energy forecasting and satellite models — Chronos-2, TimesFM 2.5, Prithvi-EO-2.0. |
| [**energy-report-writer**](skills/energy-report-writer/SKILL.md) | Others | Draft energy reports (engineering study, reliability, rate-case, EIA/FERC, ESG, production) where every number traces to a table; LaTeX/PDF or Markdown. |
| [**energy-semantic-builder**](skills/energy-semantic-builder/SKILL.md) | Others | Governed energy KPI layer (73 measures, 6 domains) generated as Unity Catalog metric views from a per-customer mapping. |
| [**presentation-builder**](skills/presentation-builder/SKILL.md) | Others | Turn reliability, production, emissions, forecast, or market results into a grounded, unit-correct, shareable HTML deck. |
| [**skill-eval**](skills/skill-eval/SKILL.md) | Others | Benchmark a skill: paired runs with/without it on planted-truth energy data, MLflow genai.evaluate scoring, win/loss + failure taxonomy. |
| [**unit-guard**](skills/unit-guard/SKILL.md) | Others | Vetted, dimension-checked energy unit conversions (Mcf, boe, MMBtu, MWh, tCO2e) that refuse ambiguous units and ask about standard conditions and conventions. |
<!-- skill-catalog:end -->

## Install

**Genie Code (workspace):** publish the skills to a Unity Catalog schema, then add that schema
in Genie Code's skill settings.

```bash
uv run sync_skills_git2unity.py --dry-run                     # list what would ship
uv run sync_skills_git2unity.py --catalog <catalog> --schema energy_skills \
    --warehouse-id <id> [--profile <profile>]
```

Only `SKILL.md`, `scripts/`, `references/`, and `assets/` are published. Each skill's `tests/`
and `eval/` (which holds the benchmark answer key) stay in git.

**Genie Code CLI / other agents:** copy or symlink `skills/<name>` into the agent's skills
folder (for example `.agents/skills/` or `.claude/skills/`).

**Skill discovery:** add one line to your agent instructions (`AGENTS.md`), for example:
*"Before writing energy-domain analysis code, check whether an Energy Skill covers the task
and read its SKILL.md first."*

## Repository layout

```
skills/<name>/          SKILL.md, scripts/, references/, tests/, eval/
benchmarks/energybench/ cross-skill benchmark on public energy data + planted-truth tasks
templates/              SKILL.md templates (pipeline, guide)
tests/                  repo-level quality gate, catalog sync, publish-bundle filter
docs/                   landing page (generated catalog) and docs hooks
sync_skills_git2unity.py  publish skills to Unity Catalog
```

## Checks

```bash
uv run --isolated --with pytest --with pyyaml python -m pytest -q tests
uv run --isolated --with pytest --with-requirements skills/<name>/tests/requirements.txt \
    python -m pytest -q skills/<name>/tests
python docs/hooks/skill_catalog.py          # refresh the tables above and docs/index.html
```

See [CONTRIBUTING.md](CONTRIBUTING.md) to add or change a skill.

## License

&copy; 2026 Databricks, Inc. All rights reserved. The source in this project is provided
subject to the [Databricks License](LICENSE.md). Portions are adapted from Vital Skills
(Databricks License); modified files say so in their header.

Public datasets referenced by skills and EnergyBench keep their own licenses and terms (EIA,
EPA, NREL, ISO/RTO market data, Equinor Volve, Texas RRC, and others). Check them before
redistribution.
