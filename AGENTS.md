# Energy Skills — Authoring Guide

Canonical guide for authoring energy-industry agent skills in this repository.
`CLAUDE.md` is only a compatibility import shim; update this file when authoring rules change.

Layout and tooling are adapted from
[Vital Skills](https://github.com/databricks-industry-solutions/vital-skills) (HLS), which
itself follows the open [Agent Skills](https://agentskills.io) specification.

## Directory Layout

```
├── AGENTS.md
├── templates/
│   ├── SKILL_TEMPLATE_PIPELINE.md  ← Pipeline
│   └── SKILL_TEMPLATE_GUIDE.md     ← Guide
├── benchmarks/energybench/         ← cross-skill benchmark (with vs. without skills)
└── skills/
    ├── ami-interval-analytics/
    ├── decline-curve-analysis/
    └── ...
```

Each skill lives at `skills/{skill-name}/SKILL.md`. Optional siblings:

| Directory | Use for | Published to UC? |
|-----------|---------|------------------|
| `references/` | On-demand markdown: standards summaries, decision tables, code lists | yes |
| `assets/` | Static templates / fixtures used as-is | yes |
| `scripts/` | Vetted, runnable entrypoints the agent **calls** | yes |
| `tests/` | Offline unit tests (pytest) + pinned `requirements.txt` | **no** |
| `eval/` | Benchmark harness and answer key (see `skills/skill-eval`) | **no** |

---

## The Energy Skill Contract

A general coding agent writes code that looks right. An energy skill makes it *right*: it
encodes the discipline an experienced energy data practitioner applies without thinking.
Every skill in this repo follows the same six rules.

### 1. Execute, don't reimplement

Domain logic lives in `scripts/` as tested functions. `SKILL.md` tells the agent to **call**
them and report their output, not to re-derive the SQL or the maths. State this near the top
of the Workflow section:

> **⛔ EXECUTE, DO NOT REIMPLEMENT.** Call the named entrypoints in `scripts/` and report their
> output. Do not hand-write the calculation, and do not pick a decision-point value yourself.

Split each script into two layers:

- **Core** (`scripts/<topic>_core.py` or similar): pure Python on pandas / numpy (scipy where
  needed). No Spark, no network, no Databricks SDK. This is what `tests/` exercises.
- **Runner** (`scripts/<topic>_run.py`): thin Databricks adapter. Reads Unity Catalog tables
  (via `spark` when present, else the Databricks SDK statement API), calls the core, writes
  results back to UC. Imports Spark / SDK lazily inside functions so the module imports
  offline.

### 2. Ask before assuming — preview, then build

Each skill names its **decision points**: choices that belong to the analyst, engineer, or
regulator, not to the agent (a b-factor bound, a Major Event Day method, an emission-factor
vintage, a weather station). Rules:

- Expose a **read-only** `preview_*` entrypoint that profiles the data and returns the
  options *with their consequences on this data* (e.g. SAIDI with and without MED exclusion).
  It builds nothing.
- Expose a `build_confirmed_*` / `run_confirmed_*` entrypoint that **requires** every decision
  as an explicit argument. Decision parameters have **no defaults**; a missing one raises
  `DecisionRequired` (a `ValueError` subclass) naming the decision and the options.
- List decision points in a `## Decision Points` table in `SKILL.md`: decision, options,
  governing standard, what changes.

### 3. Units, time, and identity are explicit

- Every numeric output carries its unit (column suffix `_mwh`, `_bbl_per_day`, `_tco2e`, or a
  `unit` column). Never infer a unit silently; when ambiguous, it is a decision point.
- Timestamps are timezone-aware. State the interval convention (interval-*ending* vs.
  interval-*beginning*) and handle DST transitions (the 23-hour and 25-hour days) explicitly.
- Never hallucinate identifiers (API well numbers, meter IDs, pricing nodes, tag names, EPA
  facility IDs, codes). Ground them in the data; report and exclude those not present.

### 4. Reproducible by construction

Every build writes a **run manifest** (JSON, also persisted as a UC table row or volume file)
with: inputs (table names + row counts), every decision and its chosen value, the standard /
factor-table version used, skill version, and timestamp. Re-running with the same manifest
reproduces the same output.

### 5. Governed by default

- Validate every UC identifier against `^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$` (back-quote
  when emitting). Pass values as SQL parameters — never splice user values into SQL text.
- Outputs are UC tables with column comments and a table comment naming the skill + version.
- Never hardcode tokens, hosts, or warehouse IDs; use ambient workspace auth, `profile=`, or
  env vars.
- Treat CEII (Critical Energy Infrastructure Information), customer meter data, and
  operator-confidential well data as sensitive: aggregate or mask in shareable outputs; route
  to `grid-data-guard` for de-identification.

### 6. Prove it

- Unit tests in `tests/` run offline with synthetic fixtures (no network, no Spark, no
  workspace). Tests that need Spark must `pytest.importorskip("pyspark")`.
- An `eval/` harness with 3–5 tasks run with and without the skill (see `skills/skill-eval`).
  Do **not** commit `eval_report.md`, `baseline_scores.json`, or `with_skill_scores.json`
  until a real paired run produced them. Never fabricate scores.

### Free text via `ai_query`

When a skill extracts facts from free text (drilling reports, work orders, outage notes,
permits), it must be **span-grounded**: the model returns a verbatim quote for each
extracted fact, and the core keeps the fact only if the quote is literally present in the
source text. Negation and subject ("no H2S observed", "offset well lost circulation") are
handled in the prompt and tested.

---

## Workflow: Topic → Skill

### Step 1. Choose the template

| Criteria | → Pipeline | → Guide |
|----------|------------|---------|
| Primary content | Tool calls, code, entrypoints | Concepts, decision frameworks |
| User action | "Run this analysis" | "Decide how to approach this" |

Pipeline: `templates/SKILL_TEMPLATE_PIPELINE.md`. Guide: `templates/SKILL_TEMPLATE_GUIDE.md`.

### Step 2. Author the skill

1. Copy the template into `skills/{skill-name}/SKILL.md`.
2. Folder name must match frontmatter `name` (lowercase, hyphens, ≤ 64 chars).
3. Keep `SKILL.md` ≤ ~400 lines; put long tables, code lists, and standards notes in
   `references/`.
4. Add `## Decision Points` (rule 2) and `## Related Skills` sections.

### Step 3. Description rules

The `description` field is the discovery hook agents read before loading the full file.

- ≤ 1024 characters; tool/domain keywords in the **first 120 characters**.
- Lead with keywords, not stop verbs (`Use`, `A`, `An`, `The`, `Query`, `Fetch`, `Run`).
- Put disambiguation (`For X use Y`) at the **end**.
- No promotional adjectives (`powerful`, `comprehensive`, `state-of-the-art`).
- `category`: one of `"Power & Utilities"`, `"Oil & Gas"`, `"Renewables & Markets"`,
  `"Emissions & ESG"`, `Others`. Quote values containing `&`.
- `summary`: one-line outcome for the README and landing page (≤ 200 chars; quote if it
  contains a colon).
- After adding or changing a skill, run `python docs/hooks/skill_catalog.py`.

### Step 4. Code quality

- Functions < 50 lines, files < 800 lines, ≤ 4 levels of nesting.
- Don't mutate inputs: return new DataFrames / dicts (`df.assign(...)`, `{**d, "k": v}`).
- No silent `except`: log with context or re-raise.
- No stray `print` in core modules; runners may print the user-facing readout.
- Each script starts with a docstring: purpose + usage.

### Step 5. Testing and evaluation

1. `python tests/test_skill_quality.py skills/my-skill/SKILL.md` validates format.
2. `uv run --isolated --with pytest --with-requirements skills/my-skill/tests/requirements.txt python -m pytest -q skills/my-skill/tests`
3. Ensure the skill loads in Genie Code; design 3–5 eval tasks in `eval/`.
4. Report Genie Code performance with and without the skill (`skills/skill-eval`).

---

## Quality Checklist

- [ ] Frontmatter has `name`, `description`, `category`, `summary`, `author`, `version`, `license`
- [ ] `name` matches parent folder
- [ ] "When to Use" written from the user's task perspective (5+ items)
- [ ] `## Decision Points` table; decision params have no defaults in `build_confirmed_*`
- [ ] Units, timezones, and interval conventions explicit
- [ ] References cite sources with URLs; paywalled standards (IEEE, IEC, API, ISO) are
      summarized in our own words, never copied
- [ ] Offline unit tests pass; `eval/` has evalset, expectations, data generator, scorers

---

## Progressive Disclosure

1. **Metadata** — `name` + `description` for discovery
2. **Instructions** — full `SKILL.md` when activated
3. **Resources** — `references/`, `assets/`, `scripts/` only as needed
