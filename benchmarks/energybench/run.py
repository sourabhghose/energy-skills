#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Run Genie Code CLI on EnergyBench tasks, once per (replicate, task, arm).

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

An arm is `no_skills` or NAME=GIT_REF[:INSTRUCTIONS]. GIT_REF names the published skill bundles of this repo at that
ref (eval/ and tests/ excluded, the same filter as the Unity Catalog sync), installed in the run's ./.agents/skills/.
INSTRUCTIONS names a file in instructions/ that is copied to ./AGENTS.md, which Genie always loads. Refs are resolved
to SHAs once, so a moving branch cannot change an arm mid-study.

Tasks come from tasks.json: `--skill NAME` runs the tasks labeled as covered by that skill, `--controls N` adds N
control tasks drawn with --seed (the no-harm check), `--tier P|R` restricts the tier, and `--tasks` names tasks
directly. With none of these, every covered and control task runs.

Each run gets a fresh workdir $EB_HOME/runs/<run-id>/<task>/<arm>/rep<k>/ with ./data (the task's files, hard-linked
and read-only) and its own Python. The prompt is the task's rendered instruction.md; the agent writes ./trace.md,
./answer.json and any requested output files.

Runs go in a schedule written to schedule-*.json before the first run starts; within a replicate the task order and
arm order are shuffled with --seed. Runs are resumable: rerunning the same command keeps the pinned SHAs and skips
every workdir with run.json, except runs still rate-limited after all retries. A turn that fails on the network is
an infrastructure failure: it is moved to $EB_HOME/infra-failed/ and the rest of the batch is skipped.

Every run uses the Genie config profile `energybench` ($GENIE_HOME/energybench.config.toml, written here), which
disables the user's personal skills and memories. Genie's bundled Databricks skills stay on in every arm.

    uv run run.py --run-id rel --skill reliability-metrics --controls 4 --arm no_skills --arm skills=main:D0 --reps 3
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(HERE))

from sync_skills_git2unity import SKILL_LEAF_PATTERN, is_published  # noqa: E402

import taskset  # noqa: E402
from paths import EB_GRADING, EB_HOME, data_version  # noqa: E402

NO_SKILLS = "no_skills"
AGENT_TIMEOUT_S = 3600
PYTHON_VERSION = "3.12"
MAX_ATTEMPTS = 4
RATE_LIMIT_BACKOFF_S = 120
MIN_FREE_GB = 8
NETWORK_FAILURES = {
    "ip_acl": ("blocked by Databricks IP ACL",),
    "connection_lost": ("stream disconnected before completion: error sending request",),
}
network_blocked = threading.Event()
MAX_KEPT_FILE_BYTES = 100 * 1024**2
RUN_RECORD = {"events.jsonl", "stderr.log", "trace.md", "answer.json"}
GENIE_HOME = Path(os.environ.get("GENIE_HOME", Path.home() / ".genie"))
GENIE_PROFILE = "energybench"
USER_SKILL_DIRS = (GENIE_HOME / "skills", Path.home() / ".agents" / "skills")
GENIE_CMD = ["genie", "exec", "--json", "--skip-git-repo-check", "-p", GENIE_PROFILE, "--sandbox", "workspace-write"]
INSTRUCTIONS_DIR = HERE / "instructions"
SKILLS_DIR = ".agents/skills"
INSTRUCTIONS_FILE = "AGENTS.md"
SKILL_OPEN = re.compile(r"\.agents/skills/([A-Za-z0-9-]+)/SKILL\.md")


def user_skill_names() -> list[str]:
    names = set()
    for root in USER_SKILL_DIRS:
        for skill_md in root.glob("*/SKILL.md"):
            m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", skill_md.read_text(errors="replace"), flags=re.MULTILINE)
            names.add(m.group(1).strip() if m else skill_md.parent.name)
    return sorted(names)


