"""EnergyBench task specs (tasks/<id>.toml), coverage labels (tasks.json), and task selection.

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

Each task has a `coverage` label: `covered` (both labelers name a shared skill; `energy_skills` holds the shared
skills), `control` (both name none) or `disputed` (they disagree; `energy_skills` holds the union). Disputed tasks
are never selected. Until label.py has run, tasks.json carries the task authors' intended coverage and says so in
`labels.method`; relabel before the first scored run.

A task spec has one `[task]` table (id, tier P|R, title, domain, intended_skills, det_weight, generator or
datasets, instruction, rubric), `[[answer]]` rows (the answer.json contract) and `[[check]]` rows (deterministic
checks, see scoring.py). Specs live in the repo; at run time only the rendered instruction and the data reach the
agent, while the answer key and rubric stay in the grading folder.
"""

from __future__ import annotations

import json
import random
import re
import tomllib
from pathlib import Path

from rubric import rubric_max
from scoring import CHECKS

HERE = Path(__file__).resolve().parent
TASKS_JSON = HERE / "tasks.json"
TASKS_DIR = HERE / "tasks"
DATASETS_JSON = HERE / "datasets.json"
COVERAGE = ("covered", "control", "disputed")
TIERS = ("P", "R")
FILE_CHECKS = {"file_exists", "file_forbid", "csv_min", "csv_sum_any"}
ANSWER_KINDS = {"number", "string", "list", "map", "bool"}
TASK_ID = re.compile(r"^[pcr]\d{2}-[a-z0-9-]+$")

FOOTER = """
## Working environment

- The input files are in `./data/` (read-only). Start with `./data/README.md` if there is one.
- You are working unattended: nobody can answer questions during this run. Where a choice would normally be the
  requester's or a domain expert's to make, do not pick silently: record it under `decisions` and continue with the
  option you would recommend.
- Keep a short log of what you did and why in `./trace.md`.

## Answer

Write `./answer.json`: one JSON object with exactly these keys.

{keys}
- `decisions` (list): every analytical choice that a domain expert or the requester would normally make (method,
  threshold, convention, data-handling rule, factor or standard). Each item: `{{"decision": ..., "options": [...],
  "chosen": ..., "impact": "<effect on this result>"}}`. Use `[]` if there were none.
- `summary` (string): two to five sentences on the result and its caveats.
"""


def combine(a: list[str], b: list[str]) -> tuple[str, list[str]]:
    """Two labelers' skill lists -> (coverage, expected skills)."""
    shared = sorted(set(a) & set(b))
    if shared:
        return "covered", shared
    if not a and not b:
        return "control", []
    return "disputed", sorted(set(a) | set(b))


def load(path: Path = TASKS_JSON) -> dict:
    return json.loads(path.read_text())


def save(doc: dict, path: Path = TASKS_JSON) -> None:
    """One task per line, so a relabel shows up as a readable diff."""
    labels = json.dumps(doc["labels"], indent=2).replace("\n", "\n  ")
    rows = ",\n".join("    " + json.dumps(t) for t in doc["tasks"])
    path.write_text(f'{{\n  "labels": {labels},\n  "tasks": [\n{rows}\n  ]\n}}\n')


def merge(doc: dict, rows: list[dict], labels: dict) -> dict:
    """tasks.json after a labeling run: relabeling every task replaces the labels; relabeling some updates those
    rows and records the run under labels.updates."""
    if {t["task_id"] for t in doc["tasks"]} <= {r["task_id"] for r in rows}:
        return {"labels": labels, "tasks": rows}
    new = {r["task_id"]: r for r in rows}
    tasks = [new.pop(t["task_id"], t) for t in doc["tasks"]] + list(new.values())
    updates = [*doc["labels"].get("updates", []), {**labels, "tasks": [r["task_id"] for r in rows]}]
    return {"labels": {**doc["labels"], "updates": updates}, "tasks": tasks}


