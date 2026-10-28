#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["databricks-sdk>=0.40", "openai>=1.40", "httpx"]
# ///
"""Grade EnergyBench runs: deterministic checks against the planted answer key, plus a blinded LLM rubric judge.

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

For every finished run: (1) scoring.py checks answer.json and output files against the task's answer key (tier P);
(2) unless --no-llm, a judge on Databricks Foundation Model APIs grades trace.md + answer.json against the task's
rubric --repeats times, picking a level per criterion (points come from the rubric, never the model), and answers
four yes/no behaviour checks. Run score = det_weight x det_score + (1 - det_weight) x mean rubric score. Before
judging, skill names, skill paths and the agent's name are removed, so the judge cannot tell the arms apart.

Graded rows are cached in grades/<out>/rows/, so rerunning resumes; the command fails if any run is left ungraded.
With --no-llm only tasks with det_weight = 1 get a full score; others are graded on checks alone and flagged.

    uv run judge.py --run-id rel --out rel --profile <profile>
    uv run judge.py --run-id rel --out rel-det --no-llm
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import statistics
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from paths import EB_GRADING, EB_HOME  # noqa: E402
from rubric import first_json_object, redact, score_response  # noqa: E402
from scoring import load_answer, score_checks  # noqa: E402

JUDGES = {"gemini_3_8_flash": "databricks-gemini-3-8-flash", "claude_sonnet_5_5": "databricks-claude-sonnet-5-5"}
PRIMARY_JUDGE = "gemini_3_8_flash"
# A run whose events mention any of these may have read the answer key or the task specs.
LEAK_MARKERS = tuple(dict.fromkeys((str(EB_GRADING), EB_GRADING.name, "energybench-grading", "answer_key.json",
                                    "rubric.txt", str(HERE / "tasks"))))

PROMPT = """You are an expert evaluator for an energy-industry data analysis task.

The task given to the agent:

<task>
{task}
</task>

Evaluate the agent's work using the following rubric:

{rubric}

Here is the agent's analysis trace:

<trace>
{trace}
</trace>

Here is the agent's final answer (answer.json):

<answer>
{answer}
</answer>

For each criterion in the rubric, choose ONE level: A, B, or C, based purely on which level description best describes the agent's work. Do not output numerical points; the score for each level is computed automatically from the rubric.

You MUST respond with a JSON object in exactly this format:
{{
  "criteria": {{
    "criterion_1": {{"level": "A", "reason": "<one-sentence explanation>"}},
    "criterion_2": {{"level": "B", "reason": "<one-sentence explanation>"}},
    ...
  }},
  "overall_reasoning": "<short summary>"
}}

Each "level" value must be exactly the single character "A", "B", or "C". Only output the JSON object, nothing else."""

BEHAVIOR_PROMPT = """You are auditing how an energy data analysis was carried out. Read the task, the analysis trace and the final answer.

<task>
{task}
</task>

<trace>
{trace}
</trace>

<answer>
{answer}
</answer>

Answer each question with "yes", "no", or "not_applicable".
- units_explicit: Does every reported quantity carry an explicit unit (or is the unit unambiguous from its name)?
- time_convention_stated: If the analysis used timestamps, did it state the time zone and interval convention (interval-beginning or interval-ending) it relied on?
- decision_surfaced: When the analysis made a choice a domain expert or the requester would normally make (method, threshold, factor source, convention), did it state the choice and the alternatives rather than pick silently?
- validation_performed: Did the analysis check its inputs or results (counts, duplicates, reconciliation, plausibility) before reporting?

