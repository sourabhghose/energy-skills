from datetime import date

import numpy as np
import pandas as pd
import pytest

import synth
from lf_decisions import DecisionRequired, make_config
from lf_features import build_features, holidays, lag_hours, to_hour_start_utc
from lf_models import metrics, origins, rolling_origin_backtest
from lf_normalize import daily_frame, normal_degree_days, weather_normalized_energy
from lf_pipeline import preview_profile, run_forecast
from lf_run import build_confirmed_forecast, format_build
from lf_weather import fill_short_gaps, fit_balance_points, infer_temperature_unit

BASE = dict(local_timezone=synth.TZ, load_timestamp_basis="utc",
            load_interval_convention="beginning", load_unit="MW", weather_station="KGOOD",
            temperature_unit="F", hdd_base=60, cdd_base=70, holiday_calendar="nerc",
            horizon_hours=24, model_family="degree_day_regression", normal_years=(2020, 2023))


@pytest.fixture(scope="module")
def data():
    wx = synth.weather()
    return wx, synth.load(wx)


def cfg(**over):
    return make_config(**{**BASE, **over})


def test_every_decision_is_required():
    for name in BASE:
        with pytest.raises(DecisionRequired, match=name):
            make_config(**{**BASE, name: None})
    with pytest.raises(DecisionRequired, match="cdd_base"):
        cfg(hdd_base=70, cdd_base=60)


def test_build_refuses_before_reading_data():
    with pytest.raises(DecisionRequired):
        build_confirmed_forecast("a.b.load", "a.b.wx", "a.b.out")


def test_nerc_and_federal_holidays():
    nerc = holidays("nerc", range(2022, 2025))
    assert date(2024, 11, 28) in nerc                 # Thanksgiving
    assert date(2022, 12, 26) in nerc                 # Christmas on Sunday → Monday
    assert date(2022, 12, 23) not in nerc             # NERC does not move Saturday holidays
    fed = holidays("us_federal", range(2021, 2022))
    assert date(2021, 12, 24) in fed                  # Saturday Christmas observed Friday
    assert date(2021, 6, 18) in fed                   # Juneteenth 2021 (Saturday) observed Fri
    assert len(holidays("us_federal", range(2023, 2024))) == 11


def test_hour_ending_local_naive_across_fall_back():
    utc = pd.date_range("2024-11-03 04:00", periods=6, freq="h", tz="UTC")
    labels = (utc + pd.Timedelta(hours=1)).tz_convert(synth.TZ).tz_localize(None)
    out = to_hour_start_utc(pd.Series(labels), "local_naive", "ending", synth.TZ)
    assert (out.to_numpy() == utc.to_numpy()).all()


def test_lags_never_shorter_than_horizon(data):
    for h in (1, 24, 36, 168, 200):
        assert min(lag_hours(h)) >= h
    wx, load = data
    frame = load.merge(wx[wx.station_id == "KGOOD"][["hour_start_utc", "temp"]], on="hour_start_utc")
    feats = build_features(frame, cfg(horizon_hours=36), set())
    assert {"load_lag_48", "load_lag_168"} <= set(feats.columns)
    assert "load_lag_24" not in feats.columns


def test_backtest_trains_strictly_before_each_origin(data):
    wx, load = data
    res = run_forecast(load, wx, cfg())
    bt = res["backtest"]
    assert bt["origin_utc"].nunique() == 6
    for o, g in bt.groupby("origin_utc"):
        assert g["hour_start_utc"].min() == o and len(g) == 24


def test_model_beats_naive_and_reports_peak_metrics(data):
    wx, load = data
    res = run_forecast(load, wx, cfg())
    assert res["skill_vs_naive"] > 0.2
    assert res["metrics_model"]["wape_pct"] < 5
    assert {"daily_peak_ape_pct", "daily_peak_timing_mae_hours"} <= set(res["metrics_model"])
    assert len(res["forecast"]) == 24  # weather extends past the last load hour