def write_genie_profile() -> Path:
    """Unattended runs: no approval prompts, network on, memories and user skills off."""
    lines = ['approval_policy = "never"', "", "[sandbox_workspace_write]", "network_access = true",
             "", "[memories]", "generate_memories = false", "use_memories = false"]
    for name in user_skill_names():
        lines += ["", "[[skills.config]]", f"name = {json.dumps(name)}", "enabled = false"]
    path = GENIE_HOME / f"{GENIE_PROFILE}.config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def resolve_arms(specs: list[str]) -> dict[str, dict]:
    """`no_skills` or NAME=GIT_REF[:INSTRUCTIONS] -> {name: arm}; refs are pinned to SHAs here."""
    arms = {}
    for spec in specs:
        if spec == NO_SKILLS:
            arms[NO_SKILLS] = {"ref": None, "sha": None, "skills_tree": None}
            continue
        name, sep, value = spec.partition("=")
        ref, _, instructions = value.partition(":")
        if not sep or not name or name == NO_SKILLS or not ref:
            sys.exit(f"--arm must be `{NO_SKILLS}` or NAME=GIT_REF[:INSTRUCTIONS], got {spec!r}")
        sha = git("rev-parse", "--verify", f"{ref}^{{commit}}")
        arm = {"ref": ref, "sha": sha, "skills_tree": git("rev-parse", f"{sha}:skills")}
        if instructions:
            path = INSTRUCTIONS_DIR / f"{instructions}.md"
            if not path.is_file():
                sys.exit(f"No instructions file {path}")
            arm |= {"instructions": instructions, "instructions_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        arms[name] = arm
    return arms


def skill_bundles(sha: str) -> dict[str, dict[str, bytes]]:
    """{skill: {relative path: bytes}} for every published skill under skills/ at a commit."""
    archive = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", sha, "skills/"], capture_output=True, check=True
    ).stdout
    bundles: dict[str, dict[str, bytes]] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if member.isfile() and len(parts) > 2 and is_published(Path(*parts[2:])):
                bundles.setdefault(parts[1], {})[str(Path(*parts[2:]))] = tar.extractfile(member).read()
    return {n: f for n, f in sorted(bundles.items()) if "SKILL.md" in f and SKILL_LEAF_PATTERN.match(n)}


def install_skills(sha: str, dest: Path) -> list[str]:
    bundles = skill_bundles(sha)
    for name, files in bundles.items():
        for rel, data in files.items():
            path = dest / name / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return list(bundles)


def build_schedule(tasks: list[str], arms: list[str], reps: list[int], seed: int) -> list[dict]:
    """Grouped by replicate. Within each, task order and each task's arm order are shuffled."""
    rng = random.Random(seed)
    schedule = []
    for rep in reps:
        for task in rng.sample(tasks, len(tasks)):
            schedule += [{"rep": rep, "task": task, "arm": arm} for arm in rng.sample(arms, len(arms))]
    return schedule


def read_text(path: Path) -> str:
    return path.read_text(errors="replace") if path.exists() else ""


def events(events_path: Path) -> list[dict]:
    out = []
    for line in read_text(events_path).splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # Genie interleaves non-JSON progress lines; they carry no usage data
    return out


def token_usage(events_path: Path) -> dict[str, int]:
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for event in events(events_path):
        if event.get("type") == "turn.completed":
            for key in totals:
                totals[key] += int((event.get("usage") or {}).get(key, 0))
    return totals


def opened_skills(events_path: Path) -> list[str]:
    """Skills whose SKILL.md the agent read with a shell command, in first-open order."""
    order: list[str] = []
    for event in events(events_path):
        item = event.get("item") or {}
        if event.get("type") == "item.started" and item.get("type") == "command_execution":
            order += [n for n in SKILL_OPEN.findall(item.get("command", "")) if n not in order]
    return order


def rate_limited(events_path: Path) -> bool:
    text = read_text(events_path)
    return "REQUEST_LIMIT_EXCEEDED" in text and '"turn.failed"' in text


def network_failure(events_path: Path) -> str | None:
    failed = [line for line in read_text(events_path).splitlines() if '"turn.failed"' in line]
    return next((k for k, ms in NETWORK_FAILURES.items() if any(m in line for m in ms for line in failed)), None)


def link_data(src: Path, dest: Path) -> None:
    """Read-only hard links to the task's files (a symlinked folder looked empty to some agents)."""
    for path in src.rglob("*"):
        if path.is_file():
            path.chmod(0o444)

    def link(s: str, d: str) -> None:
        try:
            os.link(s, d)
        except OSError:
            shutil.copy2(s, d)

    shutil.copytree(src, dest, copy_function=link)