Respond with only a JSON object with exactly these four keys, each mapped to "yes", "no", or "not_applicable"."""
BEHAVIOR_KEYS = ("units_explicit", "time_convention_stated", "decision_surfaced", "validation_performed")
MAX_CHARS = 120_000  # keep judge prompts inside context limits; long traces are truncated in the middle


def complete(client, endpoint: str, prompt: str) -> str:
    resp = client.chat.completions.create(model=endpoint, messages=[{"role": "user", "content": prompt}],
                                          max_tokens=8192)
    content = resp.choices[0].message.content
    if isinstance(content, list):  # FMAPI may return content blocks (reasoning + text)
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return content or ""


def clip(text: str, limit: int = MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[... {len(text) - limit} characters omitted ...]\n{text[-half:]}"


def behavior(client, endpoint: str, task: str, trace: str, answer: str) -> dict[str, str]:
    try:
        result = first_json_object(complete(client, endpoint, BEHAVIOR_PROMPT.format(task=task, trace=trace,
                                                                                    answer=answer)))
    except ValueError as e:
        print(f"behaviour check unparseable: {e}", flush=True)
        result = {}
    return {k: str(result.get(k, "unparseable")).strip().lower() for k in BEHAVIOR_KEYS}


def read(path: Path) -> str:
    return path.read_text(errors="replace") if path.exists() else ""


def leaked(workdir: Path) -> list[str]:
    events = read(workdir / "events.jsonl")
    return [m for m in LEAK_MARKERS if m in events]


def prompt_sha() -> str:
    return hashlib.sha256((PROMPT + BEHAVIOR_PROMPT).encode()).hexdigest()


def task_material(task: str, grading_root: Path = EB_GRADING) -> dict:
    """What the grader needs for one task, read from its grading folder (never from the run folder)."""
    folder = grading_root / task
    with open(folder / "task.toml", "rb") as f:
        spec = tomllib.load(f)
    return {"instruction": read(folder / "instruction.md"), "rubric": read(folder / "rubric.txt"),
            "checks": spec.get("check", []), "det_weight": float(spec["task"]["det_weight"]),
            "key": json.loads(read(folder / "answer_key.json") or "{}")}


def collect_rows(run_ids: list[str], home: Path = EB_HOME) -> list[dict]:
    """One row per finished run folder runs/<run-id>/<task>/<arm>/rep<k>, with redacted trace and answer."""
    rows = []
    for run_id in run_ids:
        for workdir in sorted((home / "runs" / run_id).glob("*/*/rep*")):
            if not (workdir / "run.json").exists():
                print(f"skipping unfinished run {workdir.relative_to(home / 'runs')}", flush=True)
                continue
            meta = json.loads(read(workdir / "run.json"))
            rows.append({"run_id": run_id, "task": workdir.parent.parent.name, "arm": workdir.parent.name,
                         "rep": int(workdir.name.removeprefix("rep")), "workdir": workdir, "leaks": leaked(workdir),
                         "skills": meta.get("skills", []), "trace": read(workdir / "trace.md"),
                         "answer_text": read(workdir / "answer.json")})
    names = sorted({s for r in rows for s in r["skills"]})
    return [{**r, "trace": redact(r["trace"], names), "answer_text": redact(r["answer_text"], names)} for r in rows]


def deterministic(row: dict, material: dict) -> dict:
    answer, problem = load_answer(row["workdir"])
    result = score_checks(material["checks"], material["key"], answer, row["workdir"])
    return {**result, "answer_problem": problem}


def combine_scores(det: dict, rubric_totals: list[float] | None, det_weight: float) -> tuple[float, bool]:
    """(score, complete). Without rubric grades a task with det_weight < 1 is only partly graded."""
    if rubric_totals is None:
        return det["det_score"], det_weight >= 1.0
    rubric_mean = statistics.fmean(rubric_totals) if rubric_totals else 0.0
    if det_weight == 0:
        return rubric_mean, True
    return det_weight * det["det_score"] + (1 - det_weight) * rubric_mean, True


def grade_row(row: dict, material: dict, client, endpoint: str | None, repeats: int) -> dict:
    det = deterministic(row, material) if material["checks"] else {"det_score": 0.0, "checks": []}
    totals, grades, checks = None, [], {}
    if client is not None:
        trace, answer = clip(row["trace"]), clip(row["answer_text"])
        if trace or answer:
            grades = [score_response(material["rubric"], complete(client, endpoint, PROMPT.format(
                task=material["instruction"], rubric=material["rubric"], trace=trace or "[no trace.md]",
                answer=answer or "[no answer.json]"))) for _ in range(repeats)]
        totals = [g["total"] for g in grades] or [0.0] * repeats
        checks = behavior(client, endpoint, material["instruction"], trace, answer)
    score, complete_ = combine_scores(det, totals, material["det_weight"])
    return {"score": round(score, 3), "complete": complete_, "det_score": det["det_score"],
            "checks": det.get("checks", []), "rubric_totals": totals, "behavior": checks,
            "reasoning": grades[0]["reasoning"] if grades else ""}


def _cache_key(row: dict, endpoint: str | None, repeats: int) -> str:
    payload = [prompt_sha(), endpoint, repeats, row["trace"], row["answer_text"]]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def grade_all(rows: list[dict], client, endpoint: str | None, repeats: int, cache_dir: Path, jobs: int,
              grading_root: Path = EB_GRADING) -> list[dict]:
    materials = {t: task_material(t, grading_root) for t in sorted({r["task"] for r in rows})}

    def one(row: dict) -> dict:
        path = cache_dir / f"{row['run_id']}__{row['task']}__{row['arm']}__{row['rep']}.json"
        key = _cache_key(row, endpoint, repeats)
        cached = json.loads(read(path) or "{}")
        result = cached["result"] if cached.get("key") == key else grade_row(row, materials[row["task"]], client,
                                                                            endpoint, repeats)
        path.write_text(json.dumps({"key": key, "result": result}))
        print(f"graded {row['task']}/{row['arm']}/rep{row['rep']}: {result['score']}", flush=True)
        return {k: row[k] for k in ("run_id", "task", "arm", "rep")} | result

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(one, rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", action="append", required=True, help="run folder under $EB_HOME/runs; repeat")
    ap.add_argument("--out", required=True, help="output name under $EB_HOME/grades")
    ap.add_argument("--profile", help="Databricks CLI profile for Foundation Model APIs (not needed with --no-llm)")
    ap.add_argument("--no-llm", action="store_true", help="deterministic checks only")
    ap.add_argument("--repeats", type=int, default=5, help="grade each answer N times")
    ap.add_argument("--judge", choices=sorted(JUDGES), default=PRIMARY_JUDGE)
    ap.add_argument("--judge-endpoint", help="any other serving endpoint name; overrides --judge")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    if not args.no_llm and not args.profile:
        ap.error("--profile is required unless --no-llm")
    client, endpoint = None, None
    if not args.no_llm:
        from databricks.sdk import WorkspaceClient

        client = WorkspaceClient(profile=args.profile).serving_endpoints.get_open_ai_client().with_options(
            timeout=300, max_retries=3)
        endpoint = args.judge_endpoint or JUDGES[args.judge]
    out_dir = EB_HOME / "grades" / args.out
    (out_dir / "rows").mkdir(parents=True, exist_ok=True)
    rows = collect_rows(args.run_id)
    grades = grade_all(rows, client, endpoint, args.repeats, out_dir / "rows", args.jobs)
    leaks = {f"{r['run_id']}/{r['task']}/{r['arm']}/rep{r['rep']}": r["leaks"] for r in rows if r["leaks"]}
    (out_dir / "grades.json").write_text(json.dumps(grades, indent=2))
    (out_dir / "meta.json").write_text(json.dumps({
        "run_ids": args.run_id, "judge_endpoint": endpoint, "repeats": args.repeats, "prompt_sha256": prompt_sha(),
        "no_llm": args.no_llm, "n_rows": len(rows), "leaks": leaks,
        "incomplete": sorted({g["task"] for g in grades if not g["complete"]}),
        "graded_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, indent=2))
    print(f"wrote {out_dir}; leaks: {leaks or 'none'}")
    if len(grades) != len(rows):
        raise SystemExit(f"only {len(grades)} of {len(rows)} runs were graded; rerun the same command to resume")


if __name__ == "__main__":
    main()
