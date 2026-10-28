# energy-accelerators Skill Evaluation

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/accelerators/eval/README.md); modified for the energy industry. -->

Benchmark for the `energy-accelerators` skill following the [skill-eval](../../skill-eval/SKILL.md)
methodology. Tests whether Genie Code steers to the right verified accelerator (or honestly
says none exists) and ends with a precise next step, instead of building from scratch or
inventing a repo. **No scores have been recorded yet**; `eval_report.md` and score files are
written only after a real paired run.

## Benchmark Tasks

| task_id | difficulty | task | discriminator |
|---------|-----------|------|---------------|
| ea-001 | easy | Production optimization app with decline curves | Energy Sandbox Production Optimizer + `decline-curve-analysis` |
| ea-002 | medium | On-prem PI System data into Databricks | no managed PI Lakeflow connector; AVEVA CONNECT Delta Sharing; custom connector |
| ea-003 | hard | Pole / transformer replacement plan vs SAIDI | ARMOR; predicted contributions vs reported IEEE 1366 |
| ea-004 | edge | "Use Mosaic" for DEM → H3 flood risk | Mosaic end of support → GeoBrix; Flood Prediction accelerator |
| ea-005 | edge | Subpart W accelerator | none verified; route to `ghg-emissions-calculator`; no invented repo |

## Data

Synthetic only (`generate_data.py`): 24 synthetic wells of monthly production with IDs
prefixed `SYN-` for ea-001. The other tasks need no data.

## Scorer Summary

| scorer | level | type | checks |
|--------|-------|------|--------|
| artifact_produced | L1 | deterministic | answer file exists and is non-empty |
| required_patterns | L1 | deterministic | every required pattern group matches |
| no_forbidden_content | L1 | deterministic | no forbidden pattern (e.g. Mosaic install as the path, invented repo) |
| precise_next_step | L2 | LLM judge | answer ends with a concrete command or named-role action |
| factually_grounded | L2 | LLM judge | no contradiction of expected facts or guidelines |

Judge model: `databricks:/databricks-gpt-5-mini`. Pass rule: all metrics.

## Ship Gate

`win_rate > 0` and zero regressions at any difficulty.

## Run Protocol

1. Seed data: `SKILL_EVAL_DATA_DIR=/Volumes/... python3 generate_data.py`.
2. Baseline arm: skill not registered; fresh Genie Code chat per task; paste queries verbatim; move outputs to `outputs/baseline/`.
3. Candidate arm: register the skill (without `eval/`), hard-refresh, repeat; move outputs to `outputs/with_skill/`.
4. Score both arms with `mlflow.genai.evaluate(..., scorers=scorers.scorers)`.
5. Write `eval_report.md` from the paired comparison and failure taxonomy.

Accelerators change: re-verify cards (`references/accelerators/*.md`, `Reviewed:` line) before each eval run.
