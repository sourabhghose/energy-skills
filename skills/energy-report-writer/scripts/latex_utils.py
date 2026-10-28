"""LaTeX helpers for energy reports: escape prose, break long paths, format unit labels.

Usage:
    from latex_utils import latex_escape, fpath, unit_label
    latex_escape("O&M cost 5% of capex_total")   # 'O\\&M cost 5\\% of capex\\_total'
    fpath("/Volumes/main/grid/reports/2025")     # '\\fpath{/\\allowbreak Volumes/...}'
    unit_label("Load", "MW")                     # 'Load (MW)'
"""

from __future__ import annotations

import re

_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_ESCAPE_RE = re.compile("|".join(re.escape(c) for c in _ESCAPES))

# Unit spellings for axis labels and tables; superscripts via math mode.
UNIT_LATEX = {
    "m3": r"m$^3$", "co2e": r"CO$_2$e", "tco2e": r"tCO$_2$e", "mtco2e": r"MtCO$_2$e",
    "kgco2e/mwh": r"kgCO$_2$e/MWh", "deg_c": r"$^\circ$C", "m/s": "m/s",
}


def latex_escape(text: str) -> str:
    """Escape LaTeX special characters in plain prose."""
    return _ESCAPE_RE.sub(lambda m: _ESCAPES[m.group()], text)


def fpath(path: str) -> str:
    """Wrap a long path or table name so it can break after / . _ - @."""
    escaped = latex_escape(path)
    breakable = re.sub(r"(/|\\_|\.|-|@)", r"\1\\allowbreak ", escaped)
    return rf"\fpath{{{breakable}}}"


def unit_label(quantity: str, unit: str) -> str:
    """'Quantity (unit)' with LaTeX-safe unit spelling."""
    pretty = UNIT_LATEX.get(unit.lower(), latex_escape(unit))
    return f"{latex_escape(quantity)} ({pretty})"
