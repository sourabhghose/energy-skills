"""lasio adapter tests (skipped when lasio is not installed)."""

import numpy as np
import pytest
from conftest import SAMPLE_LAS, decisions

lasio = pytest.importorskip("lasio")

from las_core import normalize_las, profile_las  # noqa: E402
from las_parse import read_las  # noqa: E402


def test_read_sample_text():
    parsed = read_las(SAMPLE_LAS)
    assert parsed.version.startswith("2")
    assert parsed.curves[0].mnemonic == "DEPT"
    assert [c.mnemonic for c in parsed.curves].count("GR") <= 1          # lasio renames duplicates
    assert np.isnan(parsed.data.iloc[1]["AT90"])                         # header NULL -> NaN
    assert parsed.well_value("API") == "05-123-45678"


def test_end_to_end_sample():
    parsed = read_las(SAMPLE_LAS)
    prof = profile_las(parsed)
    assert prof.depth_unit == "ft" and prof.logged_from == "KB"
    assert any(c.family == "GR" for c in prof.curves) and prof.family_conflicts
    norm = normalize_las(parsed, decisions(depth_datum="GL"))
    assert norm.long["depth"].min() == pytest.approx(4975.0)
    assert norm.header["api14"] == "05123456780000"
