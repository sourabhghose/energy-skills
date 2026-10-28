#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Compare two arms on the labeled EnergyBench tasks: does a skills arm beat a baseline where a skill applies, and
does it hold up where none does?

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

Run score = judge.py's combined score (deterministic checks and rubric). Cell = mean over a (task, arm)'s runs.
For A - B on a task set, d_t = cell(A) - cell(B); the effect is the unweighted mean of d_t over tasks. The 95% CI
comes from a two-level bootstrap (resample tasks, then runs within each cell). Rate-limited runs, runs that touched
the grader files, and runs graded without their rubric (judge.py --no-llm on tasks with det_weight < 1) are
excluded and listed. Agent failures (timeout, no answer) keep their score, which is 0.

Comparisons (with --skill, covered means covered by that skill):
- covered: "improves" if effect >= --margin, CI low end > -margin, and no task drops by more than --max-task-drop;
- control: "no harm" if effect > -margin and no task drops by more than --max-task-drop;
- all labeled tasks, and covered tasks on the deterministic score alone: descriptive.
Also reported: the ask-before-assuming rate (share of `decision` checks passed), behaviour checks, how often each arm
opened an expected skill, token cost and per-task cells. Fix arms, tasks and thresholds before the runs.

    uv run analyze.py --grades rel --out rel --a skills --b no_skills --skill reliability-metrics
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import taskset  # noqa: E402
from paths import EB_HOME  # noqa: E402

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261014
MARGIN = 5.0
MAX_TASK_DROP = 15.0
MAX_TOKEN_RISE = 0.30
BEHAVIOR_KEYS = ("units_explicit", "time_convention_stated", "decision_surfaced", "validation_performed")


def run_key(r: dict) -> str:
    return f"{r['run_id']}/{r['task']}/{r['arm']}/rep{r['rep']}"


def load_runs(grades: list[dict], leaked: frozenset[str] = frozenset(), home: Path = EB_HOME) -> list[dict]:
    runs = []
    for g in grades:
        path = home / "runs" / g["run_id"] / g["task"] / g["arm"] / f"rep{g['rep']}" / "run.json"
        meta = json.loads(path.read_text()) if path.exists() else {}
        infra = bool(meta.get("rate_limited")) or "skipped" in meta
        leak, partial = run_key(g) in leaked, not g.get("complete", True)
        runs.append({**g, "meta": meta, "infra_failure": infra, "leaked": leak, "partial": partial,
                     "excluded": infra or leak or partial})
    return runs


def cells(runs: list[dict], metric: str = "score") -> dict[tuple[str, str], list[float]]:
    out: dict[tuple[str, str], list[float]] = {}
    for r in runs:
        if not r["excluded"]:
            out.setdefault((r["task"], r["arm"]), []).append(float(r[metric]))
    return out


def effect(cell_scores: dict, tasks: list[str], a: str, b: str) -> tuple[float, dict[str, float]]:
    diffs = {t: statistics.fmean(cell_scores[(t, a)]) - statistics.fmean(cell_scores[(t, b)]) for t in tasks}
    return statistics.fmean(diffs.values()), diffs


def bootstrap_ci(cell_scores: dict, tasks: list[str], a: str, b: str, rng: random.Random,
                 resamples: int = BOOTSTRAP_RESAMPLES) -> tuple[float, float]:
    stats = []
    for _ in range(resamples):
        sampled = rng.choices(tasks, k=len(tasks))
        d = [statistics.fmean(rng.choices(cell_scores[(t, a)], k=len(cell_scores[(t, a)])))
             - statistics.fmean(rng.choices(cell_scores[(t, b)], k=len(cell_scores[(t, b)]))) for t in sampled]
        stats.append(statistics.fmean(d))
    stats.sort()
    return stats[int(0.025 * len(stats))], stats[int(0.975 * len(stats)) - 1]


def sign_test(diffs: list[float]) -> tuple[int, int, float]:
    """(ups, downs, two-sided exact binomial p); ties are dropped."""
    ups, downs = sum(d > 0 for d in diffs), sum(d < 0 for d in diffs)
    n = ups + downs
    if n == 0:
        return 0, 0, 1.0
    tail = sum(math.comb(n, k) for k in range(min(ups, downs) + 1)) / 2**n
    return ups, downs, min(1.0, 2 * tail)


def decide(rule: str | None, mean: float, lo: float, diffs: dict[str, float], margin: float = MARGIN,
           max_drop: float = MAX_TASK_DROP) -> str:
    worst = min(diffs.values())
    if rule == "improves":
        return "PASS" if mean >= margin and lo > -margin and worst >= -max_drop else "inconclusive"
    if rule == "no_harm":
        return "PASS" if mean > -margin and worst >= -max_drop else "FAIL"
    return "descriptive"


def median_tokens(runs: list[dict], tasks: list[str], arm: str) -> float | None:
    vals = [r["meta"].get("input_tokens", 0) + r["meta"].get("output_tokens", 0)
            for r in runs if r["arm"] == arm and r["task"] in tasks and not r["excluded"] and r["meta"]]
    return statistics.median(vals) if vals else None


