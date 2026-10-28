#!/usr/bin/env python3
"""Check a skill's eval/ folder against the skill-eval convention.

Checks:
  - required files exist (README.md, evalset.json, expectations.json, scorers.py,
    generate_data.py)
  - evalset.json and expectations.json are JSON arrays that join one-to-one on
    (task_id, dataset)
  - 3-5 tasks, each with a non-empty query; difficulty in easy/hard/edge, with
    at least one easy and one hard-or-edge task
  - evalset.json carries no answer-key fields (expectations, difficulty, ...)
  - score files and eval_report.md appear together or not at all, so no
    result is committed without the run that produced it

Stdlib only.

Usage:
  python validate_eval_dir.py skills/<skill>/eval
  python validate_eval_dir.py skills/<skill>/eval --allow-missing generate_data.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REQUIRED_FILES = ("README.md", "evalset.json", "expectations.json", "scorers.py", "generate_data.py")
RESULT_FILES = ("baseline_scores.json", "with_skill_scores.json")
REPORT_FILE = "eval_report.md"
DIFFICULTIES = ("easy", "hard", "edge")
ANSWER_KEY_FIELDS = ("expectations", "difficulty", "deterministic_checks", "expected_response",
                     "ground_truth", "ground_truth_estimates")
MIN_TASKS, MAX_TASKS = 3, 5


def _load_array(path: Path, errors: list[str]) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: cannot parse JSON ({exc})")
        return []
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        errors.append(f"{path.name}: must be a JSON array of objects")
        return []
    return data


def _keys(items: list[dict]) -> list[tuple[str, str]]:
    return [(str(item.get("task_id", "")), str(item.get("dataset", ""))) for item in items]


def check_files(eval_dir: Path, allow_missing: set[str]) -> list[str]:
    return [f"missing required file: {name}" for name in REQUIRED_FILES
            if name not in allow_missing and not (eval_dir / name).is_file()]


def check_evalset(evalset: list[dict]) -> list[str]:
    errors = []
    if not MIN_TASKS <= len(evalset) <= MAX_TASKS:
        errors.append(f"evalset.json has {len(evalset)} tasks; need {MIN_TASKS}-{MAX_TASKS}")
    for item in evalset:
        tid = item.get("task_id") or "<no task_id>"
        if not item.get("task_id"):
            errors.append("evalset.json: a task has no task_id")
        if not str(item.get("query", "")).strip():
            errors.append(f"evalset.json: {tid} has an empty query")
        leaked = sorted(set(item) & set(ANSWER_KEY_FIELDS))
        if leaked:
            errors.append(f"evalset.json: {tid} carries answer-key fields {leaked}; move them to expectations.json")
    ids = [item.get("task_id") for item in evalset]
    if len(ids) != len(set(ids)):
        errors.append("evalset.json: duplicate task_id values")
    return errors


def check_expectations(expectations: list[dict]) -> list[str]:
    errors = []
    levels = []
    for item in expectations:
        tid = item.get("task_id") or "<no task_id>"
        level = item.get("difficulty")
        if level not in DIFFICULTIES:
            errors.append(f"expectations.json: {tid} difficulty {level!r} not in {DIFFICULTIES}")
        levels.append(level)
        if not isinstance(item.get("expectations"), dict) or not item["expectations"]:
            errors.append(f"expectations.json: {tid} has no expectations object")
    if expectations and "easy" not in levels:
        errors.append("expectations.json: need at least one easy task")
    if expectations and not {"hard", "edge"} & set(levels):
        errors.append("expectations.json: need at least one hard or edge task")
    return errors


def check_join(evalset: list[dict], expectations: list[dict]) -> list[str]:
    left, right = set(_keys(evalset)), set(_keys(expectations))
    errors = [f"task {tid!r} (dataset {ds!r}) in evalset.json but not expectations.json"
              for tid, ds in sorted(left - right)]
    errors += [f"task {tid!r} (dataset {ds!r}) in expectations.json but not evalset.json"
               for tid, ds in sorted(right - left)]
    return errors


def check_results(eval_dir: Path) -> list[str]:
    present = [name for name in RESULT_FILES if (eval_dir / name).is_file()]
    has_report = (eval_dir / REPORT_FILE).is_file()
    if present and not has_report:
        return [f"score files {present} present without {REPORT_FILE}; commit results only from a real run"]
    if has_report and len(present) != len(RESULT_FILES):
        return [f"{REPORT_FILE} present but score files missing: "
                f"{sorted(set(RESULT_FILES) - set(present))}"]
    return []


def validate(eval_dir: Path, allow_missing: set[str] | None = None) -> list[str]:
    """Return a list of problems; empty means the folder follows the convention."""
    if not eval_dir.is_dir():
        return [f"not a directory: {eval_dir}"]
    errors = check_files(eval_dir, allow_missing or set())
    evalset, expectations = [], []
    if (eval_dir / "evalset.json").is_file():
        evalset = _load_array(eval_dir / "evalset.json", errors)
        errors += check_evalset(evalset)
    if (eval_dir / "expectations.json").is_file():
        expectations = _load_array(eval_dir / "expectations.json", errors)
        errors += check_expectations(expectations)
    if evalset and expectations:
        errors += check_join(evalset, expectations)
    return errors + check_results(eval_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("eval_dir", type=Path)
    parser.add_argument("--allow-missing", action="append", default=[],
                        help="required file that may be absent (repeatable)")
    args = parser.parse_args(argv)
    errors = validate(args.eval_dir, set(args.allow_missing))
    for err in errors:
        print(f"  ✗ {err}")
    print(f"{'FAIL' if errors else 'OK'}  {args.eval_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
