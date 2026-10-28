"""Offline tests for unit-guard conversions, decisions, and conventions."""

import math

import pytest

from units_core import (
    AmbiguousUnit,
    DecisionRequired,
    DimensionError,
    Quantity,
    UnknownUnit,
    add,
    boe_from_gas,
    convert,
    convert_heating_value_basis,
    efficiency_to_heat_rate,
    gas_volume_to_energy,
    heat_rate_to_efficiency,
    power_to_energy,
    required_decisions,
    to_co2e,
)

SCF = {"scf_standard_conditions": "60F_14.696psia"}


def test_exact_liquid_factors():
    assert convert(1, "bbl", "m3") == pytest.approx(0.158987294928, rel=1e-12)
    assert convert(1, "bbl", "gal") == pytest.approx(42.0, rel=1e-12)
    assert convert(1, "MMbbl", "Mbbl") == pytest.approx(1000.0)


def test_oil_gas_m_means_thousand():
    assert convert(1, "Mcf", "scf") == pytest.approx(1000.0)
    assert convert(1, "MMcf", "Mcf") == pytest.approx(1000.0)
    assert convert(1, "MMBtu", "Btu") == pytest.approx(1e6)


def test_si_msm3_means_million():
    assert convert(1, "MSm3", "Sm3") == pytest.approx(1e6)


def test_scf_to_sm3_requires_decision():
    with pytest.raises(DecisionRequired) as exc:
        convert(1, "scf", "Sm3")
    assert exc.value.decision == "scf_standard_conditions"
    assert required_decisions("Mcf", "Sm3") == ["scf_standard_conditions"]
    assert required_decisions("Mcf", "MMcf") == []


def test_scf_to_sm3_temperature_corrected():
    # 60 F (288.71 K) -> 15 C (288.15 K) at the same pressure: 0.0283168 * 288.15/288.7056
    assert convert(1, "scf", "Sm3", SCF) == pytest.approx(0.0282623, rel=1e-5)
    assert convert(1, "Sm3", "scf", SCF) == pytest.approx(35.3830, rel=1e-4)


def test_scf_basis_changes_answer():
    a = convert(1e6, "scf", "Sm3", {"scf_standard_conditions": "60F_14.696psia"})
    b = convert(1e6, "scf", "Sm3", {"scf_standard_conditions": "60F_14.73psia"})
    assert b / a == pytest.approx(14.73 / 14.696, rel=1e-5)  # 14.696 psia ~= 101.325 kPa


def test_rate_compound_and_shorthand():
    assert convert(1, "MMcfd", "Mcf/d") == pytest.approx(1000.0)
    assert convert(24, "bbl/d", "bbl/h") == pytest.approx(1.0)
    assert convert(1, "MMcf/d", "MSm3/d", SCF) == pytest.approx(0.0282623, rel=1e-5)


def test_energy_factors():
    assert convert(1, "MWh", "MMBtu") == pytest.approx(3.412141633, rel=1e-9)
    assert convert(1, "therm", "MMBtu") == pytest.approx(0.1)
    assert convert(1, "Dth", "MMBtu") == pytest.approx(1.0)
    assert convert(1, "MMBtu", "GJ") == pytest.approx(1.05505585262, rel=1e-12)


def test_energy_per_time_is_power():
    assert convert(1, "MWh/h", "MW") == pytest.approx(1.0)
    assert convert(1, "MMBtu/h", "kW") == pytest.approx(293.07107, rel=1e-6)


def test_power_is_not_energy():
    with pytest.raises(DimensionError, match="power_to_energy"):
        convert(1, "MW", "MWh")
    with pytest.raises(DimensionError):
        add(Quantity(5, "MW"), Quantity(5, "MWh"))


def test_capacity_month_is_not_energy():
    with pytest.raises(DimensionError, match="Capacity"):
        convert(1, "MW-month", "MWh")


def test_power_to_energy_dst_hours():
    assert power_to_energy(100, "MW", 25) == pytest.approx(2500.0)
    assert power_to_energy(100, "MW", 23) == pytest.approx(2300.0)
    with pytest.raises(DimensionError):
        power_to_energy(100, "MWh", 24)


@pytest.mark.parametrize("symbol", ["MBtu", "MT", "ton", "tons", "psi", "bar", "cf", "yr", "Mlb"])
def test_ambiguous_symbols_refused(symbol):
    with pytest.raises(AmbiguousUnit):
        convert(1, symbol, "kg") if symbol in ("MT", "ton", "tons", "Mlb") else convert(1, symbol, "J")


def test_unknown_unit():
    with pytest.raises(UnknownUnit):
        convert(1, "furlong", "m3")


