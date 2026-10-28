# Error Analysis Worksheet

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/references/error-analysis.md); modified for the energy industry. -->

Referenced from SKILL.md Step 7. Method: open coding → axial coding (Hamel Husain). The failure
taxonomy is the deliverable; win rates only show where to look.

## Open Coding (per trace)

Read every task that ended `tie-fail` or `regression` in either arm. Fill one row each. Annotate
the **first** observed failure; downstream errors cascade from it.

| task_id | arm | first failure observed (free text) | where in session (early/mid/late) | severity (blocks task / degrades) |
|---------|-----|------------------------------------|-----------------------------------|-----------------------------------|
| | | | | |

Rules:

- One domain expert writes the notes (a reliability engineer for SAIDI tasks, a reservoir
  engineer for decline curves). Don't outsource annotation; the notes feed the fix loop.
- Free text, concrete: "summed 96 intervals on the 25-hour day, dropping 1 h" not "bad DST handling".
- Read ≥ 5-10 traces before grouping (across both arms is fine at this scale).

## Axial Coding (grouping)

| failure mode | definition | count | example task_ids | arm(s) affected |
|--------------|-----------|-------|------------------|-----------------|
| | | | | |

## Energy Seed Taxonomy

Start grouping against these; add modes as you see them.

| failure mode | signature |
|--------------|-----------|
| dst-interval-mishandled | 25-hour or 23-hour day collapsed to 24 h; naive timestamps; duplicated or fabricated hour |
| interval-convention-confused | interval-beginning treated as interval-ending (or vice versa); off-by-one-interval totals |
| unit-confusion | MW vs. MWh, kW vs. kWh, Mcf vs. MMBtu vs. boe, short vs. metric tons, ft vs. m depth |
| silent-conversion-assumption | boe 6:1, heat content, GWP vintage (AR4/AR5/AR6) applied without saying so |
| decision-made-silently | agent picked an analyst decision (MED method, b bound, factor vintage, weather station) without asking |
| standard-misapplied | IEEE 1366, IEC 61400-12, EPA Subpart W, or PRMS definition used incorrectly |
| wrong-identifier-resolution | API well number, meter ID, pricing node, tag, or EPA facility ID mapped to the wrong entity |
| fabricated-identifier | well, node, tag, or facility that doesn't exist in the data |
| fabricated-numbers | numeric results not traceable to actual output |
| fabricated-reference | cited standard clause, dataset, or URL does not exist |
| temporal-leakage | random train/test split, future weather used as a feature, look-ahead in backtest |
| quality-flags-ignored | estimated / substituted reads, null sentinels (-999.25), or shut-in months treated as real data |
| skipped-analysis-step | required step (VEE, outlier screen, terminal decline) silently omitted |
| sensitive-data-exposed | CEII asset locations or customer meter-level data surfaced in a shareable output |
| reimplemented-vetted-logic | agent hand-wrote the calculation instead of calling the skill's entrypoint |
| scale-blindness | works on one meter or well; infeasible on a full AMI or field dataset |
| premature-stop | session ended with the task partly done, presented as complete |
| context-loss | later steps contradict earlier results in the same session |

## Feeding Back

1. Taxonomy rows where `arm = with_skill` → fix targets for the skill (description, workflow,
   guardrails, entrypoint validation).
2. Rows where the skill **eliminated** a baseline mode → the evidence section of the report.
3. Persistent modes → promote to a deterministic scorer or judge (`scorer-pack.md`). Modes seen
   once → fix directly.

## Cadence

- Per skill change: re-read losses only (Recipe: Regression Re-Run).
- Per release: full worksheet across all skills in the release.
