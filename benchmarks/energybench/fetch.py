#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Download the public datasets behind tier-R tasks, verify them against datasets.lock.json, and stage each task.

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.

Downloads are cached in $EB_HOME/cache/<dataset>/. Datasets marked `manual` in datasets.json (registration or a
browser-only download) are read from $EB_HOME/manual/<dataset>/ instead; fetch.py prints what to place there.
Each file's SHA-256 is compared with datasets.lock.json; the first fetch, or a deliberate re-pin, needs
--write-lock. Agent-visible files go to $EB_HOME/data/<task>/<dataset>/, the prompt and rubric to $EB_GRADING/<task>/.

    uv run fetch.py --all                       # every tier-R task
    uv run fetch.py r06-caiso-np15-dam --write-lock
    NREL_API_KEY=... NREL_EMAIL=... uv run fetch.py r08-nsrdb-pv-yield
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import string
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import taskset  # noqa: E402
from paths import EB_GRADING, EB_HOME, sha256_file, write_grading  # noqa: E402

LOCK = HERE / "datasets.lock.json"
USER_AGENT = "energybench-fetch/1.0 (+https://github.com/sourabhghose/energy-skills)"
RETRIES = 4


def resolve_url(template: str, env: dict[str, str]) -> str:
    """Fill {VAR} placeholders from the environment; missing secrets are an error, never an empty string."""
    names = [f for _, f, _, _ in string.Formatter().parse(template) if f]
    missing = [n for n in names if not env.get(n)]
    if missing:
        raise SystemExit(f"Set {', '.join(missing)} in the environment to fetch {template.split('?')[0]}")
    return template.format(**{n: env[n] for n in names})


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=600) as resp, open(part, "wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
            part.replace(dest)
            return
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == RETRIES:
                raise SystemExit(f"download failed ({e.code}) for {url.split('?')[0]}") from e
            print(f"HTTP {e.code}; retrying in {20 * attempt}s", flush=True)
            time.sleep(20 * attempt)


def pin_hash(path: Path, pin: str) -> str:
    """SHA-256 of the file, or for pin='extracted' of the zip members' contents (names can embed timestamps)."""
    if pin != "extracted":
        return sha256_file(path)
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            digest.update(zf.read(info))
    return digest.hexdigest()


def check_lock(lock: dict, dataset: str, name: str, sha: str, moving: bool, write: bool) -> str:
    """'pinned' (matches), 'locked' (recorded now) or raises on a mismatch. Returns the status string."""
    pinned = lock.get(dataset, {}).get(name)
    if pinned == sha:
        return "pinned"
    if write:
        lock.setdefault(dataset, {})[name] = sha
        return "locked"
    if pinned is None:
        raise SystemExit(f"{dataset}/{name} is not in {LOCK.name}; rerun with --write-lock to pin it")
    hint = " (source republishes in place; re-pin deliberately)" if moving else ""
    raise SystemExit(f"{dataset}/{name}: sha256 {sha[:12]} does not match the pinned {pinned[:12]}{hint}")


def obtain(dataset: str, meta: dict, entry: dict, home: Path) -> Path:
    if meta.get("manual"):
        path = home / "manual" / dataset / entry["name"]
        if not path.is_file():
            raise SystemExit(f"{dataset} needs a manual download: {meta.get('notes', '')}\nExpected: {path}")
        return path
    path = home / "cache" / dataset / entry["name"]
    if not path.is_file():
        print(f"downloading {dataset}/{entry['name']}", flush=True)
        download(resolve_url(entry["url"], dict(os.environ)), path)
    return path


def stage_task(task_id: str, lock: dict, write_lock: bool, home: Path = EB_HOME) -> dict:
    spec, registry = taskset.load_spec(task_id), taskset.datasets()
    data = home / "data" / task_id
    files, lines = {}, []
    for ds in spec["task"]["datasets"]:
        meta = registry[ds]
        for entry in meta["files"]:
            src = obtain(ds, meta, entry, home)
            sha = pin_hash(src, meta.get("pin", "file"))
            status = check_lock(lock, ds, entry["name"], sha, bool(meta.get("moving")), write_lock)
            dest = data / ds / entry["name"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                _link_or_copy(src, dest)
            files[f"{ds}/{entry['name']}"] = sha
            print(f"{task_id}: {ds}/{entry['name']} {sha[:12]} {status}")
        lines.append(f"- `{ds}/`: {meta['title']}. License: {meta['license']}.")
    (data / "README.md").write_text("# Data for this task\n\n" + "\n".join(lines) + "\n")
    return {"task": task_id, "tier": "R", "seed": None, "generator_version": None, "files": files}


def _link_or_copy(src: Path, dest: Path) -> None:
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tasks", nargs="*", help="tier-R task ids")
    ap.add_argument("--all", action="store_true", help="every tier-R task in tasks.json")
    ap.add_argument("--write-lock", action="store_true", help="record (or re-pin) sha256 values in the lock file")
    args = ap.parse_args()
    tasks = args.tasks or ([t["task_id"] for t in taskset.load()["tasks"] if t["tier"] == "R"] if args.all else [])
    if not tasks:
        ap.error("pass task ids or --all")
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    for task_id in tasks:
        spec = taskset.load_spec(task_id)
        manifest = stage_task(task_id, lock, args.write_lock)
        write_grading(task_id, taskset.TASKS_DIR / f"{task_id}.toml", taskset.render_instruction(spec),
                      spec["task"]["rubric"], {}, manifest)
        print(f"{task_id}: grading -> {EB_GRADING / task_id}")
    if args.write_lock:
        LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
        print(f"wrote {LOCK}")


if __name__ == "__main__":
    main()
