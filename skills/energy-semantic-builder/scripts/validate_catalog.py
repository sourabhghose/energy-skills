#!/usr/bin/env python3
"""Correctness gate for the energy measure catalog.

ERRORS: missing keys (incl. unit), bad metric_view naming / domain prefix, unknown entity,
atomic using MEASURE(), composite without MEASURE() (non-additive trap), MEASURE() of a
measure outside its metric view, depends_on mismatch, undeclared placeholders, duplicates.
WARNINGS: atomic expr referencing a non-field identifier.

Usage: python3 scripts/validate_catalog.py [--strict]
"""

from __future__ import annotations

import sys

from semantic_core import load_catalog, validate_catalog


def main() -> int:
    cat = load_catalog()
    rep = validate_catalog(cat)
    for w in rep.warnings:
        print(f"WARN  {w}")
    for e in rep.errors:
        print(f"ERROR {e}")
    print(f"\nchecked {len(cat.measures)} measures across {len(cat.metric_views)} metric views: "
          f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    strict = "--strict" in sys.argv
    return 1 if rep.errors or (strict and rep.warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
