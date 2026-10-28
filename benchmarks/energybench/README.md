# EnergyBench: test Energy Skills with and without the skills

Adapted from the BiomniBench harness in [Vital Skills](https://github.com/databricks-industry-solutions/vital-skills/tree/main/benchmarks/biomnibench); modified for the energy industry.

No public benchmark covers energy-industry data analysis, so EnergyBench defines its own tasks. It runs
[Genie Code CLI](https://docs.databricks.com/aws/en/genie-code/genie-code-cli) on each task with and without the
skills in this repository, grades both arms the same way, and compares the scores.

## Two tiers of tasks

- **Tier P: planted truth (32 tasks).** `generate.py` writes seeded synthetic datasets with a known answer, and
  each one carries a pitfall that experienced practitioners avoid and general coding agents tend to hit: the
  repeated hour at the DST fall-back, register rollover and meter exchanges, IEEE 1366 Major Event Days, unbounded
  Arps b-factors, MW vs MWh, MMcf vs Mcf, interval-ending price timestamps, location- vs market-based Scope 2,
  curtailment vs underperformance, look-ahead leakage in load-forecast backtests, negated phrases in drilling
  reports, LAS depth and porosity units, API numbers that lost their leading zero, ESP tags renamed mid-series,
  and CEII coordinates in a file meant to leave the company. Deterministic checks (`scoring.py`) compare
  `answer.json` with the answer key within tolerances. `decision` checks test **ask-before-assuming**: did the
  agent record the choice that belonged to the requester, such as the eGRID edition or the GWP set? A blinded LLM
  judge grades the trace against a rubric. Twenty-four tasks cover the fifteen domain skills; eight **controls**
  are energy-flavoured but generic (aggregation, plotting, text counting) for the no-harm check.
- **Tier R: real public data (10 tasks).** `fetch.py` downloads pinned public datasets (EIA, EPA, CAISO OASIS,
  Kelmarsh SCADA, NREL NSRDB, Low Carbon London, Texas RRC, Equinor Volve), and an LLM judge grades each task
  against an expert-style rubric only.

## How it works

1. **Prepare.** `generate.py` (tier P) or `fetch.py` (tier R). Data the agent may see goes to
   `$EB_HOME/data/<task>/`. The rendered prompt, rubric, checks and answer key go to `$EB_GRADING/<task>/`, away
   from every run folder.
2. **Label.** `label.py` asks two different LLMs which skills apply, from the task prompt and each skill's
   `description` only. A task is **covered** when both name a shared skill, **control** when both name none, and
   **disputed** otherwise. Disputed tasks are never run. *`tasks.json` currently holds the task authors' intended
   labels (`labels.method` says so). Run `label.py --write` before the first scored study.*
3. **Run.** `run.py` runs every (task, arm, replicate) in a fresh folder with read-only hard links to the data,
   its own Python, and, in skills arms, the skills at a pinned commit (without `eval/` and `tests/`). The order is
   seeded.
4. **Judge.** `judge.py` scores deterministic checks first. It then removes skill names, skill paths and the
   agent's name from the trace and answer, grades each run `--repeats` times against the rubric, and runs four
   behaviour checks: units explicit, time convention stated, decision surfaced, validation performed. Run score =
   `det_weight` × checks + (1 − `det_weight`) × rubric.
5. **Analyze.** `analyze.py` reports paired per-task deltas with a two-level bootstrap CI, the Improves and No-harm
   gates, the ask-before-assuming rate, how often each arm opened a skill, and token and time cost.

## Prerequisites

- [Genie Code CLI](https://docs.databricks.com/aws/en/genie-code/genie-code-cli#install-and-set-up). Run `genie`
  once and finish onboarding to a Databricks CLI profile.
- [uv](https://docs.astral.sh/uv/). Each script declares its own dependencies; the harness needs Python ≥ 3.11.
- A Databricks CLI profile whose workspace serves the judge and labeler endpoints (defaults:
  `databricks-gemini-3-8-flash`, `databricks-claude-sonnet-5-5`). Choose a judge from a different model family
  than the agent's.
- Tier R only: `NREL_API_KEY` and `NREL_EMAIL` for NSRDB (free key from NREL), and manual downloads for Volve
  (registration) and Texas RRC PDQ (browser download). `fetch.py` prints where to place them.

`EB_HOME` (default `~/energybench`) holds data, runs, grades and analyses. `EB_GRADING` (default
`~/.cache/energybench-grading`) holds prompts, rubrics and answer keys.

## Test one skill

Run from this folder. Arms are `no_skills` or `NAME=GIT_REF[:INSTRUCTIONS]`. `instructions/D0.md` is a one-line
`AGENTS.md` that points the agent at the matching skill before it writes analysis code.

```bash
# 1. Prepare the covered tasks plus 4 controls (same --select-seed / --seed as run.py)
uv run generate.py --skill reliability-metrics --controls 4
# 2. Run both arms, 3 replicates each
uv run run.py --run-id rel --skill reliability-metrics --controls 4 --tier P \
  --arm no_skills --arm skills=main:D0 --reps 3 --jobs 2
# 3. Grade: deterministic checks + 5 judge repeats per answer
uv run judge.py --run-id rel --out rel --profile <profile>
# 4. Compare
uv run analyze.py --grades rel --out rel --a skills --b no_skills --skill reliability-metrics
```

For a quick, offline-gradable signal, `judge.py --no-llm` scores the deterministic checks only. Those runs are
marked incomplete and `analyze.py` excludes them from the gated comparisons. Use them for debugging, not for claims.

The report goes to `$EB_HOME/analysis/<out>/analysis.md`:

| Comparison | Tasks | Rule |
|---|---|---|
| Improves | covered | effect ≥ +5 points, 95% CI low end above −5, no task down more than 15 |
| No harm | control | effect above −5, no task down more than 15 |
| All | covered + control | descriptive |
| Deterministic only | covered | descriptive, checks score alone |

A passing Improves comparison whose skills arm uses more than 30% more tokens is reported as
"PASS on score, FAILS cost guardrail".

## Tasks

| Task | Tier | Domain | Intended skills | What it tests |
|---|---|---|---|---|
| `c01-fuel-mix` | P | Control | control | Wind and solar share of state generation |
| `c02-price-plot` | P | Control | control | Plot residential retail prices by state |
| `c03-ev-chargers` | P | Control | control | DC fast charging ports by city |
| `c04-tariff-bill` | P | Control | control | Residential bill under a tiered tariff |
| `c05-press-mentions` | P | Control | control | Hydrogen mentions in press releases |
| `c06-gasoline-yoy` | P | Control | control | Year-over-year gasoline price change |
| `c07-trir` | P | Control | control | Contractor total recordable incident rate |
| `c08-refinery-dedupe` | P | Control | control | Deduplicate a refinery list |
| `p01-ami-dst` | P | Power & Utilities | ami-interval-analytics | Daily energy from 15-minute AMI data across the DST fall-back |
| `p02-ami-rollover` | P | Power & Utilities | ami-interval-analytics | Quarterly consumption from cumulative register reads |
| `p03-reliability-med` | P | Power & Utilities | reliability-metrics | 2024 SAIDI and SAIFI with and without Major Event Days |
| `p04-reliability-caidi` | P | Power & Utilities | reliability-metrics | System SAIDI, SAIFI and CAIDI from feeder events |
| `p05-load-leakage` | P | Power & Utilities | load-forecaster | Day-ahead load forecast backtest without leakage |
| `p06-ceii-share` | P | Power & Utilities | grid-data-guard | Shareable feeder summary without CEII or customer PII |
| `p07-wildfire-miles` | P | Power & Utilities | wildfire-asset-risk | Overhead circuit miles in Tier 3 High Fire-Threat District |
| `p08-iso-interval-ending` | P | Renewables & Markets | iso-market-data | Hourly real-time prices from 5-minute interval-ending LMPs |
| `p09-iso-settlement` | P | Renewables & Markets | iso-market-data | Two-settlement energy charges for a load-serving entity |
| `p10-dca-eur` | P | Oil & Gas | decline-curve-analysis | EUR from monthly production with a terminal decline |
| `p11-boe` | P | Others | unit-guard | Total BOE across operators reporting gas in different units |
| `p12-las-netpay` | P | Oil & Gas | well-log-ingest | Net pay from LAS files with mixed depth and porosity units |
| `p13-density-porosity` | P | Oil & Gas | well-log-ingest | Average density porosity across vendor mnemonics |
| `p14-drilling-npt` | P | Oil & Gas | drilling-report-npt | Non-productive time from free-text drilling reports |
| `p15-well-identity` | P | Oil & Gas | osdu-ppdm-mapper | Reconcile wells and wellbores across two systems by API number |
| `p16-esp-failures` | P | Oil & Gas | equipment-pdm | Which ESPs are likely to fail in the next two weeks |
| `p17-wind-curtailment` | P | Renewables & Markets | wind-solar-performance | Separate curtailment losses from turbine underperformance |
| `p18-solar-pr` | P | Renewables & Markets | wind-solar-performance | PV plant performance ratio, raw and temperature-corrected |
| `p19-capacity-factor` | P | Renewables & Markets | wind-solar-performance, unit-guard | Annual generation and capacity factor from 15-minute output |
| `p20-scope2` | P | Emissions & ESG | ghg-emissions-calculator | Scope 2 emissions, location-based and market-based |
| `p21-scope1` | P | Emissions & ESG | ghg-emissions-calculator | Scope 1 stationary combustion with mixed fuel units |
| `p22-methane` | P | Emissions & ESG | ghg-emissions-calculator | Annual methane emissions from component counts |
| `p23-heat-rate` | P | Others | energy-semantic-builder | Net heat rate and capacity factor KPIs for a generation fleet |
| `p24-gas-units` | P | Others | unit-guard | Sales-gas energy across US and Canadian unit systems |
| `r01-eia930-ercot-peak` | R | Power & Utilities | load-forecaster | ERCOT peak demand and data quality from EIA-930 |
| `r02-eia861-reliability` | R | Power & Utilities | reliability-metrics | Utility reliability rankings from EIA-861 |
| `r03-egrid-scope2` | R | Emissions & ESG | ghg-emissions-calculator | Location-based Scope 2 with real eGRID2023 factors |
| `r04-ghgrp-subpart-w` | R | Emissions & ESG | ghg-emissions-calculator | Petroleum and natural gas systems emissions from GHGRP |
| `r05-kelmarsh-performance` | R | Renewables & Markets | wind-solar-performance | Kelmarsh wind farm 2022 performance and lost energy |
| `r06-caiso-np15-dam` | R | Renewables & Markets | iso-market-data | CAISO NP15 day-ahead prices, January 2024 |
| `r07-london-ami-profiles` | R | Power & Utilities | ami-interval-analytics | Half-hourly smart meter profiles by tariff |
| `r08-nsrdb-pv-yield` | R | Renewables & Markets | wind-solar-performance | Expected PV yield from NSRDB irradiance |
| `r09-volve-dca` | R | Oil & Gas | decline-curve-analysis | Decline analysis on Volve well 15/9-F-14 |
| `r10-rrc-production-trend` | R | Oil & Gas | decline-curve-analysis, unit-guard | Permian Basin production trend from Texas RRC data |

## Datasets (tier R)

Every URL was checked on 2026-10-28 and returned the expected content type. On the first fetch,
`fetch.py --write-lock` records each file's SHA-256 in `datasets.lock.json`, and later fetches must match it. No
lock is committed yet because nothing has been fetched for a scored study.

| Dataset | Source | License | Access |
|---|---|---|---|
| `eia930_balance_2024h1` | EIA-930 Hourly Electric Grid Monitor, six-month balance file | Public domain (U.S. Government) | direct |
| `eia861_2023` | EIA-861 annual file (archive URL, stable) | Public domain (U.S. Government) | direct |
| `egrid2023` | EPA eGRID2023 rev 2 data file | Public domain (U.S. Government) | direct |
| `ghgrp_2023_summary` | EPA GHGRP 2023 data summary spreadsheets | Public domain (U.S. Government) | direct |
| `kelmarsh_2022` | Kelmarsh wind farm SCADA, Zenodo record 16807551 | CC BY 4.0 | direct (~485 MB) |
| `caiso_np15_dam_2024_01` | CAISO OASIS `PRC_LMP` DAM, TH_NP15_GEN-APND | CAISO terms of use | direct, rate-limited; pinned on extracted CSV |
| `london_lcl` | Low Carbon London smart meter data (London Datastore) | TODO verify on the dataset page | direct (large) |
| `nsrdb_psm3_2022` | NREL NSRDB PSM v3.2.2 API (`developer.nlr.gov`) | NREL NSRDB terms | API key (`NREL_API_KEY`, `NREL_EMAIL`) |
| `rrc_pdq` | Texas RRC Production Data Query dump (MFT link) | Texas public information | manual browser download; republished monthly |
| `volve` | Equinor Volve data village | Equinor Open Data Licence | manual, registration required |

ERCOT public reports are not included: the ERCOT public API needs a registered subscription key, and the portal
refused unauthenticated requests when checked.

## Reproducibility

| What | Where it is pinned |
|---|---|
| Tier-P data | `--seed` and `GENERATOR_VERSION`, recorded in `data_manifest.json`, and a `data_version` hash in every `run.json` |
| Tier-R data | SHA-256 in `datasets.lock.json` |
| Skills | each arm's ref resolved to a commit SHA and skills tree hash before the first run |
| Instruction file | its SHA-256 |
| Task labels | `tasks.json` `labels` (skills SHA, labelers, prompt hash) |
| Run order | `--seed`; the schedule is written before the first run |
| Agent | Genie Code CLI version and model |
| Judge | endpoint, repeats and prompt hash in `grades/<out>/meta.json` |
| Statistics | bootstrap seed, margin and drop thresholds in `analyze.py` |

## Guardrails

- **No answer key in reach.** Answer keys, rubrics and checks stay in `EB_GRADING`. `judge.py` flags any run whose
  events mention the grading folder, `answer_key.json`, `rubric.txt` or this repository's `tasks/` folder, and
  `analyze.py` excludes those runs and lists them. Generators never write pitfall values into agent data (tested).
- **No leakage between arms.** Genie runs with the profile `energybench`, which turns off personal skills and
  memories. `run.py` stops if a personal skill has the same name as an Energy Skill.
- **Infrastructure failures are not scores.** Rate-limited runs are retried, then excluded and listed. Network
  failures are moved to `infra-failed/` and rerun on the next call. Timeouts and missing answers score 0.
- **No fabricated results.** This folder ships no grades, runs or analyses. Every number in a report must come
  from a run of the commands above.

## Limits

- Tier-P tasks are synthetic. They test whether the agent applies domain discipline, not whether it can handle
  every quirk of real operator data. Tier R covers that, but with rubric grading only.
- Each domain skill has one to three covered tasks, so only large effects are detectable per skill. Pool skills
  for a study-level claim and report per-skill results as descriptive.
- `decision` checks match keywords in `decisions`. An agent can name a decision without making it well; the rubric
  and the `decision_surfaced` behaviour check cover quality.
- Coverage labels are design intent until `label.py` runs.

## Tests

Offline (no network, Genie or Databricks). Generator cross-checks with pandas run only when pandas is installed.

```bash
uv run --isolated --with pytest --with pyyaml python -m pytest -q benchmarks/energybench/tests
uv run --isolated --with pytest --with pyyaml --with numpy --with pandas python -m pytest -q benchmarks/energybench/tests
```
