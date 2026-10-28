"""Facts ledger: every number in an energy report comes from a result table or run manifest.

The report draft never contains bare figures. It references facts by id
(`\\fact{saidi_2025_excl_med}` in LaTeX, `{{fact:saidi_2025_excl_med}}` in
Markdown); `render()` substitutes the value and unit from the ledger, and
`find_untraced_numbers()` flags any number the draft states without a fact.

Usage:
    from facts_ledger import build_ledger, records_from_rows, render, find_untraced_numbers
    ledger = build_ledger(records_from_rows(rows, id_key="metric", value_key="value",
                                            unit_key="unit", source="main.rel.saidi_annual"))
    problems = find_untraced_numbers(draft, syntax="latex")
    final = render(draft, ledger, syntax="latex")
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

FACT_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,79}$")
FACT_REF = {
    "latex": re.compile(r"\\fact\{([^}]*)\}"),
    "markdown": re.compile(r"\{\{fact:([^}]*)\}\}"),
}
NUMBER = re.compile(r"(?<![\w.])[-−]?\d[\d,]*(?:\.\d+)?(?![\w])")
YEAR = re.compile(r"^(19|20)\d{2}$")

# Tokens directly after these words are names, not figures (Scope 2, IEEE 1366, Form 1).
NAME_PREFIXES = (
    "figure", "fig.", "table", "section", "appendix", "step", "scope", "tier", "phase",
    "form", "rule", "subpart", "part", "ieee", "iec", "iso", "api", "nerc", "ferc", "eia",
    "epa", "ar", "chapter", "item", "exhibit", "schedule", "page", "version", "v",
)
# LaTeX commands whose arguments never hold reported figures.
LATEX_STRUCTURAL = re.compile(
    r"\\(?:label|ref|eqref|cite|includegraphics|input|include|bibliography|bibliographystyle|"
    r"documentclass|usepackage|fpath|texttt|url|href|hspace|vspace|setlength|fact)"
    r"(?:\[[^\]]*\])?\{[^}]*\}"
)
LATEX_OPTIONS = re.compile(r"\[[^\]]*(?:width|height|scale|pt|cm|in|em)[^\]]*\]")
LATEX_COMMENT = re.compile(r"(?<!\\)%.*$")
MARKDOWN_STRUCTURAL = re.compile(r"`[^`]*`|\]\([^)]*\)|^#{1,6}\s.*$|^\s*\d+\.\s", re.M)


class UnknownFact(KeyError):
    """A draft references a fact id that is not in the ledger."""


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: float
    unit: str
    source: str
    decimals: int | None = None

    def formatted(self) -> str:
        decimals = self.decimals if self.decimals is not None else _auto_decimals(self.value)
        number = f"{self.value:,.{decimals}f}"
        return f"{number} {self.unit}".strip() if self.unit != "-" else number


@dataclass(frozen=True)
class UntracedNumber:
    line: int
    token: str
    context: str


def _auto_decimals(value: float) -> int:
    magnitude = abs(value)
    if magnitude >= 100 or float(value).is_integer():
        return 0
    return 1 if magnitude >= 10 else 2


def _validate_record(record: Mapping) -> Fact:
    fact_id = str(record.get("fact_id", ""))
    if not FACT_ID.match(fact_id):
        raise ValueError(f"fact_id {fact_id!r} must match {FACT_ID.pattern}")
    try:
        value = float(record["value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{fact_id}: value must be numeric, got {record.get('value')!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"{fact_id}: value must be finite, got {value}")
    unit = str(record.get("unit") or "").strip()
    if not unit:
        raise ValueError(f"{fact_id}: unit is required (use '-' for dimensionless counts)")
    source = str(record.get("source") or "").strip()
    if not source:
        raise ValueError(f"{fact_id}: source (table, manifest, or query) is required")
    decimals = record.get("decimals")
    return Fact(fact_id, value, unit, source, None if decimals is None else int(decimals))


def build_ledger(records: Iterable[Mapping]) -> dict[str, Fact]:
    """Validate records into an immutable-by-convention {fact_id: Fact} mapping."""
    ledger: dict[str, Fact] = {}
    for record in records:
        fact = _validate_record(record)
        if fact.fact_id in ledger:
            raise ValueError(f"duplicate fact_id {fact.fact_id!r}")
        ledger = {**ledger, fact.fact_id: fact}
    return ledger


def records_from_rows(rows: Iterable[Mapping], *, id_key: str, value_key: str,
                      unit_key: str, source: str, prefix: str = "") -> list[dict]:
    """Turn result-table rows (e.g. `df.to_dict('records')`) into ledger records."""
    return [
        {"fact_id": f"{prefix}{row[id_key]}".lower(), "value": row[value_key],
         "unit": row[unit_key], "source": source}
        for row in rows
    ]


def load_ledger(path: str | Path) -> dict[str, Fact]:
    """Load a ledger saved as a JSON array of records."""
    return build_ledger(json.loads(Path(path).read_text(encoding="utf-8")))


def save_ledger(ledger: Mapping[str, Fact], path: str | Path) -> None:
    records = [{"fact_id": f.fact_id, "value": f.value, "unit": f.unit, "source": f.source,
                "decimals": f.decimals} for f in ledger.values()]
    Path(path).write_text(json.dumps(records, indent=2), encoding="utf-8")


def referenced_ids(text: str, syntax: str = "latex") -> list[str]:
    return [m.strip() for m in FACT_REF[syntax].findall(text)]


def render(text: str, ledger: Mapping[str, Fact], syntax: str = "latex") -> str:
    """Replace every fact reference with its formatted value and unit."""
    missing = sorted({fid for fid in referenced_ids(text, syntax) if fid not in ledger})
    if missing:
        raise UnknownFact(f"draft references facts not in the ledger: {missing}")
    escape = (lambda s: s.replace("%", r"\%")) if syntax == "latex" else (lambda s: s)
    return FACT_REF[syntax].sub(lambda m: escape(ledger[m.group(1).strip()].formatted()), text)


def _strip_structural(line: str, syntax: str) -> str:
    if syntax == "latex":
        line = LATEX_COMMENT.sub("", line)
        line = LATEX_STRUCTURAL.sub(" ", line)
        return LATEX_OPTIONS.sub(" ", line)
    return MARKDOWN_STRUCTURAL.sub(" ", FACT_REF["markdown"].sub(" ", line))


def _is_exempt(token: str, before: str, after: str) -> bool:
    plain = token.replace(",", "").lstrip("-−")
    if YEAR.match(plain):
        return True
    if re.match(r"-[A-Za-z]", after):  # compound adjective: 15-minute, 5-year
        return True
    words = re.findall(r"[A-Za-z.]+", before[-14:])
    return bool(words) and words[-1].lower().rstrip("~") in NAME_PREFIXES


def find_untraced_numbers(text: str, syntax: str = "latex") -> list[UntracedNumber]:
    """Numbers stated in prose without a fact reference (years and names exempt)."""
    if syntax not in FACT_REF:
        raise ValueError(f"syntax must be one of {sorted(FACT_REF)}")
    body = text.split(r"\begin{document}", 1)[-1] if syntax == "latex" else text
    found: list[UntracedNumber] = []
    for line_no, raw in enumerate(body.splitlines(), 1):
        line = _strip_structural(raw, syntax)
        for match in NUMBER.finditer(line):
            if not _is_exempt(match.group(), line[: match.start()], line[match.end():]):
                found = [*found, UntracedNumber(line_no, match.group(), raw.strip()[:120])]
    return found


def ledger_appendix(ledger: Mapping[str, Fact], used: Iterable[str], syntax: str = "latex") -> str:
    """A 'Sources of figures' table for the facts the report uses."""
    facts = [ledger[fid] for fid in dict.fromkeys(used)]
    if syntax == "markdown":
        rows = [f"| `{f.fact_id}` | {f.formatted()} | `{f.source}` |" for f in facts]
        return "\n".join(["| Fact | Value | Source |", "|------|-------|--------|", *rows])
    esc = lambda s: s.replace("_", r"\_").replace("%", r"\%").replace("&", r"\&")  # noqa: E731
    rows = [rf"\texttt{{{esc(f.fact_id)}}} & {esc(f.formatted())} & \texttt{{{esc(f.source)}}} \\"
            for f in facts]
    return "\n".join([r"\begin{tabular}{lll}", r"\toprule", r"Fact & Value & Source \\",
                      r"\midrule", *rows, r"\bottomrule", r"\end{tabular}"])
