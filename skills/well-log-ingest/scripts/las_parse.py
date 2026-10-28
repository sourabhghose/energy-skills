"""Read LAS files with lasio into a plain, library-independent ParsedLas.

lasio does the parsing (LAS 1.2 / 2.0 fully; LAS 3.0 partially: only the first data
section is read). This adapter copies what downstream needs into frozen dataclasses, so the
normalization core (las_core.py) never touches lasio objects and can be tested without it.

Usage:
    from las_parse import read_las
    parsed = read_las("/Volumes/main/subsurface/raw_logs/well_a.las")   # or LAS text
"""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeaderItem:
    mnemonic: str
    unit: str
    value: str
    descr: str


@dataclass(frozen=True)
class CurveInfo:
    mnemonic: str          # as stored by lasio (duplicates renamed GR:1, GR:2)
    original_mnemonic: str
    unit: str
    descr: str


@dataclass(frozen=True)
class ParsedLas:
    source: str
    sha256: str
    version: str
    wrap: bool
    well: dict[str, HeaderItem]
    params: dict[str, HeaderItem]
    curves: tuple[CurveInfo, ...]
    data: pd.DataFrame     # columns = curve mnemonics; first column is the depth index
    null_value: float | None
    warnings: tuple[str, ...] = ()

    def well_value(self, *mnemonics: str) -> str:
        """First non-empty ~Well (then ~Parameter) value among mnemonics."""
        for section in (self.well, self.params):
            for m in mnemonics:
                item = section.get(m)
                if item is not None and str(item.value).strip():
                    return str(item.value).strip()
        return ""

    def well_item(self, *mnemonics: str) -> HeaderItem | None:
        for section in (self.well, self.params):
            for m in mnemonics:
                if m in section and str(section[m].value).strip():
                    return section[m]
        return None


def _items(section) -> dict[str, HeaderItem]:
    return {item.mnemonic.upper(): HeaderItem(item.mnemonic.upper(), str(item.unit or ""),
                                             str(item.value if item.value is not None else ""),
                                             str(item.descr or "")) for item in section}


def _null(well: dict[str, HeaderItem]) -> float | None:
    item = well.get("NULL")
    try:
        return float(item.value) if item is not None else None
    except ValueError:
        logger.warning("Unparseable NULL value %r", item.value)
        return None


def _source_text(source: str | Path) -> tuple[str, str]:
    text = str(source)
    if "\n" in text:
        return "<text>", text
    raw = Path(text).read_bytes()
    return text, raw.decode("utf-8", errors="replace")


def read_las(source: str | Path) -> ParsedLas:
    """Parse a LAS file path or LAS text. NULL from the header becomes NaN (lasio 'strict')."""
    import lasio

    name, text = _source_text(source)
    las = lasio.read(io.StringIO(text), null_policy="strict", ignore_header_errors=False)
    well = _items(las.well)
    curves = tuple(CurveInfo(c.mnemonic, getattr(c, "original_mnemonic", c.mnemonic) or c.mnemonic,
                             str(c.unit or ""), str(c.descr or "")) for c in las.curves)
    data = pd.DataFrame(las.data, columns=[c.mnemonic for c in curves])
    version_items = _items(las.version)
    version = version_items.get("VERS").value if "VERS" in version_items else ""
    wrap = version_items.get("WRAP").value.strip().upper() in ("YES", "Y") if "WRAP" in version_items else False
    warnings = []
    if str(version).startswith("3"):
        warnings.append("LAS 3.0: lasio reads only the first data section; check for extra ~Log sections")
    return ParsedLas(source=name, sha256=hashlib.sha256(text.encode()).hexdigest(), version=str(version),
                     wrap=wrap, well=well, params=_items(las.params), curves=curves, data=data,
                     null_value=_null(well), warnings=tuple(warnings))
