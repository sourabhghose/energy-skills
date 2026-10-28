import numpy as np
import pandas as pd

from ami_estimate import consumption_drop_indicator, reconcile_to_register
from ami_validate import detect_read_type, register_to_interval, run_lengths
from synth import TZ, true_profile


def test_run_lengths():
    assert run_lengths(pd.Series([True, True, False, True])).tolist() == [2, 2, 0, 1]


def test_detect_read_type():
    truth = true_profile("2024-10-01", "2024-10-03")
    assert detect_read_type(truth["kwh"]) == "interval"
    assert detect_read_type(52000 + truth["kwh"].cumsum()) == "register"


def test_register_reset_is_not_treated_as_rollover():
    reads = pd.DataFrame({
        "instant_utc": pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC"),
        "register_kwh": [5000.0, 5000.5, 12.0, 12.4]})
    out = register_to_interval(reads, 15, 100000.0)
    assert out["flag_register_reset"].tolist() == [False, True, False]
    assert np.isnan(out["kwh"].iloc[1])


def test_reconciliation_flags_period_outside_tolerance():
    truth = true_profile("2024-10-01 05:00", "2024-10-03 05:00")
    register = pd.DataFrame({"instant_utc": pd.to_datetime(
        ["2024-10-01 05:00", "2024-10-02 05:00", "2024-10-03 05:00"], utc=True)})
    day1 = truth["kwh"].iloc[:96].sum()
    day2 = truth["kwh"].iloc[96:].sum()
    register = register.assign(register_kwh=[0.0, day1, day1 + day2 * 1.05])
    out = reconcile_to_register(truth, register, tolerance_pct=1.0)
    assert out["within_tolerance"].tolist() == [True, False]


def test_sustained_drop_indicator():
    truth = true_profile("2024-01-01 06:00", "2024-05-01 05:00")
    cut = truth["interval_start_utc"] >= pd.Timestamp("2024-04-01", tz="UTC")
    dropped = truth.assign(kwh=truth["kwh"].where(~cut, truth["kwh"] * 0.2))
    assert consumption_drop_indicator(dropped, TZ)["flag_sustained_drop"] is True
    assert consumption_drop_indicator(truth, TZ)["flag_sustained_drop"] is False
