import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

DECISIONS = {"gas_mcf_per_boe": "energy_6", "gads_weighting": "mw_weighted",
             "capacity_basis": "net_dependable", "heat_rate_basis": "hhv"}


@pytest.fixture
def mapping_path() -> Path:
    return HERE / "fixture_mapping.yaml"
