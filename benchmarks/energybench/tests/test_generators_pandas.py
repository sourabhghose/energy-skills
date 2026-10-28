"""Cross-check a few planted truths with pandas, the way an analyst would compute them (skipped without pandas)."""

import pytest

pd = pytest.importorskip("pandas")

from generators import power, markets, renewables  # noqa: E402


def test_p01_with_pandas_tz_localize(tmp_path):
    key = power.p01_ami_dst(tmp_path, 20261028)
    df = pd.read_csv(tmp_path / "interval_reads.csv").sort_values(["meter_id", "read_seq"])
    local = pd.to_datetime(df["interval_start_local"])
    df["ts"] = local.groupby(df["meter_id"]).transform(
        lambda s: s.dt.tz_localize("America/Chicago", ambiguous="infer"))
    daily = df.groupby(df["ts"].dt.strftime("%Y-%m-%d"))["kwh"].sum()
    assert daily["2025-11-02"] == pytest.approx(key["system_kwh_2025_11_02"], abs=1e-6)


def test_p08_with_pandas_resample_right_closed(tmp_path):
    key = markets.p08_iso_interval_ending(tmp_path, 20261028)
    df = pd.read_csv(tmp_path / "rt_lmp_5min.csv", parse_dates=["interval_ending_local"])
    hourly = df.set_index("interval_ending_local")["rt_lmp_usd_per_mwh"].resample("h", closed="right",
                                                                                 label="right").mean()
    assert hourly[pd.Timestamp("2024-07-15 18:00")] == pytest.approx(key["rt_price_he18"], rel=1e-6)


def test_p17_with_pandas(tmp_path):
    key = renewables.p17_wind_curtailment(tmp_path, 20261028)
    df = pd.read_csv(tmp_path / "scada_10min.csv")
    pc = pd.read_csv(tmp_path / "reference_power_curve.csv")
    import numpy as np

    df = df[df["available"] == 1].assign(expected=lambda d: np.interp(d["wind_speed_ms"], pc["wind_speed_ms"],
                                                                      pc["power_kw"]))
    loss = (df["expected"] - df["active_power_kw"]).clip(lower=0) / 6 / 1000
    curtailed = df["park_setpoint_kw"] < 2050
    assert loss[curtailed].sum() == pytest.approx(key["curtailment_loss_mwh"], rel=1e-4)
    assert loss[~curtailed].sum() == pytest.approx(key["underperformance_loss_mwh"], rel=1e-4)
