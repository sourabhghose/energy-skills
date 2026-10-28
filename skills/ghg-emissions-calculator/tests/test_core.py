import pandas as pd
import pytest

from ghg_core import (DecisionRequired, FactorProvenanceError, UnitError, gwp, load_factors, lookup_factor,
                      normalize_unit, require, to_mmbtu, to_mwh)
from uc_io import IdentifierError, validate_identifier


def test_gwp_sets_published_values():
    assert gwp("CH4", "AR4") == 25 and gwp("CH4", "AR5") == 28 and gwp("CH4", "AR6") == 29.8
    assert gwp("N2O", "AR5") == 265


def test_unknown_gwp_set_is_a_decision():
    with pytest.raises(DecisionRequired):
        gwp("CH4", "AR3")


def test_require_allows_none_only_when_not_applicable():
    assert require("x", None, ["a"], applicable=False) == "not_applicable"
    with pytest.raises(DecisionRequired):
        require("x", None, ["a"], applicable=True)


@pytest.mark.parametrize("unit", ["m3", "ton", "btu"])
def test_ambiguous_units_raise(unit):
    with pytest.raises(UnitError):
        normalize_unit(unit)


def test_gas_volume_to_mmbtu_uses_hhv_with_lineage():
    factors = load_factors(["epa_hub_2025"])
    mmbtu, hhv = to_mmbtu(1000, "Mcf", factors, "natural_gas")
    assert mmbtu == pytest.approx(1026.0)
    assert hhv.factor_id == "hub25_ng_hhv" and hhv.vintage == "2025"


def test_energy_units_need_no_hhv():
    mmbtu, hhv = to_mmbtu(10, "therm", load_factors(["epa_hub_2025"]), "natural_gas")
    assert mmbtu == pytest.approx(1.0) and hhv is None


def test_electricity_unit_guard():
    assert to_mwh(2500, "kWh") == pytest.approx(2.5)
    with pytest.raises(UnitError):
        to_mwh(10, "mmBtu")


def test_factor_sets_are_a_decision():
    with pytest.raises(DecisionRequired):
        load_factors([])
    with pytest.raises(FactorProvenanceError):
        load_factors(["made_up_2030"])


def test_missing_factor_raises():
    with pytest.raises(FactorProvenanceError):
        lookup_factor(load_factors(["egrid_2023"]), "purchased_electricity_location", "XXXX", "CO2")


def test_ambiguous_factor_across_sets(tmp_path):
    table = pd.read_csv(load_factors.__defaults__[0])
    dup = table[table.factor_id == "hub25_ng_co2"].assign(factor_set="other_2024", factor_id="x")
    path = tmp_path / "f.csv"
    pd.concat([table, dup]).to_csv(path, index=False)
    factors = load_factors(["epa_hub_2025", "other_2024"], path)
    with pytest.raises(FactorProvenanceError, match="Ambiguous"):
        lookup_factor(factors, "stationary_combustion", "natural_gas", "CO2")


def test_every_factor_has_source_vintage_and_url():
    table = pd.read_csv(load_factors.__defaults__[0])
    assert table[["source", "vintage", "url", "status"]].notna().all().all()
    assert set(table.status) <= {"verified", "verify_before_use"}


@pytest.mark.parametrize("bad", ["a;b", "a.b.c.d", "x y", "`x`"])
def test_identifier_validation(bad):
    with pytest.raises(IdentifierError):
        validate_identifier(bad)


def test_identifier_quoting():
    assert validate_identifier("main.esg.t1") == "`main`.`esg`.`t1`"
