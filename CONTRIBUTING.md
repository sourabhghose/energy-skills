# Contributing

## Add or update a skill

1. Follow the authoring guide and the Energy Skill Contract in [AGENTS.md](AGENTS.md).
2. Start from the matching template in `templates/` (pipeline or guide).
3. Put the skill at `skills/<skill-name>/SKILL.md`.
4. Folder name must match frontmatter `name`. Set `category` and `summary` (the public table
   blurb). Check format with `python tests/test_skill_quality.py skills/<skill-name>`.
5. Run `python docs/hooks/skill_catalog.py` to refresh the skill table in `README.md` and
   `docs/index.html`.
6. Open a PR and request a second-party review, ideally from someone who has done the work
   the skill encodes (a reservoir engineer for decline curves, a reliability engineer for
   IEEE 1366, and so on).

## Test

#### 1. Repo-level tests

- `tests/test_skill_quality.py`: frontmatter and required sections for every skill
- `tests/test_skill_catalog.py`: README / landing page match `skills/*/SKILL.md`
- `tests/test_sync_bundle.py`: `eval/` and `tests/` are never published to Unity Catalog

```bash
uv run --isolated --with pytest --with pyyaml python -m pytest -q tests
```

#### 2. Skill-level unit tests

Offline only: synthetic fixtures, no network, no workspace. Pin test dependencies in
`skills/<name>/tests/requirements.txt`.

```bash
uv run --isolated --with pytest --with-requirements skills/<name>/tests/requirements.txt \
    python -m pytest -q skills/<name>/tests
```

CI (`.github/workflows/ci.yml`) discovers every `skills/*/tests/` folder, runs each in its own
environment, and scans history for secrets with gitleaks.

#### 3. Evaluate with and without the skill

A skill must make the agent measurably better at its task. Benchmark it on 3–5 tasks by running
Genie Code twice per task (skill on, skill off) and scoring both runs the same way. The
[skill-eval](skills/skill-eval/SKILL.md) skill builds the harness:

```text
skills/<skill-name>/eval/
├── README.md               # run protocol, scorer summary, ship gate
├── evalset.json            # 3-5 benchmark task definitions (task_id, dataset, query)
├── expectations.json       # difficulty, expectations, deterministic checks per task
├── generate_data.py        # seeded synthetic data with planted truth
├── scorers.py              # deterministic checks + LLM judge guidelines
├── eval_report.md          # after a real run only: paired comparison + failure taxonomy
├── baseline_scores.json    # after a real run only
└── with_skill_scores.json  # after a real run only
```

> [!WARNING]
> **`eval/` holds the answer key.** It is excluded from the Unity Catalog bundle. Never copy
> expectations into `references/`, and never commit scores that a real run did not produce.

For cross-skill evaluation on public data, see [EnergyBench](benchmarks/energybench/README.md).

## Data and confidentiality

This repository is public. Do not commit CEII, customer meter-level data, operator-confidential
well or production data, credentials, or customer names. Use synthetic data or public datasets
and link to their sources.

## Contributor terms

By submitting a contribution you certify that you have the right to submit it, that it is
licensed under the same terms as the rest of the project, and that it contains no confidential
or proprietary information.
