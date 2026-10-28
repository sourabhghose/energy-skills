"""Where EnergyBench keeps data, runs and grades, and how a task's grading folder is written.

$EB_HOME (default ~/energybench) holds agent-visible data, runs, grades and analyses. $EB_GRADING (default
~/.cache/energybench-grading) holds each task's rendered prompt, rubric, checks and answer key, away from every run
folder, so an agent exploring its surroundings does not stumble on the answer key.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
EB_HOME = Path(os.environ.get("EB_HOME", Path.home() / "energybench"))
EB_GRADING = Path(os.environ.get("EB_GRADING", Path.home() / ".cache" / "energybench-grading"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_hashes(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def write_grading(task_id: str, spec_path: Path, instruction: str, rubric: str, answer_key: dict,
                  manifest: dict, grading_root: Path | None = None) -> Path:
    """The grader-only folder for one task. Replaces any previous one, so stale keys never survive."""
    grading = (grading_root or EB_GRADING) / task_id
    if grading.exists():
        shutil.rmtree(grading)
    grading.mkdir(parents=True)
    (grading / "instruction.md").write_text(instruction)
    (grading / "rubric.txt").write_text(rubric.strip() + "\n")
    shutil.copy2(spec_path, grading / "task.toml")
    (grading / "answer_key.json").write_text(json.dumps(answer_key, indent=1, sort_keys=True) + "\n")
    stamped = {**manifest, "written_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    (grading / "data_manifest.json").write_text(json.dumps(stamped, indent=1) + "\n")
    return grading


def data_version(task_id: str, grading_root: Path | None = None) -> str | None:
    """A short hash of the task's data manifest (files and seed), recorded in every run.json."""
    path = (grading_root or EB_GRADING) / task_id / "data_manifest.json"
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text())
    stable = {k: manifest.get(k) for k in ("task", "seed", "generator_version", "files")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()[:16]
