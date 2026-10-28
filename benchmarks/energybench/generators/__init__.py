"""Planted-truth data generators for EnergyBench tier-P tasks.

REGISTRY maps a task's `generator` field (task.toml) to a function `(out_dir, seed) -> answer_key`. Generators are
stdlib-only and deterministic for a given seed. Bump GENERATOR_VERSION whenever any generator's output changes, so
grades made on old data are never compared with grades on new data.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import accounting, controls, markets, oilgas, power, renewables, subsurface

GENERATOR_VERSION = "1.0.0"

REGISTRY: dict[str, Callable[[Path, int], dict]] = {
    "power.p01_ami_dst": power.p01_ami_dst,
    "power.p02_ami_rollover": power.p02_ami_rollover,
    "power.p03_reliability_med": power.p03_reliability_med,
    "power.p04_reliability_caidi": power.p04_reliability_caidi,
    "power.p05_load_leakage": power.p05_load_leakage,
    "power.p06_ceii_share": power.p06_ceii_share,
    "power.p07_wildfire_miles": power.p07_wildfire_miles,
    "markets.p08_iso_interval_ending": markets.p08_iso_interval_ending,
    "markets.p09_iso_settlement": markets.p09_iso_settlement,
    "oilgas.p10_dca_eur": oilgas.p10_dca_eur,
    "oilgas.p11_boe": oilgas.p11_boe,
    "subsurface.p12_las_netpay": subsurface.p12_las_netpay,
    "subsurface.p13_density_porosity": subsurface.p13_density_porosity,
    "subsurface.p14_drilling_npt": subsurface.p14_drilling_npt,
    "oilgas.p15_well_identity": oilgas.p15_well_identity,
    "oilgas.p16_esp_failures": oilgas.p16_esp_failures,
    "renewables.p17_wind_curtailment": renewables.p17_wind_curtailment,
    "renewables.p18_solar_pr": renewables.p18_solar_pr,
    "renewables.p19_capacity_factor": renewables.p19_capacity_factor,
    "accounting.p20_scope2": accounting.p20_scope2,
    "accounting.p21_scope1": accounting.p21_scope1,
    "accounting.p22_methane": accounting.p22_methane,
    "accounting.p23_heat_rate": accounting.p23_heat_rate,
    "accounting.p24_gas_units": accounting.p24_gas_units,
    "controls.c01_fuel_mix": controls.c01_fuel_mix,
    "controls.c02_price_plot": controls.c02_price_plot,
    "controls.c03_ev_chargers": controls.c03_ev_chargers,
    "controls.c04_tariff_bill": controls.c04_tariff_bill,
    "controls.c05_press_mentions": controls.c05_press_mentions,
    "controls.c06_gasoline_yoy": controls.c06_gasoline_yoy,
    "controls.c07_trir": controls.c07_trir,
    "controls.c08_refinery_dedupe": controls.c08_refinery_dedupe,
}