def test_mass_tons():
    assert convert(1, "short_ton", "kg") == pytest.approx(907.18474)
    assert convert(1, "long_ton", "kg") == pytest.approx(1016.0469088)
    assert convert(1, "Mt", "t") == pytest.approx(1e6)
    assert convert(1, "MMTCO2e", "tCO2e") == pytest.approx(1e6)


def test_temperature_affine():
    assert convert(60, "degF", "degC") == pytest.approx(15.5555556)
    assert convert(0, "degC", "K") == pytest.approx(273.15)
    assert convert(-40, "degF", "degC") == pytest.approx(-40.0)
    with pytest.raises(DimensionError):
        add(Quantity(20, "degC"), Quantity(5, "degC"))


def test_gauge_absolute_requires_atmosphere():
    with pytest.raises(DecisionRequired):
        convert(100, "psig", "psia")
    assert convert(100, "psig", "psia", {"atmospheric_pressure_psia": 14.696}) == pytest.approx(114.696)
    assert convert(114.696, "psia", "psig", {"atmospheric_pressure_psia": 14.696}) == pytest.approx(100.0)
    assert convert(1, "bara", "kPa") == pytest.approx(100.0)


def test_boe_methods():
    assert boe_from_gas(600, "Mcf", method="energy_6_to_1") == pytest.approx(100.0)
    hv = boe_from_gas(600, "Mcf", method="heating_value", gas_hhv_btu_per_scf=1036, oil_mmbtu_per_bbl=5.8)
    assert hv == pytest.approx(600 * 1.036 / 5.8)
    price = boe_from_gas(600, "Mcf", method="price_parity", gas_price_per_mcf=3.0, oil_price_per_bbl=75.0)
    assert price == pytest.approx(24.0)
    with pytest.raises(DecisionRequired):
        boe_from_gas(600, "Mcf", method="whatever")
    with pytest.raises(DecisionRequired):
        boe_from_gas(600, "Mcf", method="heating_value")
    with pytest.raises(DecisionRequired):
        boe_from_gas(1000, "Sm3", method="energy_6_to_1")


def test_co2e_gwp_sets():
    assert to_co2e(1, "t", "CH4", "AR4_100") == pytest.approx(25)
    assert to_co2e(1, "t", "CH4", "AR5_100") == pytest.approx(28)
    assert to_co2e(1, "t", "CH4", "AR6_100", ch4_origin="fossil") == pytest.approx(29.8)
    assert to_co2e(2000, "lb", "N2O", "AR5_100") == pytest.approx(0.90718474 * 265)
    with pytest.raises(DecisionRequired):
        to_co2e(1, "t", "CH4", "AR6_100")
    with pytest.raises(DecisionRequired):
        to_co2e(1, "t", "CH4", "latest")


def test_heat_rate_efficiency_roundtrip():
    assert heat_rate_to_efficiency(6824.28, "Btu/kWh", "HHV") == pytest.approx(0.5, rel=1e-5)
    assert heat_rate_to_efficiency(7200, "kJ/kWh", "LHV") == pytest.approx(0.5)
    hr = efficiency_to_heat_rate(0.45, "Btu/kWh", "HHV")
    assert heat_rate_to_efficiency(hr, "Btu/kWh", "HHV") == pytest.approx(0.45)
    with pytest.raises(DecisionRequired):
        heat_rate_to_efficiency(7000, "Btu/kWh", "gross")


def test_hhv_lhv():
    assert convert_heating_value_basis(100.0, "HHV", "LHV", 0.9) == pytest.approx(90.0)
    assert convert_heating_value_basis(90.0, "LHV", "HHV", 0.9) == pytest.approx(100.0)
    with pytest.raises(ValueError):
        convert_heating_value_basis(1, "HHV", "LHV", 0.5)


def test_gas_volume_to_energy():
    mmbtu = gas_volume_to_energy(1, "Mcf", 1036, "HHV", "MMBtu")
    assert mmbtu == pytest.approx(1.036)
    with pytest.raises(ValueError, match="heating value"):
        gas_volume_to_energy(1, "Mcf", 38.3, "HHV", "MMBtu")


def test_roundtrip_property():
    for a, b in [("bbl", "m3"), ("MWh", "GJ"), ("lb", "t"), ("Mcf/d", "MMcf/d"), ("kW", "hp")]:
        assert convert(convert(123.456, a, b), b, a) == pytest.approx(123.456, rel=1e-12)
    assert math.isclose(convert(convert(5, "scf", "Nm3", SCF), "Nm3", "scf", SCF), 5, rel_tol=1e-12)
