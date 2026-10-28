import pandas as pd
import pytest

from conftest import make_pv
from perf_common import DecisionRequired
from solar_core import IrradianceBasisError
from solar_perf import build_confirmed_solar, preview_solar

KW = dict(dc_kwp=1000.0, ac_capacity_kw=750.0, gamma_pmax_per_c=-0.004)
DEC = dict(timestamp_convention="interval_ending", pr_method="temperature_corrected_stc",
           clipping_handling="exclude_intervals", availability_in_pr="include_downtime")


@pytest.fixture(scope="module")
def short_pv():
    return make_pv(days=60, rd_pct=0.0, start="2024-06-01")


def test_missing_decision(short_pv):
    with pytest.raises(DecisionRequired, match="pr_method"):
        build_confirmed_solar(short_pv, **KW, **{**DEC, "pr_method": None})


def test_ghi_only_is_rejected(short_pv):
    ghi = short_pv.rename(columns={"poa_wm2": "ghi_wm2"})
    with pytest.raises(IrradianceBasisError, match="transpose"):
        build_confirmed_solar(ghi, **KW, **DEC)


def test_temperature_corrected_pr_recovers_planted(short_pv):
    out = build_confirmed_solar(short_pv, **KW, **DEC)
    assert out["pr"] == pytest.approx(0.82, abs=0.005)


def test_uncorrected_pr_differs_from_corrected(short_pv):
    unc = build_confirmed_solar(short_pv, **KW, **{**DEC, "pr_method": "iec_61724_uncorrected"})["pr"]
    assert abs(unc - 0.82) > 0.01


def test_nrel_weather_corrected_close_to_uncorrected_average(short_pv):
    nrel = build_confirmed_solar(short_pv, **KW, **{**DEC, "pr_method": "nrel_weather_corrected"})["pr"]
    unc = build_confirmed_solar(short_pv, **KW, **{**DEC, "pr_method": "iec_61724_uncorrected"})["pr"]
    assert nrel == pytest.approx(unc, abs=0.01)


def test_curtailment_always_excluded(short_pv):
    base = build_confirmed_solar(short_pv, **KW, **DEC)
    curt = short_pv.copy()
    day = curt.timestamp.dt.date == curt.timestamp.dt.date.iloc[96 * 10]
    curt.loc[day, "setpoint_kw"] = 200.0
    curt.loc[day, "ac_power_kw"] = curt.loc[day, "ac_power_kw"].clip(upper=200.0)
    out = build_confirmed_solar(curt, **KW, **DEC)
    assert out["pr"] == pytest.approx(base["pr"], abs=0.002)
    assert out["lost_energy"]["lost_curtailment_kwh"] > 0


def test_clipping_choice_matters(short_pv):
    exc = build_confirmed_solar(short_pv, **KW, **DEC)
    inc = build_confirmed_solar(short_pv, **KW, **{**DEC, "clipping_handling": "include"})
    assert exc["flag_shares_daylight"]["flag_clipped"] > 0
    assert inc["pr"] < exc["pr"]
    assert exc["lost_energy"]["lost_clipping_kwh"] > 0


def test_inverter_fault_availability(short_pv):
    pv = short_pv.copy()
    idx = pv.index[pv.poa_wm2 >= 50][:200]
    pv.loc[idx, "inverter_status"] = "fault"
    pv.loc[idx, "ac_power_kw"] = 0.0
    out = build_confirmed_solar(pv, **KW, **DEC)
    n_day = int((pv.poa_wm2 >= 50).sum())
    assert out["inverter_availability"].availability.iloc[0] == pytest.approx(1 - 200 / n_day, abs=1e-6)
    excl = build_confirmed_solar(pv, **KW, **{**DEC, "availability_in_pr": "exclude_downtime"})
    assert excl["pr"] > out["pr"]


def test_implausible_gamma(short_pv):
    with pytest.raises(ValueError, match="implausible"):
        build_confirmed_solar(short_pv, **{**KW, "gamma_pmax_per_c": -0.4}, **DEC)


def test_degradation_recovers_planted_rate(pv):
    out = build_confirmed_solar(pv, **KW, **DEC)
    rd = out["degradation"]
    assert rd["rd_pct_per_year"] == pytest.approx(-0.8, abs=0.2)
    assert rd["ci_68_low"] <= rd["rd_pct_per_year"] <= rd["ci_68_high"]


def test_short_series_skips_degradation(short_pv):
    out = build_confirmed_solar(short_pv, **KW, **DEC)
    assert isinstance(out["degradation"], str) and out["degradation"].startswith("skipped")


def test_preview_grid(short_pv):
    p = preview_solar(short_pv, **KW)
    assert len(p["pr_grid"]) == 12 and "nothing built" in p["readout"]
    p2 = preview_solar(short_pv, dc_kwp=1000.0, ac_capacity_kw=750.0)
    assert p2["pr_grid"]["nrel_weather_corrected"] == "needs gamma_pmax_per_c"
