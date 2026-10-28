"""Unit tests for IEEE 1366 index logic: step restoration, MED, denominators, momentary."""

import numpy as np
import pandas as pd
import pytest

from conftest import TZ
from reliability_core import (
    DecisionRequired,
    classify_steps,
    compute_indices,
    customer_level_indices,
    customers_served_for,
    daily_saidi,
    group_momentary_events,
    major_event_days,
    med_threshold,
    period_minutes,
    require_decisions,
    summarize_events,
    validate_steps,
)


def _stepped_event() -> pd.DataFrame:
    start = pd.Timestamp("2024-05-01 10:00", tz=TZ)
    return pd.DataFrame({
        "event_id": ["E1", "E1", "E1"],
        "outage_start": [start] * 3,
        "restore_ts": [start + pd.Timedelta(minutes=m) for m in (3, 60, 180)],
        "customers_restored": [100, 200, 50],
        "cause_code": ["EQP"] * 3,
        "is_planned": [False] * 3,
    })


def test_step_restoration_customer_minutes():
    events = summarize_events(classify_steps(_stepped_event(), 5), TZ)
    row = events.iloc[0]
    assert row["customer_minutes"] == pytest.approx(200 * 60 + 50 * 180)
    assert row["customers_interrupted"] == 250
    assert row["momentary_customers"] == 100


def test_one_minute_threshold_makes_short_step_sustained():
    events = summarize_events(classify_steps(_stepped_event(), 1), TZ)
    assert events.iloc[0]["customers_interrupted"] == 350
    assert events.iloc[0]["customer_minutes"] == pytest.approx(300 + 12_000 + 9_000)


def test_exactly_five_minutes_is_momentary():
    steps = _stepped_event().assign(
        restore_ts=lambda d: d["outage_start"] + pd.Timedelta(minutes=5))
    classified = classify_steps(steps, 5)
    assert not classified["is_sustained"].any()


def test_naive_timestamps_rejected():
    steps = _stepped_event().assign(outage_start=lambda d: d["outage_start"].dt.tz_localize(None))
    assert any("timezone-aware" in p for p in validate_steps(steps))
    with pytest.raises(ValueError):
        classify_steps(steps, 5)


def test_input_not_mutated():
    steps = _stepped_event()
    before = steps.copy()
    classify_steps(steps, 5)
    pd.testing.assert_frame_equal(steps, before)


def test_event_dated_by_local_day():
    start = pd.Timestamp("2024-05-02 03:30", tz="UTC")  # 22:30 on May 1 in Chicago
    steps = _stepped_event().assign(outage_start=start,
                                    restore_ts=start + pd.Timedelta(minutes=30))
    events = summarize_events(classify_steps(steps, 5), TZ)
    assert str(events.iloc[0]["event_date"]) == "2024-05-01"


def test_denominator_bases(customers):
    assert customers_served_for(customers, 2024, "average") == pytest.approx(165_500)
    assert customers_served_for(customers, 2024, "year_end") == pytest.approx(171_000)


def test_asai_uses_leap_year_minutes():
    assert period_minutes(2024) == 527_040
    assert period_minutes(2023) == 525_600


def test_med_threshold_matches_manual_fit(history, customers):
    events = summarize_events(classify_steps(history, 5), TZ)
    daily = daily_saidi(events, customers, "average")
    stats = med_threshold(daily, 2024)
    idx = pd.to_datetime(pd.Index(daily.index))
    window = daily[(idx.year >= 2019) & (idx.year < 2024)]
    logs = np.log(window[window > 0].to_numpy())
    expected = np.exp(logs.mean() + 2.5 * logs.std(ddof=1))
    assert stats["t_med_minutes"] == pytest.approx(expected)
    assert stats["history_years"] == [2019, 2020, 2021, 2022, 2023]


def test_med_ignores_reporting_year_data(history, customers):
    events = summarize_events(classify_steps(history, 5), TZ)
    base = med_threshold(daily_saidi(events, customers, "average"), 2024)["t_med_minutes"]
    bigger = events.assign(customer_minutes=np.where(events["year"] == 2024,
                                                     events["customer_minutes"] * 10,
                                                     events["customer_minutes"]))
    again = med_threshold(daily_saidi(bigger, customers, "average"), 2024)["t_med_minutes"]
    assert again == pytest.approx(base)


def test_storm_is_major_event_day(history, customers):
    events = summarize_events(classify_steps(history, 5), TZ)
    daily = daily_saidi(events, customers, "average")
    stats = med_threshold(daily, 2024)
    meds = major_event_days(daily, 2024, stats["t_med_minutes"])
    assert pd.Timestamp("2024-07-15").date() in meds


def test_med_needs_history(history, customers):
    events = summarize_events(classify_steps(history, 5), TZ)
    daily = daily_saidi(events, customers, "average")
    with pytest.raises(ValueError, match="history"):
        med_threshold(daily, 2019)


def test_compute_indices_relationships():
    events = summarize_events(classify_steps(_stepped_event(), 5), TZ)
    idx = compute_indices(events, 1_000, 2024)
    assert idx["saidi_min"] == pytest.approx(21.0)
    assert idx["saifi"] == pytest.approx(0.25)
    assert idx["caidi_min"] == pytest.approx(84.0)
    assert idx["maifi"] == pytest.approx(0.1)
    assert idx["asai"] == pytest.approx(1 - 21_000 / (1_000 * 527_040))


def test_maifi_e_groups_reclosing_sequences():
    t0 = pd.Timestamp("2024-06-01 08:00", tz=TZ)
    ops = pd.DataFrame({
        "device_id": ["R1", "R1", "R1", "R1", "R2"],
        "op_ts": [t0, t0 + pd.Timedelta(minutes=1), t0 + pd.Timedelta(minutes=2),
                  t0 + pd.Timedelta(minutes=20), t0],
        "customers_affected": [300, 300, 320, 300, 50],
    })
    events = group_momentary_events(ops)
    assert len(events) == 3
    assert events["customers_affected"].sum() == 320 + 300 + 50


def test_customer_level_indices():
    ce = pd.DataFrame({
        "customer_id": ["a", "a", "a", "a", "b", "c"],
        "event_id": ["1", "2", "3", "4", "1", "5"],
        "duration_min": [10, 10, 10, 10, 600, 200],
    })
    out = customer_level_indices(ce, n_t=10, cemi_n=3, celid_hours=8)
    assert out["caifi"] == pytest.approx(6 / 3)
    assert out["cemi_3"] == pytest.approx(0.1)
    assert out["celid_s_8h"] == pytest.approx(0.1)
    assert out["celid_t_8h"] == pytest.approx(0.1)


@pytest.mark.parametrize("missing", ["sustained_threshold_min", "denominator_basis",
                                     "planned_handling", "med_method"])
def test_every_decision_is_required(missing):
    kwargs = {"sustained_threshold_min": 5, "denominator_basis": "average",
              "planned_handling": "exclude_planned", "med_method": "ieee_2_5_beta"}
    with pytest.raises(DecisionRequired) as err:
        require_decisions(**{**kwargs, missing: None})
    assert err.value.decision == missing
