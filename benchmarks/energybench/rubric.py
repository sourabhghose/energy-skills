"""Rubric parsing, judge-response scoring and blinding for EnergyBench (stdlib only).

Adapted from databricks-industry-solutions/vital-skills (benchmarks/biomnibench); modified for the energy industry.
The judge picks a level (A/B/C) per criterion; points come from the rubric, never from the model.
"""

from __future__ import annotations

import json
import re


def parse_rubric_levels(rubric_text: str) -> dict[str, dict[str, int]]:
    """{criterion_<N>: {"A": pts, "B": pts, "C": pts}} from `Levels: A=X B=Y C=0` lines."""
    out: dict[str, dict[str, int]] = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric_text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        body = parts[i + 1] if i + 1 < len(parts) else ""
        m = re.search(r"Levels:\s*((?:[A-Z]=\d+\s*)+)", body)
        if m:
            levels = {lm.group(1).upper(): int(lm.group(2)) for lm in re.finditer(r"([A-Z])=(\d+)", m.group(1))}
            out[f"criterion_{parts[i].strip()}"] = levels
    return out


def rubric_max(rubric_text: str) -> int:
    return sum(max(levels.values()) for levels in parse_rubric_levels(rubric_text).values())


def first_json_object(text: str) -> dict:
    """The first complete JSON object in the text. Braces inside JSON strings do not count."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass  # not an object start; keep scanning
        start = text.find("{", start + 1)
    raise ValueError("no complete JSON object in judge response")


def score_response(rubric: str, response_text: str) -> dict:
    """Map the judge's per-criterion levels to rubric points; total clamped to 0-100."""
    try:
        result = first_json_object(response_text)
    except ValueError as e:
        return {"total": 0, "criteria": {}, "reasoning": f"unparseable judge response: {e}"}
    levels = parse_rubric_levels(rubric)
    criteria = {}
    for key, crit in (result.get("criteria") or {}).items():
        if isinstance(crit, dict):
            level = str(crit.get("level") or "").strip().upper()
            criteria[key] = {**crit, "score": levels.get(key, {}).get(level, 0)}
    total = sum(c["score"] for c in criteria.values())
    return {"total": max(0, min(100, total)), "criteria": criteria,
            "reasoning": result.get("overall_reasoning", result.get("reasoning", ""))}


def redact(text: str, skill_names: list[str]) -> str:
    """Remove what would tell the judge which arm ran: skill paths, skill names, instruction files, agent name."""
    text = re.sub(r"\S*\.agents/skills\S*", "[redacted]", text)
    text = re.sub(r"\b(SKILL|AGENTS)\.md\b", "[redacted]", text)
    text = re.sub(r"\bscripts/[\w./-]+\.py\b", "[redacted]", text)
    text = re.sub(r"(?<![\w-])(Genie Code( CLI)?|Genie|Codex( CLI)?)(?![\w-])", "[agent]", text, flags=re.IGNORECASE)
    for name in sorted(skill_names, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", "[redacted]", text)
    return text