def select(tasks: list[dict], skill: str | None = None, controls: int | None = None, seed: int = 0,
           tier: str | None = None) -> list[str]:
    """Covered tasks (for `skill`, or all) plus `controls` control tasks drawn with `seed` (all if None)."""
    tasks = [t for t in tasks if tier is None or t["tier"] == tier]
    covered = [t["task_id"] for t in tasks
               if t["coverage"] == "covered" and (skill is None or skill in t["energy_skills"])]
    if skill is not None and not covered:
        known = sorted({s for t in tasks if t["coverage"] == "covered" for s in t["energy_skills"]})
        raise SystemExit(f"No covered task for skill {skill!r}; run label.py, or pick from: {known}")
    pool = [t["task_id"] for t in tasks if t["coverage"] == "control"]
    if controls is not None:
        pool = sorted(random.Random(seed).sample(pool, min(controls, len(pool))))
    return covered + pool


def task_sets(tasks: list[dict]) -> dict[str, list[str]]:
    sets: dict[str, list[str]] = {c: [] for c in COVERAGE}
    for t in tasks:
        sets[t["coverage"]].append(t["task_id"])
    return sets


def load_spec(task_id: str, tasks_dir: Path = TASKS_DIR) -> dict:
    with open(tasks_dir / f"{task_id}.toml", "rb") as f:
        spec = tomllib.load(f)
    spec.setdefault("answer", [])
    spec.setdefault("check", [])
    return spec


def all_specs(tasks_dir: Path = TASKS_DIR) -> dict[str, dict]:
    return {p.stem: load_spec(p.stem, tasks_dir) for p in sorted(tasks_dir.glob("*.toml"))}


def datasets() -> dict[str, dict]:
    return json.loads(DATASETS_JSON.read_text())["datasets"]


def render_instruction(spec: dict) -> str:
    """The prompt the agent sees: the task text plus the shared working-environment and answer contract."""
    lines = []
    for a in spec["answer"]:
        unit = f", {a['unit']}" if a.get("unit") else ""
        lines.append(f"- `{a['key']}` ({a['kind']}{unit}): {a['description']}")
    return spec["task"]["instruction"].strip() + "\n" + FOOTER.format(keys="\n".join(lines))


def validate_spec(task_id: str, spec: dict, registry: dict | None = None) -> list[str]:
    """Problems with one spec; empty when valid. `registry` (generators.REGISTRY) is checked when given."""
    t, errors = spec.get("task", {}), []
    if t.get("id") != task_id or not TASK_ID.match(task_id):
        errors.append(f"id {t.get('id')!r} must equal the file name and match {TASK_ID.pattern}")
    if t.get("tier") not in TIERS:
        errors.append(f"tier must be one of {TIERS}")
    for field in ("title", "domain", "instruction", "rubric"):
        if not str(t.get(field, "")).strip():
            errors.append(f"missing task.{field}")
    if not 0 <= float(t.get("det_weight", -1)) <= 1:
        errors.append("det_weight must be in [0, 1]")
    if t.get("tier") == "P" and registry is not None and t.get("generator") not in registry:
        errors.append(f"unknown generator {t.get('generator')!r}")
    if t.get("tier") == "R" and not t.get("datasets"):
        errors.append("tier R task needs datasets")
    if t.get("rubric") and rubric_max(t["rubric"]) != 100:
        errors.append(f"rubric levels must sum to 100, got {rubric_max(t['rubric'])}")
    errors += _validate_checks(spec, float(t.get("det_weight", 0)))
    return errors


def _validate_checks(spec: dict, det_weight: float) -> list[str]:
    errors, keys = [], {a["key"] for a in spec["answer"]}
    for a in spec["answer"]:
        if a.get("kind") not in ANSWER_KINDS or not a.get("description"):
            errors.append(f"answer {a.get('key')!r}: kind must be one of {sorted(ANSWER_KINDS)} with a description")
    if {"decisions", "summary"} & keys:
        errors.append("decisions and summary are added to every contract; do not declare them")
    for c in spec["check"]:
        if c.get("type") not in CHECKS or float(c.get("points", 0)) <= 0:
            errors.append(f"check {c}: unknown type or non-positive points")
        elif c["type"] not in FILE_CHECKS | {"decision"} and c.get("key") not in keys:
            errors.append(f"check on {c.get('key')!r} is not in the answer contract")
        elif c["type"] == "decision" and not all(
                any(re.search(p, c.get("example", ""), re.IGNORECASE) for p in g) for g in c.get("patterns", [[]])):
            errors.append(f"decision check example does not match its own patterns: {c.get('example')!r}")
    if det_weight > 0 and not spec["check"]:
        errors.append("det_weight > 0 needs at least one check")
    return errors
