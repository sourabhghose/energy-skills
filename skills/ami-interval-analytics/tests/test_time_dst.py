import pandas as pd
import pytest

from ami_time import (dst_transition_dates, expected_intervals_per_local_day,
                      label_instants_utc, to_interval_start_utc)
from synth import TZ, to_ending_local_labels, true_profile


@pytest.mark.parametrize("start,end", [("2024-11-03 04:00", "2024-11-03 10:00"),
                                       ("2024-03-10 05:00", "2024-03-10 11:00")])
def test_ending_labels_round_trip_through_both_dst_transitions(start, end):
    truth = true_profile(start, end)
    labels = to_ending_local_labels(truth)
    out = to_interval_start_utc(labels, TZ, "local_naive", "ending", 15)
    assert (out["interval_start_utc"].to_numpy() == truth["interval_start_utc"].to_numpy()).all()
    assert not out["flag_nonexistent_time"].any()


def test_fall_back_hour_has_repeated_labels_resolved_by_order():
    truth = true_profile("2024-11-03 05:00", "2024-11-03 08:00")
    labels = truth["interval_start_utc"].dt.tz_convert(TZ).dt.tz_localize(None)
    assert labels.duplicated().sum() == 4  # 01:00-01:45 appear twice
    out = to_interval_start_utc(labels, TZ, "local_naive", "beginning", 15)
    assert out["interval_start_utc"].is_unique


def test_naive_subtraction_before_localizing_would_be_wrong():
    # Documents the pitfall: subtracting 15 min from wall-clock labels before localizing
    # collides with the previous interval at the fall-back boundary.
    truth = true_profile("2024-11-03 05:00", "2024-11-03 08:00")
    labels = to_ending_local_labels(truth)
    naive_start = labels - pd.Timedelta(minutes=15)
    wrong = to_interval_start_utc(naive_start, TZ, "local_naive", "beginning", 15)
    mismatched = wrong["interval_start_utc"].to_numpy() != truth["interval_start_utc"].to_numpy()
    assert mismatched.any()  # 00:45 now appears twice and lands on the wrong UTC instant


def test_single_occurrence_of_ambiguous_label_is_flagged():
    labels = pd.Series(pd.to_datetime(["2024-11-03 00:45", "2024-11-03 01:15",
                                       "2024-11-03 02:15"]))
    out = label_instants_utc(labels, TZ, "local_naive")
    assert out["flag_dst_ambiguous_single"].tolist() == [False, True, False]


def test_nonexistent_spring_forward_label_is_flagged():
    labels = pd.Series(pd.to_datetime(["2024-03-10 01:45", "2024-03-10 02:15",
                                       "2024-03-10 03:00"]))
    out = label_instants_utc(labels, TZ, "local_naive")
    assert out["flag_nonexistent_time"].tolist() == [False, True, False]


def test_expected_intervals_handle_23_and_25_hour_days():
    days = pd.Series(pd.to_datetime(["2024-03-10", "2024-11-03", "2024-07-01"]))
    assert expected_intervals_per_local_day(days, TZ, 15).tolist() == [92, 100, 96]
    assert len(dst_transition_dates(2024, TZ)) == 2


def test_utc_and_offset_bases():
    labels = pd.Series(["2024-11-03T06:15:00Z", "2024-11-03T06:30:00Z"])
    out = to_interval_start_utc(labels, TZ, "offset_aware", "ending", 15)
    assert str(out["interval_start_utc"].iloc[0]) == "2024-11-03 06:00:00+00:00"
    naive = pd.Series(pd.to_datetime(["2024-11-03 06:15"]))
    out2 = to_interval_start_utc(naive, TZ, "utc", "beginning", 15)
    assert str(out2["interval_start_utc"].iloc[0]) == "2024-11-03 06:15:00+00:00"
