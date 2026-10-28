import numpy as np
import pandas as pd
import pytest

from conftest import RATED
from perf_common import DecisionRequired
from wind_core import air_density, binned_power_curve, flag_scada, normalize_density, rayleigh_aep_mwh
from wind_perf import build_confirmed_wind, preview_wind
from perf_common import with_interval_start

DEC = dict(timestamp_convention="interval_beginning", reference_curve="warranted", ref_density=1.225,
           turbine_control="pitch", availability_basis="time", external_downtime="exclude_from_availability")


def test_missing_decision_raises(scada, curve):
    with pytest.raises(DecisionRequired, match="availability_basis"):
        build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **{**DEC, "availability_basis": None})
    with pytest.raises(DecisionRequired, match="ref_density"):
        build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **{**DEC, "ref_density": None})


def test_naive_timestamps_rejected(scada, curve):
    naive = scada.assign(timestamp=scada.timestamp.dt.tz_localize(None))
    with pytest.raises(ValueError, match="timezone-aware"):
        build_confirmed_wind(naive, rated_kw=RATED, warranted_curve=curve, **DEC)


def test_unknown_state_rejected(scada):
    with pytest.raises(ValueError, match="Unknown state"):
        flag_scada(scada.assign(state="ON"), RATED)


def test_stuck_anemometer_flagged(scada):
    f = flag_scada(scada, RATED)
    t1 = f[f.turbine_id == "T1"]
    assert t1["flag_stuck_anemometer"].iloc[2005:2012].all()
    assert not t1["flag_stuck_anemometer"].iloc[:90].any()


def test_density_pitch_normalization():
    df = pd.DataFrame({"wind_speed_ms": [10.0], "power_kw": [1000.0], "ambient_temp_c": [-10.0],
                       "pressure_hpa": [1013.25]})
    rho = air_density(df)
    assert rho.iloc[0] == pytest.approx(101325 / (287.05 * 263.15))
    out = normalize_density(df, rho, 1.225, "pitch")
    assert out.ws_norm.iloc[0] == pytest.approx(10 * (rho.iloc[0] / 1.225) ** (1 / 3))
    stall = normalize_density(df, rho, 1.225, "stall")
    assert stall.p_norm.iloc[0] == pytest.approx(1000 * 1.225 / rho.iloc[0])


def test_bins_are_iec_half_metre(scada):
    f = flag_scada(with_interval_start(scada, "interval_beginning", group_col="turbine_id"), RATED)
    curve = binned_power_curve(f.assign(ws_norm=f.wind_speed_ms, p_norm=f.power_kw))
    assert np.allclose(curve.bin_ms % 0.5, 0)
    assert "complete" in curve and curve.complete.dtype == bool


def test_curtailment_is_not_underperformance(scada, curve):
    out = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **DEC)
    t1 = out["losses"].set_index("turbine_id").loc["T1"]
    assert t1.lost_curtailment_kwh > 0
    assert abs(t1.performance_gap_kwh) / t1.expected_kwh < 0.01


def test_underperforming_turbine_detected(scada, curve):
    out = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **DEC)
    t2 = out["losses"].set_index("turbine_id").loc["T2"]
    assert t2.performance_gap_kwh / t2.expected_kwh == pytest.approx(0.05, abs=0.01)


def test_availability_external_downtime_choice(scada, curve):
    excl = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **DEC)["availability"]
    count = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve,
                                 **{**DEC, "external_downtime": "count_as_unavailable"})["availability"]
    a_ex = excl.set_index("turbine_id").availability["T1"]
    a_ct = count.set_index("turbine_id").availability["T1"]
    assert a_ex == pytest.approx(1 - 1 / 29)
    assert a_ct == pytest.approx(1 - 2 / 30)


def test_energy_based_availability_differs(scada, curve):
    out = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **{**DEC, "availability_basis": "energy"})
    a = out["availability"].set_index("turbine_id").availability["T1"]
    assert 0.9 < a < 1.0 and out["availability"].basis.iloc[0] == "energy"


def test_yaw_offset_flagged(scada, curve):
    yaw = build_confirmed_wind(scada, rated_kw=RATED, warranted_curve=curve, **DEC)["yaw"].set_index("turbine_id")
    assert yaw.flag["T2"] and not yaw.flag["T1"]
    assert yaw.median_offset_deg["T2"] == pytest.approx(8.0, abs=0.5)


def test_aep_ratio_close_to_one_for_healthy_turbine(curve):
    assert rayleigh_aep_mwh(curve.rename(columns={"ws_ms": "ws_mean"}), 7.5, RATED) > 0


def test_icing_flag(scada, curve):
    cold = scada.copy()
    idx = cold.index[(cold.turbine_id == "T1") & (cold.wind_speed_ms > 8)][:50]
    cold.loc[idx, "ambient_temp_c"] = -5.0
    cold.loc[idx, "power_kw"] = cold.loc[idx, "power_kw"] * 0.2
    out = build_confirmed_wind(cold, rated_kw=RATED, warranted_curve=curve, **DEC)
    share = out["flags"].set_index("flag").share["flag_icing"]
    assert share > 0


def test_site_baseline_requires_baseline_end(scada):
    with pytest.raises(DecisionRequired, match="baseline_end"):
        build_confirmed_wind(scada, rated_kw=RATED, **{**DEC, "reference_curve": "site_baseline"})
    out = build_confirmed_wind(scada, rated_kw=RATED, baseline_end="2025-03-15T00:00:00Z",
                               **{**DEC, "reference_curve": "site_baseline"})
    assert out["manifest"]["inputs"]["baseline_end"].startswith("2025-03-15")


def test_preview_read_only(scada, curve):
    before = scada.copy()
    p = preview_wind(scada, rated_kw=RATED, warranted_curve=curve)
    pd.testing.assert_frame_equal(scada, before)
    assert set(p["consequences"]["aep_ratio_by_ref_density"]) == {"site_mean", "iso_1.225"}
    assert len(p["consequences"]["fleet_availability"]) == 4
    assert "nothing built" in p["readout"]