def test_balance_point_search_recovers_planted_bases(data):
    wx, load = data
    prof = preview_profile(load, wx, synth.TZ)
    best = prof["fitted_balance_points_top5"][0]
    assert abs(best["hdd_base"] - synth.HEAT_BASE_F) <= 2
    assert abs(best["cdd_base"] - synth.COOL_BASE_F) <= 2
    assert prof["station_ranking"][-1]["station_id"] == "KGAPPY"
    assert prof["temperature_unit_check"]["guess"] == "F"


def test_weather_normalization_is_zero_in_normal_weather_and_signed_otherwise(data):
    wx, load = data
    good = wx[wx.station_id == "KGOOD"]
    frame = load.merge(good[["hour_start_utc", "temp"]], on="hour_start_utc")
    daily = daily_frame(frame, synth.TZ, set())
    year = daily[pd.to_datetime(daily.index).year == 2022]
    same = normal_degree_days(good, synth.TZ, (2022, 2022), 60, 70)
    res = weather_normalized_energy(year, same, 60, 70)
    assert res["fit_r2"] > 0.95
    assert abs(res["weather_adjustment_mwh"]) < 1e-6 * res["actual_mwh"]
    hotter = same.assign(cdd=same["cdd"] * 1.5)
    assert weather_normalized_energy(year, hotter, 60, 70)["weather_adjustment_mwh"] > 0


def test_normal_degree_days_average_dd_not_dd_of_average():
    hours = pd.date_range("2020-01-01", "2022-01-01", freq="h", tz="UTC", inclusive="left")
    temp = np.where(hours.year == 2020, 50.0, 70.0)
    wx = pd.DataFrame({"hour_start_utc": hours, "temp": temp})
    n = normal_degree_days(wx, "UTC", (2020, 2021), 65, 65)
    assert n.loc["06-15", "hdd"] == pytest.approx(7.5)   # mean(15, 0), not max(65-60, 0)=5


def test_fill_short_gaps_only():
    hours = pd.date_range("2024-01-01", periods=20, freq="h", tz="UTC")
    w = pd.DataFrame({"hour_start_utc": hours, "temp": np.arange(20.0)}).drop(index=[3, 4, 10, 11, 12, 13, 14])
    out = fill_short_gaps(w, 3)
    assert out["temp"].isna().sum() == 5 and out["temp_filled"].sum() == 2


def test_unit_inference_and_metrics():
    assert infer_temperature_unit(pd.Series([-5.0, 10, 30, 35]))["guess"] == "C"
    a = pd.Series([100.0, 200, 100, 200])
    f = pd.Series([110.0, 190, 100, 220])
    m = metrics(a, f, pd.Series([1, 1, 2, 2]), pd.Series([0, 1, 0, 1]))
    assert m["wape_pct"] == pytest.approx(100 * 40 / 600)
    assert m["daily_peak_timing_mae_hours"] == 0


def test_origins_require_history():
    hours = pd.Series(pd.date_range("2024-01-01", periods=100, freq="h", tz="UTC"))
    with pytest.raises(ValueError, match="Not enough history"):
        origins(hours, 24, 3, 24, 24 * 365)


def test_gbm_family_when_sklearn_available(data):
    pytest.importorskip("sklearn")
    wx, load = data
    res = run_forecast(load, wx, cfg(model_family="gbm"))
    assert res["skill_vs_naive"] > 0


def test_format_build_mentions_ex_post_weather(data):
    wx, load = data
    res = run_forecast(load, wx, cfg())
    summary = {k: res[k] for k in ("metrics_model", "metrics_naive", "skill_vs_naive",
                                   "normalization_last_365_days", "data_report")}
    text = format_build(summary, {"run_id": "x", "outputs": {}, "decisions": {"a": 1}})
    assert "ex-post" in text and "naive" in text


def test_balance_points_function_shape():
    t = pd.Series(np.linspace(20, 90, 400))
    e = 100 + 5 * np.clip(55 - t, 0, None) + 9 * np.clip(t - 72, 0, None)
    bp = fit_balance_points(e, t, np.arange(45, 80, 1.0))
    assert (bp.iloc[0]["hdd_base"], bp.iloc[0]["cdd_base"]) == (55.0, 72.0)
