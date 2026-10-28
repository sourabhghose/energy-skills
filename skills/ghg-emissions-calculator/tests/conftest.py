"""Shared fixtures: synthetic activity data with hand-checkable values."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

SETS = ["epa_hub_2025", "egrid_2023", "greene_rm_2025", "subpart_w_legacy"]


@pytest.fixture
def activity() -> pd.DataFrame:
    base = {"period": "2025", "operational_control": True, "equity_share": 1.0}
    rows = [
        {"facility_id": "F1", "source_type": "stationary_combustion", "fuel_or_product": "natural_gas",
         "quantity": 1000.0, "unit": "Mcf"},
        {"facility_id": "F1", "source_type": "flare", "fuel_or_product": "flare_gas", "quantity": 1.0,
         "unit": "MMscf", "ch4_mol_frac": 0.8, "co2_mol_frac": 0.02, "c2plus_mol_frac": 0.15,
         "c2plus_carbon_number": 2.5},
        {"facility_id": "F1", "source_type": "pneumatic_device", "fuel_or_product": "high_bleed",
         "quantity": 0.0, "unit": "scf", "device_count": 10, "operating_hours": 8760, "ch4_mol_frac": 0.8,
         "co2_mol_frac": 0.02},
        {"facility_id": "F2", "source_type": "purchased_electricity", "fuel_or_product": "electricity",
         "quantity": 1_000_000.0, "unit": "kWh", "egrid_subregion": "ERCT", "rec_mwh": 400.0,
         "equity_share": 0.5, "operational_control": False},
        {"facility_id": "F2", "source_type": "vented_other", "fuel_or_product": "compressor_vent",
         "quantity": 0.0, "unit": "scf", "measured_ch4_kg": 2000.0, "site_level_reconciled": True,
         "equity_share": 0.5, "operational_control": False},
    ]
    return pd.DataFrame([{**base, **r} for r in rows])


@pytest.fixture
def decisions() -> dict:
    return dict(gwp_set="AR5", factor_sets=SETS, consolidation="operational_control",
                flare_efficiency_tier="tier2_de95", tank_method=None, market_fallback="raise",
                scope2_headline="market", cat11_basis=None, boe_mcf_per_boe=None)
