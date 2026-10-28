#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["databricks-sdk>=0.40", "openai>=1.40", "httpx", "pyyaml>=6"]
# ///
"""Label which Energy Skills each EnergyBench task falls under, before any scored run.

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

Two labelers, each a different LLM on Foundation Model APIs, work independently. Each sees only the task's rendered
instruction and the name and description of every published skill at --skills-ref (read from skills/*/SKILL.md at
that commit, so new skills are picked up automatically), never the rubric, the data, the answer key or the task
author's intended skills. taskset.combine turns the two answers into `covered`, `control` or `disputed`. Answers go
to labels/<name>_labeler_{a,b}.json, settings to labels/<name>_meta.json; with --write, labels go into tasks.json.

Freeze the labels (commit them) before the first scored run. When the skills change, relabel at the new commit.
`--compare-intent` also prints where the labelers disagree with the task authors' intended_skills.

    uv run label.py --labeled --skills-ref main --name main --profile <profile> --write --compare-intent
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import taskset  # noqa: E402
from judge import complete  # noqa: E402
from run import git, skill_bundles  # noqa: E402

LABELERS = {"a": "databricks-gemini-3-8-flash", "b": "databricks-claude-sonnet-5-5"}

PROMPT = """You decide which agent skills apply to an energy-industry data analysis task. A skill applies only if the analysis the task asks for is what the skill's description says it is for. A task may fit several skills or none; generic data work (aggregation, plotting, text counting) fits none.

Skills:
{skills}

Task:
<task>
{task}
</task>

Respond with only a JSON object: {{"skills": [<names of the skills that apply, or empty>], "reason": "<one sentence>"}}"""


def skill_descriptions(sha: str) -> dict[str, str]:
    """{skill name: description} from each published skill's SKILL.md frontmatter at a commit."""
    out = {}
    for name, files in skill_bundles(sha).items():
        front = re.match(r"---\n(.*?)\n---", files["SKILL.md"].decode(), flags=re.DOTALL)
        if front:
            out[name] = " ".join(str(yaml.safe_load(front.group(1)).get("description", "")).split())
    return out


def prompt_for(skills: dict[str, str], task_text: str) -> str:
    listing = "\n".join(f"- {name}: {desc}" for name, desc in sorted(skills.items()))
    return PROMPT.format(skills=listing, task=task_text.strip())


def parse(response: str, known: set[str]) -> dict:
    start, end = response.find("{"), response.rfind("}")
    try:
        result = json.loads(response[start:end + 1])
    except ValueError:
        return {"skills": [], "reason": f"unparseable: {response[:200]}", "unparseable": True}
    named = [s for s in result.get("skills") or [] if isinstance(s, str)]
    out = {"skills": sorted(s for s in named if s in known), "reason": str(result.get("reason", ""))}
    if unknown := sorted(set(named) - known):
        out["unknown_skills"] = unknown
    return out


def label_all(client, endpoints: dict[str, str], prompts: dict[str, str], known: set[str], name: str) -> dict:
    labels: dict[str, dict[str, dict]] = {}
    for key, endpoint in endpoints.items():
        with ThreadPoolExecutor(max_workers=4) as pool:
            answers = pool.map(lambda t: parse(complete(client, endpoint, prompts[t]), known), list(prompts))
            labels[key] = dict(zip(prompts, answers))
        path = HERE / "labels" / f"{name}_labeler_{key}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(labels[key], indent=1) + "\n")
        print(f"labeler {key} ({endpoint}): {path}")
    return labels


def main() -> None:
    from databricks.sdk import WorkspaceClient

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*", help="task ids")
    ap.add_argument("--labeled", action="store_true", help="relabel every task in tasks.json")
    ap.add_argument("--skills-ref", required=True, help="git ref whose published skills are offered")
    ap.add_argument("--name", required=True, help="label file prefix under labels/")
    ap.add_argument("--profile", required=True, help="Databricks CLI profile for Foundation Model APIs")
    ap.add_argument("--labeler-a", default=LABELERS["a"])
    ap.add_argument("--labeler-b", default=LABELERS["b"])
    ap.add_argument("--write", action="store_true", help="write these labels into tasks.json")
    ap.add_argument("--compare-intent", action="store_true", help="print disagreements with intended_skills")
    args = ap.parse_args()
    doc = taskset.load()
    tasks = args.tasks or ([t["task_id"] for t in doc["tasks"]] if args.labeled else [])
    if not tasks:
        ap.error("pass task ids or --labeled")
    sha = git("rev-parse", "--verify", f"{args.skills_ref}^{{commit}}")
    skills = skill_descriptions(sha)
    specs = {t: taskset.load_spec(t) for t in tasks}
    prompts = {t: prompt_for(skills, taskset.render_instruction(specs[t])) for t in tasks}
    client = WorkspaceClient(profile=args.profile).serving_endpoints.get_open_ai_client().with_options(
        timeout=300, max_retries=3)
    endpoints = {"a": args.labeler_a, "b": args.labeler_b}
    labels = label_all(client, endpoints, prompts, set(skills), args.name)
    meta = {"skills_sha": sha, "skills": sorted(skills), "labelers": endpoints,
            "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            "labeled_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    (HERE / "labels" / f"{args.name}_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    rows = []
    for t in tasks:
        coverage, expected = taskset.combine(labels["a"][t]["skills"], labels["b"][t]["skills"])
        task = specs[t]["task"]
        rows.append({"task_id": t, "tier": task["tier"], "topic": task["title"], "coverage": coverage,
                     "energy_skills": expected})
        if args.compare_intent and sorted(task["intended_skills"]) != expected:
            print(f"  intent differs: {t}: intended {task['intended_skills']}, labeled {coverage} {expected}")
    print(f"{len(rows)} tasks: { {c: sum(r['coverage'] == c for r in rows) for c in taskset.COVERAGE} }")
    unparseable = [f"{k}/{t}" for k in labels for t in tasks if labels[k][t].get("unparseable")]
    if unparseable:
        raise SystemExit(f"unparseable answers, tasks.json not written: {unparseable}")
    if args.write:
        files = [f"labels/{args.name}_labeler_{k}.json" for k in endpoints]
        taskset.save(taskset.merge(doc, rows, {**meta, "method": "label.py", "labeler_files": files}))
        print(f"wrote {taskset.TASKS_JSON}")


if __name__ == "__main__":
    main()
