#!/usr/bin/env python3
# Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/scripts/run_combined_job.py); modified for the energy industry.
"""Validate and submit a three-task paired skill-evaluation job."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def validate_job(spec: dict) -> None:
    tasks = spec.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 3:
        raise ValueError("combined eval job must define exactly three tasks")

    task_keys = [task.get("task_key") for task in tasks]
    if len(set(task_keys)) != 3 or any(not key for key in task_keys):
        raise ValueError("all three tasks need unique non-empty task_key values")

    roots = [task for task in tasks if not task.get("depends_on")]
    downstream = [task for task in tasks if task.get("depends_on")]
    if len(roots) != 2 or len(downstream) != 1:
        raise ValueError("job must have two independent arm tasks and one dependent scoring task")

    score_task = downstream[0]
    dependencies = {item.get("task_key") for item in score_task["depends_on"]}
    root_keys = {task["task_key"] for task in roots}
    if dependencies != root_keys:
        raise ValueError("scoring task must depend on both arm tasks and no other tasks")
    if score_task.get("run_if", "ALL_SUCCESS") != "ALL_SUCCESS":
        raise ValueError("scoring task must use run_if=ALL_SUCCESS")

    environments = spec.get("environments")
    if not isinstance(environments, list) or not environments:
        raise ValueError("serverless job needs environment definitions")
    environment_keys = {environment.get("environment_key") for environment in environments}
    for task in tasks:
        if task.get("environment_key") not in environment_keys:
            raise ValueError(f"task {task['task_key']} references an undefined environment")
    for environment in environments:
        if str(environment.get("spec", {}).get("client")) != "4":
            raise ValueError("every serverless environment must set spec.client to '4'")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate and submit a combined paired skill-evaluation job."
    )
    parser.add_argument("job_json", type=Path)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    spec = json.loads(args.job_json.read_text(encoding="utf-8"))
    validate_job(spec)
    if args.dry_run:
        print(json.dumps(spec, indent=2))
        return

    completed = subprocess.run(
        [
            "databricks",
            "jobs",
            "submit",
            "--no-wait",
            "--profile",
            args.profile,
            "--json",
            f"@{args.job_json.resolve()}",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    print(completed.stdout.strip())


if __name__ == "__main__":
    main()