def token_rise(runs: list[dict], tasks: list[str], a: str, b: str) -> float | None:
    """Mean over tasks of median_tokens(a) / median_tokens(b), minus 1."""
    ratios = []
    for t in tasks:
        tok_a, tok_b = median_tokens(runs, [t], a), median_tokens(runs, [t], b)
        if tok_a and tok_b:
            ratios.append(tok_a / tok_b)
    return statistics.fmean(ratios) - 1 if ratios else None


def rate(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def decision_rate(runs: list[dict], tasks: list[str], arm: str) -> float | None:
    """Ask-before-assuming: percent of `decision` checks passed by an arm on these tasks."""
    passed = [100.0 * (c["earned"] > 0) for r in runs if r["arm"] == arm and r["task"] in tasks and not r["excluded"]
              for c in r.get("checks", []) if c["type"] == "decision"]
    return rate(passed)


def behavior_rates(runs: list[dict], tasks: list[str], arm: str) -> dict[str, str]:
    out = {}
    for key in BEHAVIOR_KEYS:
        answers = [(r.get("behavior") or {}).get(key) for r in runs if r["arm"] == arm and r["task"] in tasks]
        applicable = [a for a in answers if a in ("yes", "no")]
        out[key] = f"{sum(a == 'yes' for a in applicable)}/{len(applicable)}" if applicable else "n/a"
    return out


def routing(runs: list[dict], task_sets: dict[str, list[str]], expected: dict[str, list[str]]) -> dict:
    """Per arm, percent of covered runs that opened an expected skill, and of control runs that opened any."""
    hits: dict[str, list[float]] = {}
    false: dict[str, list[float]] = {}
    for r in runs:
        if r["excluded"]:
            continue
        opened = set(r["meta"].get("opened", []))
        if r["task"] in task_sets.get("covered", []):
            hits.setdefault(r["arm"], []).append(100.0 * bool(opened & set(expected[r["task"]])))
        elif r["task"] in task_sets.get("control", []):
            false.setdefault(r["arm"], []).append(100.0 * bool(opened))
    return {arm: {"hit_rate": rate(hits.get(arm, [])), "false_trigger_rate": rate(false.get(arm, []))}
            for arm in sorted(hits | false)}


def comparisons_for(a: str, b: str) -> list[tuple]:
    """(name, task set, arm A, arm B, rule, metric)."""
    return [
        (f"covered: {a} vs {b}", "covered", a, b, "improves", "score"),
        (f"no harm on controls: {a} vs {b}", "control", a, b, "no_harm", "score"),
        (f"all labeled tasks: {a} vs {b}", "all", a, b, None, "score"),
        (f"covered, deterministic checks only: {a} vs {b}", "covered", a, b, None, "det_score"),
    ]


def compare(runs: list[dict], task_sets: dict, comparison: tuple, rng: random.Random, margin: float,
            max_drop: float) -> dict | None:
    name, task_set, a, b, rule, metric = comparison
    cell_scores = cells(runs, metric)
    tasks = [t for t in task_sets.get(task_set, []) if (t, a) in cell_scores and (t, b) in cell_scores]
    if not tasks:
        return None
    mean, diffs = effect(cell_scores, tasks, a, b)
    lo, hi = bootstrap_ci(cell_scores, tasks, a, b, rng)
    ups, downs, p = sign_test(list(diffs.values()))
    rise = token_rise(runs, tasks, a, b)
    decision = decide(rule, mean, lo, diffs, margin, max_drop)
    if rule == "improves" and decision == "PASS" and rise is not None and rise > MAX_TOKEN_RISE:
        decision = "PASS on score, FAILS cost guardrail"
    return {"comparison": name, "set": task_set, "metric": metric, "a": a, "b": b, "rule": rule, "tasks": tasks,
            "left_out": [t for t in task_sets.get(task_set, []) if t not in tasks], "effect": mean,
            "ci95": [lo, hi], "per_task": diffs, "ups": ups, "downs": downs, "sign_p": p, "token_rise": rise,
            "decision": decision}


def analyze(grades: list[dict], task_sets: dict[str, list[str]], comparisons: list[tuple],
            expected: dict[str, list[str]], seed: int = BOOTSTRAP_SEED, margin: float = MARGIN,
            max_drop: float = MAX_TASK_DROP, leaked: frozenset[str] = frozenset(), home: Path = EB_HOME) -> dict:
    runs = load_runs(grades, leaked, home)
    rng = random.Random(seed)
    results = [c for c in (compare(runs, task_sets, comp, rng, margin, max_drop) for comp in comparisons) if c]
    arms = sorted({r["arm"] for r in runs})
    return {
        "comparisons": results,
        "cells": {f"{t}|{arm}": {"mean": statistics.fmean(v), "runs": v} for (t, arm), v in sorted(cells(runs).items())},
        "decision_rate": {arm: decision_rate(runs, task_sets.get("covered", []), arm) for arm in arms},
        "behavior": {f"{s}|{arm}": behavior_rates(runs, tasks, arm) for s, tasks in task_sets.items() for arm in arms},
        "routing": routing(runs, task_sets, expected),
        "infra_failures": [run_key(r) for r in runs if r["infra_failure"]],
        "leaks": [run_key(r) for r in runs if r["leaked"]],
        "partial": [run_key(r) for r in runs if r["partial"]],
        "cost": {arm: {"median_tokens": median_tokens(runs, task_sets.get("all", []), arm),
                       "median_wall_s": statistics.median([r["meta"]["wall_s"] for r in runs if r["arm"] == arm
                                                           and r["meta"].get("wall_s") is not None] or [0])}
                 for arm in arms},
    }


def to_markdown(result: dict) -> str:
    fmt = lambda x, spec="+.1f": "n/a" if x is None else format(x, spec)  # noqa: E731
    lines = ["# EnergyBench analysis", "", "## Comparisons", "",
             "| Comparison | Tasks | Left out | Effect | 95% CI | Up / down | Sign p | Token change | Decision |",
             "|---|---|---|---|---|---|---|---|---|"]
    for c in result["comparisons"]:
        lines.append(f"| {c['comparison']} | {len(c['tasks'])} | {', '.join(c['left_out']) or 'none'} "
                     f"| {c['effect']:+.1f} | {c['ci95'][0]:+.1f} to {c['ci95'][1]:+.1f} | {c['ups']} / {c['downs']} "
                     f"| {c['sign_p']:.3f} | {fmt(c['token_rise'], '+.0%')} | {c['decision']} |")
    lines += ["", "## Ask-before-assuming (decision checks passed, covered tasks)", "", "| Arm | Rate |", "|---|---|"]
    lines += [f"| {arm} | {fmt(v, '.0f')}% |" for arm, v in result["decision_rate"].items()]
    lines += ["", "## Cells (mean of runs)", "", "| Task | Arm | Mean | Runs |", "|---|---|---|---|"]
    for key, v in result["cells"].items():
        task, arm = key.split("|")
        lines.append(f"| {task} | {arm} | {v['mean']:.1f} | {', '.join(f'{x:.1f}' for x in v['runs'])} |")
    lines += ["", "## Behaviour checks (yes / applicable)", "",
              "| Set and arm | Units | Time convention | Decision surfaced | Validation |", "|---|---|---|---|---|"]
    lines += [f"| {k.replace('|', ' ')} | " + " | ".join(v.values()) + " |" for k, v in result["behavior"].items()]
    lines += ["", "## Skill use", "", "| Arm | Hit rate (covered) | False triggers (controls) |", "|---|---|---|"]
    lines += [f"| {arm} | {fmt(m['hit_rate'], '.0f')}% | {fmt(m['false_trigger_rate'], '.0f')}% |"
              for arm, m in result["routing"].items()]
    lines += ["", "## Cost (all tasks)", "", "| Arm | Median tokens | Median wall time (s) |", "|---|---|---|"]
    lines += [f"| {arm} | {c['median_tokens']} | {c['median_wall_s']} |" for arm, c in result["cost"].items()]
    for label, key in (("Infrastructure failures", "infra_failures"), ("Runs that touched grader files", "leaks"),
                       ("Runs graded without their rubric", "partial")):
        lines += ["", f"{label}, excluded: {', '.join(result[key]) or 'none'}"]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grades", action="append", required=True, help="grades folder name under $EB_HOME/grades")
    ap.add_argument("--out", required=True)
    ap.add_argument("--a", required=True, help="the arm under test, e.g. skills")
    ap.add_argument("--b", required=True, help="the baseline arm, e.g. no_skills")
    ap.add_argument("--skill", help="count only the tasks covered by this skill as covered")
    ap.add_argument("--margin", type=float, default=MARGIN)
    ap.add_argument("--max-task-drop", type=float, default=MAX_TASK_DROP)
    ap.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    args = ap.parse_args()
    grades = [g for n in args.grades for g in json.loads((EB_HOME / "grades" / n / "grades.json").read_text())]
    leaked = frozenset(k for n in args.grades
                       for k in json.loads((EB_HOME / "grades" / n / "meta.json").read_text()).get("leaks", {}))
    tasks = taskset.load()["tasks"]
    if args.skill:
        tasks = [t for t in tasks if t["coverage"] != "covered" or args.skill in t["energy_skills"]]
    task_sets = taskset.task_sets(tasks)
    task_sets["all"] = task_sets["covered"] + task_sets["control"]
    expected = {t["task_id"]: t["energy_skills"] for t in tasks}
    result = analyze(grades, task_sets, comparisons_for(args.a, args.b), expected, args.seed, args.margin,
                     args.max_task_drop, leaked)
    out_dir = EB_HOME / "analysis" / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.json").write_text(json.dumps(result, indent=2))
    (out_dir / "analysis.md").write_text(to_markdown(result))
    print(to_markdown(result))


if __name__ == "__main__":
    main()
