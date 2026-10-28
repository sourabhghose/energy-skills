import pandas as pd
import pytest

from ghg_core import load_factors
from ghg_sources import compute_emissions, flare
from conftest import SETS

FACTORS = load_factors(SETS)
D = {"flare_efficiency_tier": "tier2_de95", "tank_method": "flash_factor", "market_fallback": "raise"}


def _mass(records, source_type, gas, method_prefix=""):
    sel = records[(records.source_type == source_type) & (records.gas == gas)
                  & records.method.str.startswith(method_prefix)]
    return sel["mass_t"].sum()


def test_natural_gas_combustion_hand_calc(activity):
    rec, issues = compute_emissions(activity, FACTORS, D)
    assert issues.empty
    assert _mass(rec, "stationary_combustion", "CO2") == pytest.approx(1026 * 53.06 / 1000)
    assert _mass(rec, "stationary_combustion", "CH4") == pytest.approx(1026 * 1.0 / 1e6)


def test_flare_tier2_hand_calc(activity):
    rec, _ = compute_emissions(activity, FACTORS, D)
    assert _mass(rec, "flare", "CH4") == pytest.approx(1e6 * 0.8 * 0.05 * 0.0192 / 1000)
    co2_scf = 1e6 * (0.02 + 0.935 * (0.8 + 0.15 * 2.5))
    assert _mass(rec, "flare", "CO2") == pytest.approx(co2_scf * 0.0526 / 1000)


def test_flare_tier_changes_methane_materially(activity):
    row = activity[activity.source_type == "flare"].iloc[0].to_dict()
    t1 = flare(row, FACTORS, {"flare_efficiency_tier": "tier1_de98"})[0]["mass_t"]
    t3 = flare(row, FACTORS, {"flare_efficiency_tier": "tier3_de92"})[0]["mass_t"]
    assert t3 / t1 == pytest.approx(4.0)


def test_pneumatic_high_bleed(activity):
    rec, _ = compute_emissions(activity, FACTORS, D)
    assert _mass(rec, "pneumatic_device", "CH4") == pytest.approx(10 * 8760 * 37.3 * 0.8 * 0.0192 / 1000)


def test_scope2_dual_reporting(activity):
    rec, _ = compute_emissions(activity, FACTORS, D)
    loc = rec[(rec.scope2_method == "location")]["mass_t"].sum()
    mkt = rec[(rec.scope2_method == "market")]["mass_t"].sum()
    lb = 0.45359237 / 1000
    assert loc == pytest.approx(1000 * 733.9 * lb)
    assert mkt == pytest.approx(600 * 823.81 * lb)


def test_market_fallback_raise_vs_flag(activity):
    row = activity[activity.source_type == "purchased_electricity"].assign(egrid_subregion="US")
    _, issues = compute_emissions(row, FACTORS, D)
    assert len(issues) == 1 and "purchased_electricity_residual" in issues.issue.iloc[0]
    rec, issues = compute_emissions(row, FACTORS, {**D, "market_fallback": "location_fallback_flagged"})
    assert issues.empty and rec.note.str.contains("FLAG").any()


def test_measured_site_reconciled_is_ogmp_level5(activity):
    rec, _ = compute_emissions(activity, FACTORS, D)
    vent = rec[(rec.source_type == "vented_other") & (rec.gas == "CH4")]
    assert vent.ogmp_level.iloc[0] == 5 and vent.mass_t.iloc[0] == pytest.approx(2.0)


def test_component_ef_without_source_is_rejected():
    row = pd.DataFrame([{"facility_id": "F", "source_type": "fugitive_component", "fuel_or_product": "valve",
                         "quantity": 0, "unit": "scf", "component_count": 100, "operating_hours": 8760,
                         "ef_scf_per_hour": 0.1, "ch4_mol_frac": 0.8}])
    _, issues = compute_emissions(row, FACTORS, D)
    assert "ef_source" in issues.issue.iloc[0]


def test_tank_flash_factor_needs_source():
    row = pd.DataFrame([{"facility_id": "F", "source_type": "tank_vent", "fuel_or_product": "oil",
                         "quantity": 10000, "unit": "bbl", "flash_gor_scf_per_bbl": 30.0,
                         "ch4_mol_frac": 0.4}])
    _, issues = compute_emissions(row, FACTORS, D)
    assert "flash_gor_source" in issues.issue.iloc[0]
    rec, issues = compute_emissions(row.assign(flash_gor_source="lab_2025_03"), FACTORS, D)
    assert rec[rec.gas == "CH4"].mass_t.iloc[0] == pytest.approx(10000 * 30 * 0.4 * 0.0192 / 1000)


def test_mobile_combustion_flags_missing_ch4_n2o():
    row = pd.DataFrame([{"facility_id": "F", "source_type": "mobile_combustion", "fuel_or_product": "diesel",
                         "quantity": 1000, "unit": "gallons"}])
    rec, _ = compute_emissions(row, FACTORS, D)
    assert rec.mass_t.iloc[0] == pytest.approx(10.21) and "not estimated" in rec.note.iloc[0]


def test_unknown_unit_reported_not_dropped():
    row = pd.DataFrame([{"facility_id": "F", "source_type": "stationary_combustion",
                         "fuel_or_product": "natural_gas", "quantity": 5, "unit": "m3"}])
    rec, issues = compute_emissions(row, FACTORS, D)
    assert rec.empty and "Ambiguous unit" in issues.issue.iloc[0]


def test_inputs_not_mutated(activity):
    before = activity.copy()
    compute_emissions(activity, FACTORS, D)
    pd.testing.assert_frame_equal(activity, before)