def prepare_workdir(wd: Path, task: str, arm: dict) -> tuple[list[str], dict[str, str]]:
    wd.mkdir(parents=True)
    link_data(EB_HOME / "data" / task, wd / "data")
    subprocess.run(["git", "init", "-q"], cwd=wd, check=True)  # project skills are found from the repo root
    skills = install_skills(arm["sha"], wd / SKILLS_DIR) if arm["sha"] else []
    if arm.get("instructions"):
        shutil.copyfile(INSTRUCTIONS_DIR / f"{arm['instructions']}.md", wd / INSTRUCTIONS_FILE)
    subprocess.run(["uv", "venv", "--quiet", "--seed", "--python", PYTHON_VERSION, str(wd / ".venv")], check=True)
    zdotdir = wd / ".zdotdir"
    zdotdir.mkdir()
    (zdotdir / ".zprofile").write_text(f'export PATH="{wd / ".venv" / "bin"}:$PATH"\n')
    cache = wd / ".cache"
    env = {
        **os.environ,
        "PATH": f"{wd / '.venv' / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "VIRTUAL_ENV": str(wd / ".venv"), "ZDOTDIR": str(zdotdir), "XDG_CACHE_HOME": str(cache),
        "UV_CACHE_DIR": str(cache / "uv"), "PIP_CACHE_DIR": str(cache / "pip"),
        "MPLCONFIGDIR": str(cache / "matplotlib"),
    }
    return skills, env


def clean_workdir(wd: Path) -> list[str]:
    """Record the agent's packages, then drop the venv, caches and large leftovers. Outputs stay."""
    python = wd / ".venv" / "bin" / "python"
    if python.exists():
        freeze = subprocess.run([str(python), "-m", "pip", "freeze"], capture_output=True, text=True, check=False)
        (wd / "pip-freeze.txt").write_text(freeze.stdout)
    for name in (".venv", ".cache"):
        shutil.rmtree(wd / name, ignore_errors=True)
    removed = []
    for path in wd.rglob("*"):
        if path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1 \
                and path.stat().st_size > MAX_KEPT_FILE_BYTES and str(path.relative_to(wd)) not in RUN_RECORD:
            removed.append(str(path.relative_to(wd)))
            path.unlink()
    return removed


def _attempt(wd: Path, task: str, arm: dict, prompt: str) -> tuple[list[str], object, dt.datetime]:
    shutil.rmtree(wd, ignore_errors=True)  # every attempt starts clean, so a retry sees what a first try sees
    skills, env = prepare_workdir(wd, task, arm)
    started = dt.datetime.now(dt.timezone.utc)
    with open(wd / "events.jsonl", "w") as out, open(wd / "stderr.log", "w") as err:
        try:
            returncode: object = subprocess.run(
                [*GENIE_CMD, prompt], cwd=wd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                timeout=AGENT_TIMEOUT_S, check=False).returncode
        except subprocess.TimeoutExpired:
            returncode = "timeout"
    return skills, returncode, started


