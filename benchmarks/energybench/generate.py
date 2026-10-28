#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Materialise tier-P (planted-truth) tasks: seeded synthetic data for the agent, answer key for the grader.

Agent-visible files go to $EB_HOME/data/<task>/. The rendered prompt, rubric, task.toml and answer key go to
$EB_GRADING/<task>/ (see paths.py). The same --seed always produces byte-identical data and the same key.

    uv run generate.py --all                    # every tier-P task, covered and control
    uv run generate.py --skill reliability-metrics --controls 4
    uv run generate.py p01-ami-dst --force      # regenerate one task
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import taskset  # noqa: E402
from generators import GENERATOR_VERSION, REGISTRY  # noqa: E402
from paths import EB_GRADING, EB_HOME, file_hashes, write_grading  # noqa: E402

DEFAULT_SEED = 20261028


def materialise(task_id: str, seed: int, home: Path = EB_HOME, grading_root: Path = EB_GRADING,
                force: bool = False) -> tuple[Path, dict]:
    """Generate one task. Returns (data dir, answer key). Writes into a staging folder first, so a failing
    generator never leaves a half-written data folder behind."""
    spec = taskset.load_spec(task_id)
    errors = taskset.validate_spec(task_id, spec, REGISTRY)
    if errors or spec["task"]["tier"] != "P":
        raise SystemExit(f"{task_id}: not a valid tier-P task: {errors or 'tier R; use fetch.py'}")
    data = home / "data" / task_id
    if data.exists() and not force:
        raise FileExistsError(f"{data} exists; pass --force to regenerate")
    staging = home / "staging" / task_id
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    key = REGISTRY[spec["task"]["generator"]](staging, seed)
    manifest = {"task": task_id, "tier": "P", "seed": seed, "generator": spec["task"]["generator"],
                "generator_version": GENERATOR_VERSION, "files": file_hashes(staging)}
    if data.exists():
        _make_writable(data)
        shutil.rmtree(data)
    data.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(staging), str(data))
    write_grading(task_id, taskset.TASKS_DIR / f"{task_id}.toml", taskset.render_instruction(spec),
                  spec["task"]["rubric"], key, manifest, grading_root)
    return data, key


def _make_writable(root: Path) -> None:
    """run.py makes task data read-only; regeneration needs write access back."""
    for p in [root, *root.rglob("*")]:
        p.chmod(0o755 if p.is_dir() else 0o644)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*", help="task ids")
    ap.add_argument("--all", action="store_true", help="every tier-P task in tasks.json")
    ap.add_argument("--skill", help="the tier-P tasks labeled as covered by this skill")
    ap.add_argument("--controls", type=int, help="number of control tasks to add (default: all)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="data seed (pinned in every run.json)")
    ap.add_argument("--select-seed", type=int, default=20261014, help="must match run.py --seed with --controls")
    ap.add_argument("--force", action="store_true", help="overwrite existing data")
    args = ap.parse_args()
    tasks = args.tasks
    if not tasks and (args.all or args.skill or args.controls is not None):
        tasks = taskset.select(taskset.load()["tasks"], args.skill, args.controls, args.select_seed, tier="P")
    if not tasks:
        ap.error("pass task ids, --all or --skill")
    for task_id in tasks:
        try:
            data, _ = materialise(task_id, args.seed, force=args.force)
        except FileExistsError as e:
            print(f"{task_id}: skipped ({e})")
            continue
        print(f"{task_id}: data -> {data}, grading -> {EB_GRADING / task_id}")


if __name__ == "__main__":
    main()
