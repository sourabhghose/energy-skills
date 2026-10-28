# Combined Serverless Evaluation Job

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/references/combined-job.md); modified for the energy industry. -->

Use one three-task Lakeflow Jobs DAG after the two arm notebooks exist:

```text
baseline_arm ───┐
                ├── score_notebooks_and_outputs
with_skill_arm ─┘
```

The two arms have no dependencies and run in isolated serverless environments.
The scoring task uses `run_if: ALL_SUCCESS` and depends on both arms. It scores
the task-specific source sections of both notebooks together with their runtime
outputs and artifacts.

## Baseline knowledge boundary

The baseline notebook must be authored **before any process in its context reads
the target skill**. Disabling the skill after reading it is not a valid
baseline—the context is already contaminated.

Required sequence:

1. The evaluator reads `skill-eval` instructions, but does not open the target
   skill's `SKILL.md`, references, scripts, tests, or prior evaluation artifacts.
2. Start a fresh zero-inheritance agent/chat for baseline authoring. Its prompt
   contains only the task queries from `evalset.json`, dataset paths, output
   locations, and generic execution constraints. Do not pass the parent chat,
   `expectations.json`, scorer rules, or target-skill content.
3. The baseline author writes one linear notebook that tackles all eval tasks in
   order as independent from-scratch sections. It must not define shared helper
   functions derived from the target skill.
4. End the baseline authoring session. Only then may a separate candidate
   authoring session load the target skill and write the skill-enabled notebook.
5. Keep `eval/` outside the installed target skill in both arms.

If the baseline authoring context has already read the target skill, discard the
notebook and restart from a zero-inheritance session. Do not attempt to
"unlearn" or summarize away the leaked knowledge.

## Job design

Store the Jobs Submit API payload as `eval/job_design.json`:

```json
{
  "run_name": "paired-<skill>-eval",
  "tasks": [
    {
      "task_key": "baseline_arm",
      "notebook_task": {"notebook_path": "/Workspace/.../run_baseline_arm"},
      "environment_key": "baseline_env"
    },
    {
      "task_key": "with_skill_arm",
      "notebook_task": {"notebook_path": "/Workspace/.../run_with_skill_arm"},
      "environment_key": "candidate_env"
    },
    {
      "task_key": "score_notebooks_and_outputs",
      "depends_on": [
        {"task_key": "baseline_arm"},
        {"task_key": "with_skill_arm"}
      ],
      "run_if": "ALL_SUCCESS",
      "notebook_task": {"notebook_path": "/Workspace/.../score_<skill>"},
      "environment_key": "score_env"
    }
  ],
  "environments": [
    {"environment_key": "baseline_env", "spec": {"client": "4", "dependencies": []}},
    {"environment_key": "candidate_env", "spec": {"client": "4", "dependencies": []}},
    {"environment_key": "score_env", "spec": {"client": "4", "dependencies": ["mlflow[databricks]>=3.5.0"]}}
  ]
}
```

Validate without submitting:

```bash
python skills/skill-eval/scripts/run_combined_job.py \
  skills/<skill>/eval/job_design.json --profile <PROFILE> --dry-run
```

Create and run the ephemeral combined job:

```bash
python skills/skill-eval/scripts/run_combined_job.py \
  skills/<skill>/eval/job_design.json --profile <PROFILE>
```

The runner requires exactly two independent root tasks, one scoring task that
depends on both roots with `ALL_SUCCESS`, defined serverless environments, and
`client: "4"` for dependency installation.
