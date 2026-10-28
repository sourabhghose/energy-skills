# energy-foundation-models Skill Evaluation

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/accelerators/eval/README.md); modified for the energy industry. -->

Benchmark for the `energy-foundation-models` skill following the
[skill-eval](../../skill-eval/SKILL.md) methodology: run Genie Code on each task with and
without the skill and score both arms the same way. **No scores have been recorded yet**;
`eval_report.md`, `baseline_scores.json` and `with_skill_scores.json` are written only after
a real paired run.

## Benchmark Tasks

| task_id | difficulty | task | discriminator |
|---------|-----------|------|---------------|
| efm-001 | hard | Day-ahead feeder load endpoint with temperature forecast covariates | picks a covariate-capable model, pins revision, UTC, seasonal-naive backtest, inference tables |
| efm-002 | edge | "Use Moirai for our trading desk's LMP forecasts" | flags CC-BY-NC weights; no clipping of negative prices |
| efm-003 | edge | "Register TimesFM 3.0 for production" | flags the non-commercial 3.0 weights; offers 2.5 |
| efm-004 | medium | Chronos-Bolt on naive local-time historian export, compare to last week | DST repeated/missing hour; weekly seasonal-naive backtest |
| efm-005 | medium | Prithvi burn scars on HLS S30 chips | S30 band codes (B8A/B11/B12), GPU batch Job not serving |

## Data

Synthetic only (`generate_data.py`, seed 20261028): feeder load + temperature, LMPs with
negative hours, a naive-local-time substation export spanning both 2026 US DST transitions,
and an HLS S30 chip manifest (no imagery; efm-005 is graded on the plan).

Volume: `/Volumes/<catalog>/energy_skills/eval/energy_foundation_models/` (set
`SKILL_EVAL_DATA_DIR`; replace `<catalog>` in `evalset.json` queries).

## Scorer Summary

| scorer | level | type | checks |
|--------|-------|------|--------|
| artifact_produced | L1 | deterministic | answer file exists and is non-empty |
| required_patterns | L1 | deterministic | every group in `deterministic_checks.required_patterns` matches |
| no_forbidden_content | L1 | deterministic | no forbidden pattern (e.g. `revision="main"`) |
| decisions_surfaced | L2 | LLM judge | user-owned decisions are asked or stated as assumptions |
| factually_grounded | L2 | LLM judge | no contradiction of expected facts or guidelines |

Judge model: `databricks:/databricks-gpt-5-mini` (must differ from the Genie Code model).
Pass rule: all metrics.

## Ship Gate

`win_rate > 0` and zero regressions at any difficulty.

## Run Protocol

1. **Seed data**: `SKILL_EVAL_DATA_DIR=/Volumes/... python3 generate_data.py`.
2. **Baseline arm**: make sure `energy-foundation-models` is not in any registered skill
   folder; fresh Genie Code chat per task; paste the query verbatim; move `outputs/*.md` to
   `outputs/baseline/`.
3. **Candidate arm**: register the skill (without `eval/`), hard-refresh, repeat in fresh
   chats; move outputs to `outputs/with_skill/`.
4. **Score**: `mlflow.genai.evaluate(data=..., scorers=scorers.scorers)` for each arm.
5. **Report**: write `eval_report.md` from the paired comparison and failure taxonomy.

Genie Code keeps memories across chats: ask it to delete memories about this eval before each arm.
