"""Deterministic scoring of an agent's ./answer.json (and output files) against a task's planted answer key.

Each `[[check]]` in a task.toml is one of the types in CHECKS. A check earns its `points` when it passes; set and map
checks earn partial credit. The deterministic score is earned / possible x 100. Values in the answer key are looked
up by `expected` (default: the check's `key`); keys starting with `_` (pitfall values) are never used for scoring.

Stdlib only, so CI can test it without the judge's dependencies.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

NUMBER = re.compile(r"[-+]?\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?|[-+]?\.\d+")


def norm(value: object) -> str:
    """Case-, space- and punctuation-insensitive form for ids, names and map keys."""
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        m = NUMBER.search(value)
        if m:
            try:
                return float(m.group(0).replace(",", ""))
            except ValueError:
                return None
    return None


def close(actual: object, expected: float, check: dict) -> bool:
    got = to_number(actual)
    if got is None:
        return False
    if "abs_tol" in check:
        return abs(got - expected) <= float(check["abs_tol"])
    return abs(got - expected) <= float(check.get("rel_tol", 1e-3)) * max(abs(expected), 1e-12)


def load_answer(workdir: Path) -> tuple[dict | None, str]:
    """(answer dict or None, problem). Tolerates a code fence or prose around the JSON object."""
    path = workdir / "answer.json"
    if not path.is_file():
        return None, "no answer.json"
    text = path.read_text(errors="replace")
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        try:
            data = json.loads(text[start:end + 1]) if start >= 0 else None
        except ValueError:
            return None, "answer.json is not valid JSON"
    return (data, "") if isinstance(data, dict) else (None, "answer.json is not a JSON object")


def _expected(check: dict, key: dict, field: str = "expected") -> object:
    name = check.get(field, check["key"])
    if str(name).startswith("_"):
        raise ValueError(f"check uses pitfall value {name!r}")
    return key[name]


def _get(answer: dict, dotted: str) -> object:
    cur: object = answer
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = {norm(k): v for k, v in cur.items()}.get(norm(part))
    return cur


def c_numeric(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    exp = float(_expected(check, key))
    got = _get(answer, check["key"])
    return float(close(got, exp, check)), f"got {got!r}, expected {exp}"


def c_numeric_any(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    options = [float(key[k]) for k in check["expected_any"]]
    got = _get(answer, check["key"])
    return float(any(close(got, o, check) for o in options)), f"got {got!r}, expected one of {options}"


def c_numeric_range(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    low, high = float(key[check["low"]]), float(key[check["high"]])
    got = to_number(_get(answer, check["key"]))
    return float(got is not None and low <= got <= high), f"got {got!r}, allowed [{low}, {high}]"


def c_numeric_map(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    exp = _expected(check, key)
    got = _get(answer, check["key"])
    got = {norm(k): v for k, v in got.items()} if isinstance(got, dict) else {}
    hits = [k for k, v in exp.items() if close(got.get(norm(k)), float(v), check)]
    return len(hits) / len(exp), f"{len(hits)}/{len(exp)} within tolerance"


def c_exact(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    exp, got = _expected(check, key), _get(answer, check["key"])
    num_e, num_g = to_number(exp), to_number(got)
    ok = num_e == num_g if num_e is not None and not isinstance(exp, str) else norm(got) == norm(exp)
    return float(ok and got is not None), f"got {got!r}, expected {exp!r}"


def c_set_f1(check: dict, key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    exp = {norm(v) for v in _expected(check, key)}
    got_raw = _get(answer, check["key"])
    got = {norm(v) for v in got_raw} if isinstance(got_raw, list) else set()
    tp = len(exp & got)
    if not exp and not got:
        return 1.0, "both empty"
    f1 = 2 * tp / (len(exp) + len(got)) if (exp or got) else 0.0
    return f1, f"F1 {f1:.2f} (tp {tp}, predicted {len(got)}, true {len(exp)})"


def c_decision(check: dict, _key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    """Ask-before-assuming: every pattern group must match the agent's `decisions` text."""
    text = json.dumps(answer.get("decisions", ""), ensure_ascii=False)
    missing = [g for g in check["patterns"] if not any(re.search(p, text, re.IGNORECASE) for p in g)]
    return float(not missing), "surfaced" if not missing else f"not surfaced: {missing}"


