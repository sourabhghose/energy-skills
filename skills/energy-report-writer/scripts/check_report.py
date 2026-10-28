#!/usr/bin/env python3
"""Pre-delivery check for an energy report draft (.tex or .md).

Fails when the draft:
  - references a fact id that is not in the ledger
  - states a number in prose without a fact reference (years and names exempt)
  - lacks the notices required for its report type (review notice, not-advice
    notice, reserves caution for reserves reports, and so on)
  - uses reserves-classification terms (proved, probable, 2P, contingent
    resources, ...) in a reserves-production-summary

On success, writes the rendered draft (facts substituted) next to the input
as <name>.rendered.<ext> and prints the facts used.

Usage:
  python check_report.py report.tex --ledger facts.json --report-type reliability-annual
  python check_report.py summary.md --ledger facts.json --report-type esg-disclosure --syntax markdown
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from facts_ledger import (  # noqa: E402
    find_untraced_numbers,
    load_ledger,
    referenced_ids,
    render,
)

REVIEW_NOTICE = "requires review by a qualified"
NOT_ADVICE = "not legal, regulatory, or investment advice"
RESERVES_CAUTION = "not a reserves report"
ESTIMATE_NOTICE = "estimates"

REPORT_TYPES: dict[str, tuple[str, ...]] = {
    "engineering-study": (REVIEW_NOTICE,),
    "internal-brief": (REVIEW_NOTICE,),
    "reliability-annual": (REVIEW_NOTICE, NOT_ADVICE),
    "rate-case-exhibit": (REVIEW_NOTICE, NOT_ADVICE),
    "regulatory-form-commentary": (REVIEW_NOTICE, NOT_ADVICE),
    "esg-disclosure": (REVIEW_NOTICE, NOT_ADVICE, ESTIMATE_NOTICE),
    "reserves-production-summary": (REVIEW_NOTICE, NOT_ADVICE, RESERVES_CAUTION),
}


# Volumes in a production summary are decline-analysis outputs, never classified reserves.
RESERVES_TERMS = re.compile(
    r"\b(?:proved|(?:probable|possible) (?:reserves|volumes|case)|[123]P|PDP|PUD|"
    r"contingent resources?|prospective resources?|reserves(?! (?:report|evaluator)))\b",
    re.IGNORECASE,
)
FORBIDDEN_TERMS: dict[str, re.Pattern] = {"reserves-production-summary": RESERVES_TERMS}


def forbidden_terms(text: str, report_type: str) -> list[str]:
    pattern = FORBIDDEN_TERMS.get(report_type)
    return sorted({m.group() for m in pattern.finditer(text)}) if pattern else []


def missing_notices(text: str, report_type: str) -> list[str]:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {sorted(REPORT_TYPES)}")
    flat = " ".join(text.lower().split())
    return [phrase for phrase in REPORT_TYPES[report_type] if phrase not in flat]


def check(text: str, ledger: dict, report_type: str, syntax: str) -> list[str]:
    """Return a list of human-readable problems; empty means ready to render."""
    problems = [f"fact not in ledger: {fid}"
                for fid in sorted(set(referenced_ids(text, syntax)) - set(ledger))]
    problems += [f"line {n.line}: untraced number {n.token!r} in: {n.context}"
                 for n in find_untraced_numbers(text, syntax)]
    problems += [f"missing required notice containing: {phrase!r}"
                 for phrase in missing_notices(text, report_type)]
    problems += [f"term not allowed in {report_type}: {term!r} (needs a qualified reserves evaluator)"
                 for term in forbidden_terms(text, report_type)]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("draft", type=Path)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--report-type", required=True, choices=sorted(REPORT_TYPES))
    parser.add_argument("--syntax", choices=("latex", "markdown"), default=None,
                        help="default: latex for .tex, markdown otherwise")
    args = parser.parse_args(argv)
    syntax = args.syntax or ("latex" if args.draft.suffix == ".tex" else "markdown")
    text = args.draft.read_text(encoding="utf-8")
    ledger = load_ledger(args.ledger)
    problems = check(text, ledger, args.report_type, syntax)
    if problems:
        for problem in problems:
            print(f"  ✗ {problem}")
        print(f"FAIL  {args.draft}  ({len(problems)} problem(s))")
        return 1
    out = args.draft.with_suffix(f".rendered{args.draft.suffix}")
    out.write_text(render(text, ledger, syntax), encoding="utf-8")
    used = sorted(set(referenced_ids(text, syntax)))
    print(f"OK  {args.draft} -> {out}  ({len(used)} fact(s): {', '.join(used)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
