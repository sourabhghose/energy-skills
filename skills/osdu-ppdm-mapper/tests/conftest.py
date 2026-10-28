"""Put this skill's scripts/ on sys.path and provide a vendor-style well header fixture."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pandas as pd
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
for _mod in ("uc_io", "canonical_model", "identifiers", "geo", "mapping_spec", "mapping_apply",
             "osdu_records", "mapping_run"):
    sys.modules.pop(_mod, None)


@pytest.fixture
def header() -> pd.DataFrame:
    """Completion-level vendor extract: two completions share wellbore 423011234500."""
    return pd.DataFrame({
        "API_NO": ["42-301-12345-00-00", "42-301-12345-00-01", "42-301-12346-01-00", "42-301-12347-00-00",
                   "42-301-12347-00-00"],
        "LEASE_WELL": ["SMITH 1H", "SMITH 1H", "JONES 2H ST1", "BROWN 3", "BROWN 3"],
        "OPERATOR": ["Acme Energy", "Acme Energy", "Acme Energy", "Borealis", "Borealis"],
        "WELL_STATUS": ["PR", "PR", "SI", "P&A", "P&A"],
        "SURF_LAT": [31.90, 31.90, 31.95, 32.01, 32.01],
        "SURF_LONG": [-103.40, -103.40, -103.45, -103.50, -103.50],
        "TD": [18500, 18500, 17900, 9800, 9800],
        "DATUM": ["NAD27", "NAD27", "NAD27", "NAD83", "NAD83"],
    })


@pytest.fixture
def reviewed_spec(header):
    from mapping_spec import propose_mapping

    spec = copy.deepcopy(propose_mapping(header, "wellbore", "main.raw.header"))
    spec["fields"]["total_depth_md"]["uom"] = "ft"
    spec["status"] = "reviewed"
    return spec