def c_forbid_in_list(check: dict, _key: dict, answer: dict, _wd: Path) -> tuple[float, str]:
    items = _get(answer, check["key"])
    if not isinstance(items, list) or not items:
        return 0.0, f"{check['key']} missing or empty"
    bad = [i for i in items if any(re.search(p, str(i), re.IGNORECASE) for p in check["patterns"])]
    return float(not bad), "clean" if not bad else f"forbidden items: {bad}"


def c_file_exists(check: dict, _key: dict, _answer: dict, wd: Path) -> tuple[float, str]:
    hits = sorted(wd.glob(check["path"]))
    return float(any(h.is_file() and h.stat().st_size > 0 for h in hits)), f"{len(hits)} file(s) at {check['path']}"


def _read_rows(wd: Path, pattern: str) -> list[dict[str, str]] | None:
    hits = sorted(p for p in wd.glob(pattern) if p.is_file())
    if not hits:
        return None
    with open(hits[0], newline="", encoding="utf-8", errors="replace") as f:
        return [{norm(k): v for k, v in row.items() if k is not None} for row in csv.DictReader(f)]


def c_file_forbid(check: dict, key: dict, _answer: dict, wd: Path) -> tuple[float, str]:
    hits = sorted(p for p in wd.glob(check["path"]) if p.is_file())
    if not hits:
        return 0.0, f"no file at {check['path']}"
    text = "\n".join(h.read_text(errors="replace") for h in hits)
    bad = [r for r in key.get(check.get("regex_from", ""), []) if re.search(r, text)]
    bad += [s for s in key.get(check.get("literals_from", ""), []) if s in text]
    return float(not bad), "clean" if not bad else f"{len(bad)} forbidden value(s), e.g. {bad[:3]}"


def c_csv_min(check: dict, _key: dict, _answer: dict, wd: Path) -> tuple[float, str]:
    rows = _read_rows(wd, check["path"])
    col = norm(check["column"])
    if not rows or col not in rows[0]:
        return 0.0, f"no column {check['column']!r} in {check['path']}"
    values = [to_number(r[col]) for r in rows]
    low = [v for v in values if v is not None and v < float(check["min"])]
    return float(not low), "ok" if not low else f"{len(low)} row(s) below {check['min']}"


def c_csv_sum_any(check: dict, key: dict, _answer: dict, wd: Path) -> tuple[float, str]:
    rows = _read_rows(wd, check["path"])
    col = norm(check["column"])
    if not rows or col not in rows[0]:
        return 0.0, f"no column {check['column']!r} in {check['path']}"
    total = sum(v for v in (to_number(r[col]) for r in rows) if v is not None)
    options = [float(key[k]) for k in check["expected_any"]]
    return float(any(close(total, o, check) for o in options)), f"column sum {total}, expected one of {options}"


CHECKS = {
    "numeric": c_numeric, "numeric_any": c_numeric_any, "numeric_range": c_numeric_range,
    "numeric_map": c_numeric_map, "exact": c_exact, "set_f1": c_set_f1, "decision": c_decision,
    "forbid_in_list": c_forbid_in_list, "file_exists": c_file_exists, "file_forbid": c_file_forbid,
    "csv_min": c_csv_min, "csv_sum_any": c_csv_sum_any,
}


def score_checks(checks: list[dict], key: dict, answer: dict | None, workdir: Path) -> dict:
    """{"det_score": 0-100, "earned", "possible", "checks": [...]} for one run."""
    results, earned, possible = [], 0.0, 0.0
    for check in checks:
        points = float(check["points"])
        possible += points
        if answer is None and check["type"] not in ("file_exists", "file_forbid", "csv_min", "csv_sum_any"):
            frac, detail = 0.0, "no valid answer.json"
        else:
            frac, detail = CHECKS[check["type"]](check, key, answer or {}, workdir)
        earned += points * frac
        results.append({"type": check["type"], "key": check.get("key", check.get("path")), "points": points,
                        "earned": round(points * frac, 3), "detail": detail})
    score = 100 * earned / possible if possible else 0.0
    return {"det_score": round(score, 3), "earned": round(earned, 3), "possible": possible, "checks": results}