def _quarantine(run_dir: Path, wd: Path, item: dict, reason: str, started: dt.datetime) -> dict:
    network_blocked.set()
    dest = EB_HOME / "infra-failed" / (f"{run_dir.name}-{item['task']}-{item['arm']}-rep{item['rep']}-{reason}-"
                                        f"{started:%Y%m%dT%H%M%S}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(wd, dest)
    print(f"{item['task']}/{item['arm']}/rep{item['rep']}: network failure ({reason}); moved to {dest}", flush=True)
    return {**item, "skipped": reason}


def run_one(run_dir: Path, item: dict, arms: dict[str, dict], provenance: dict) -> dict:
    task, arm, rep = item["task"], item["arm"], item["rep"]
    wd = run_dir / task / arm / f"rep{rep}"
    if (wd / "run.json").exists():
        meta = json.loads((wd / "run.json").read_text())
        if not meta.get("rate_limited"):
            return meta
    if shutil.disk_usage(EB_HOME).free / 1024**3 < MIN_FREE_GB:
        return {**item, "skipped": "low_disk"}
    if network_blocked.is_set():
        return {**item, "skipped": "network"}
    prompt = (EB_GRADING / task / "instruction.md").read_text()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        skills, returncode, started = _attempt(wd, task, arms[arm], prompt)
        if not rate_limited(wd / "events.jsonl") or attempt == MAX_ATTEMPTS:
            break
        time.sleep(RATE_LIMIT_BACKOFF_S * attempt)
    if reason := network_failure(wd / "events.jsonl"):
        return _quarantine(run_dir, wd, item, reason, started)
    ended = dt.datetime.now(dt.timezone.utc)
    meta = {
        **item, **{f"arm_{k}": v for k, v in arms[arm].items()}, "skills": skills, "returncode": returncode,
        "attempts": attempt, "rate_limited": rate_limited(wd / "events.jsonl"), "started_at": started.isoformat(),
        "ended_at": ended.isoformat(), "wall_s": round((ended - started).total_seconds()),
        "has_answer": (wd / "answer.json").exists(), "has_trace": (wd / "trace.md").exists(),
        "opened": opened_skills(wd / "events.jsonl"), **token_usage(wd / "events.jsonl"), **provenance,
        "data_version": data_version(task), "removed_large_files": clean_workdir(wd),
    }
    (wd / "run.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: meta[k] for k in ("task", "arm", "rep", "returncode", "attempts", "wall_s", "has_answer")}),
          flush=True)
    return meta


def resume_or_pin(schedule_path: Path, arms: dict[str, dict], schedule: list[dict]) -> dict[str, dict]:
    """A rerun of the same command keeps the SHAs the first call pinned, even if a ref has moved since."""
    if not schedule_path.exists():
        return arms
    prev = json.loads(schedule_path.read_text())
    if list(prev["arms"]) != list(arms) or prev["schedule"] != schedule:
        sys.exit(f"{schedule_path} has other arms or tasks; resume with the same command, or use a new --run-id")
    return prev["arms"]


def check_user_skills(arms: dict[str, dict]) -> None:
    """Personal skills are turned off by name, which would also turn off a project skill with the same name."""
    ours = {name for arm in arms.values() if arm["sha"] for name in skill_bundles(arm["sha"])}
    if clash := sorted(set(user_skill_names()) & ours):
        sys.exit(f"Personal skills named like Energy Skills would turn those off in every arm: {clash}. "
                 f"Remove them from {', '.join(map(str, USER_SKILL_DIRS))} for the study.")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--skill", help="run the tasks labeled as covered by this skill")
    ap.add_argument("--controls", type=int, help="number of control tasks to add (default: all)")
    ap.add_argument("--tier", choices=taskset.TIERS, help="restrict to tier P or R")
    ap.add_argument("--tasks", nargs="*", help="task ids (overrides --skill and --controls)")
    ap.add_argument("--arm", action="append", required=True, help=f"`{NO_SKILLS}` or NAME=GIT_REF[:INSTRUCTIONS]")
    ap.add_argument("--reps", type=int, default=3, help="replicates per (task, arm)")
    ap.add_argument("--rep-start", type=int, default=1)
    ap.add_argument("--seed", type=int, default=20261014)
    ap.add_argument("--jobs", type=int, default=1)
    return ap.parse_args()


def main() -> None:
    args = _parse_args()
    arms = resolve_arms(args.arm)
    if 'model_provider = "databricks"' not in read_text(GENIE_HOME / "config.toml"):
        sys.exit("Genie is not connected to Databricks: run `genie` once and finish onboarding.")
    labeled = taskset.load()
    tasks = args.tasks or taskset.select(labeled["tasks"], args.skill, args.controls, args.seed, args.tier)
    missing = [t for t in tasks if not (EB_HOME / "data" / t).is_dir() or not (EB_GRADING / t).is_dir()]
    if missing:
        sys.exit(f"Run generate.py (tier P) or fetch.py (tier R) first; missing: {missing}")
    run_dir = EB_HOME / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    reps = list(range(args.rep_start, args.rep_start + args.reps))
    schedule = build_schedule(tasks, list(arms), reps, args.seed)
    config = read_text(GENIE_HOME / "config.toml")
    provenance = {
        "genie_version": subprocess.run(["genie", "--version"], capture_output=True, text=True, check=True).stdout.strip(),
        "model": (re.search(r'^model\s*=\s*"([^"]+)"', config, flags=re.MULTILINE) or [None, None])[1],
        "harness_sha": git("rev-parse", "HEAD"), "labels_skills_sha": labeled["labels"].get("skills_sha"),
    }
    schedule_path = run_dir / f"schedule-rep{reps[0]}-{reps[-1]}.json"
    resumed = schedule_path.exists()
    arms = resume_or_pin(schedule_path, arms, schedule)
    if not resumed:
        schedule_path.write_text(json.dumps({"seed": args.seed, "skill": args.skill, "arms": arms,
                                             "provenance": provenance, "schedule": schedule,
                                             "written_at": dt.datetime.now(dt.timezone.utc).isoformat()}, indent=2))
    check_user_skills(arms)
    print(f"Genie profile: {write_genie_profile()} ({len(user_skill_names())} user skills disabled)")
    print(f"Schedule: {schedule_path} ({len(schedule)} runs)", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda item: run_one(run_dir, item, arms, provenance), schedule))
    (run_dir / f"runs-rep{reps[0]}-{reps[-1]}.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
