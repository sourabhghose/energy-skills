import numpy as np
import pandas as pd
import pytest

from ami_decisions import DecisionRequired, make_config
from ami_pipeline import preview_profile, vee_frame, vee_meter, vee_summary
from synth import TZ, raw_meter, to_register, true_profile

BASE = dict(interval_minutes=15, source_timezone=TZ, timestamp_basis="local_naive",
            interval_convention="ending", read_type="interval",
            net_metering_policy="negative_is_error", linear_max_gap_intervals=4,
            long_gap_method="like_day", max_estimation_gap_hours=24, spike_max_kw=48)


def cfg(**over):
    return make_config(**{**BASE, **over})


def _drop(raw, start, n):
    return raw.drop(raw.index[start:start + n]).reset_index(drop=True)


def test_clean_meter_round_trips_including_fall_back_day():
    raw, truth = raw_meter()
    out = vee_meter(raw, cfg())
    assert len(out) == len(truth)
    assert (out["quality_code"] == "ACTUAL").all()
    assert np.allclose(out["kwh"].sum(), truth["kwh"].sum())
    nov3 = out[out["local_date"] == pd.Timestamp("2024-11-03").date()]
    assert len(nov3) == 100


def test_short_gap_is_linear_long_gap_is_like_day_and_overlong_is_missing():
    raw, _ = raw_meter()
    raw = _drop(_drop(_drop(raw, 2000, 3), 1000, 40), 2500, 200)
    out = vee_meter(raw, cfg())
    codes = out["quality_code"].value_counts()
    assert codes["ESTIMATED_LINEAR"] == 3
    assert codes["ESTIMATED_LIKE_DAY"] == 40
    assert codes["MISSING"] == 200  # 50 h > 24 h cap
    assert out.loc[out["quality_code"] == "MISSING", "kwh"].isna().all()


def test_leave_missing_disables_like_day():
    raw, _ = raw_meter()
    out = vee_meter(_drop(raw, 1000, 40), cfg(long_gap_method="leave_missing"))
    assert (out["quality_code"] == "MISSING").sum() == 40


def test_spike_negative_and_flatline_are_invalidated_and_estimated():
    raw, truth = raw_meter()
    vals = raw["value"].to_numpy().copy()
    vals[500] = 30.0           # 120 kW over 15 min > 48 kW service
    vals[800] = -0.4           # negative on a non-net-metered premise
    vals[1200:1224] = 0.777    # 6 h stuck register
    out = vee_meter(raw.assign(value=vals), cfg())
    assert "spike" in out.loc[500, "flags"]
    assert "negative_error" in out.loc[800, "flags"]
    assert out.loc[1200:1223, "flags"].str.contains("flatline").all()
    assert out.loc[[500, 800], "quality_code"].eq("ESTIMATED_LINEAR").all()
    assert abs(out.loc[500, "kwh"] - truth.loc[500, "kwh"]) < 0.3


def test_negative_is_valid_export_when_net_metered():
    raw, _ = raw_meter()
    vals = raw["value"].to_numpy().copy()
    vals[800] = -0.4
    out = vee_meter(raw.assign(value=vals), cfg(net_metering_policy="negative_is_export"))
    assert out.loc[800, "quality_code"] == "ACTUAL" and out.loc[800, "kwh"] == -0.4


def test_per_meter_net_metering_policy():
    a, _ = raw_meter("NEM1", seed=1)
    b, _ = raw_meter("STD1", seed=2)
    both = pd.concat([a, b], ignore_index=True)
    both.loc[both.index[[800, len(a) + 800]], "value"] = -0.4
    out = vee_frame(both, cfg(net_metering_policy="per_meter", net_metered_meter_ids=["NEM1"]))
    by = out.set_index(["meter_id", out.groupby("meter_id").cumcount()])
    assert by.loc[("NEM1", 800), "quality_code"] == "ACTUAL"
    assert by.loc[("STD1", 800), "quality_code"] == "ESTIMATED_LINEAR"
    with pytest.raises(ValueError, match="net_metered_meter_ids"):
        cfg(net_metering_policy="per_meter")


def test_duplicates_and_source_estimates():
    raw, _ = raw_meter()
    dup = pd.concat([raw, raw.iloc[[10]].assign(value=9.9)], ignore_index=True)
    dup.loc[20, "quality"] = "E"
    out = vee_meter(dup, cfg())
    assert "duplicate_conflict" in out.loc[10, "flags"]
    assert out.loc[20, "quality_code"] == "SOURCE_ESTIMATED"


def test_register_reads_with_rollover_and_gap_are_energy_conserving():
    truth = true_profile("2024-10-20 05:00", "2024-10-27 05:00")
    reads = to_register(truth, start_reading=99990.0, rollover=100000.0)
    reads = reads.drop(reads.index[100:108]).reset_index(drop=True)
    out = vee_meter(reads, cfg(read_type="register", timestamp_basis="utc",
                               register_rollover_kwh=100000.0))
    assert out["flags"].str.contains("register_rollover").any()
    assert np.isclose(out["kwh"].sum(), truth["kwh"].sum(), atol=1e-6)
    # 8 dropped reads leave one 9-interval register delta spanning the gap
    assert (out["quality_code"] == "ESTIMATED_REGISTER_PRORATED").sum() == 9


def test_summary_and_frame_over_two_meters():
    a, _ = raw_meter("A", seed=1)
    b, _ = raw_meter("B", seed=2)
    out = vee_frame(pd.concat([a, _drop(b, 100, 3)], ignore_index=True), cfg())
    summary = vee_summary(out, cfg())
    assert set(summary["meter_id"]) == {"A", "B"}
    assert summary.set_index("meter_id").loc["B", "ESTIMATED_LINEAR"] == 3


def test_missing_decision_raises_decision_required():
    with pytest.raises(DecisionRequired, match="net_metering_policy"):
        make_config(**{**BASE, "net_metering_policy": None})
    with pytest.raises(DecisionRequired, match="source_timezone"):
        make_config(**{**BASE, "source_timezone": "Mars/Olympus"})
    with pytest.raises(ValueError, match="register_rollover_kwh"):
        make_config(**{**BASE, "read_type": "register"})


def test_preview_surfaces_gap_spike_and_dst_effects_without_building():
    raw, _ = raw_meter()
    vals = raw["value"].to_numpy().copy()
    vals[500] = 30.0
    prof = preview_profile(_drop(raw.assign(value=vals), 1000, 40), TZ)
    assert prof["detected_interval_minutes"] == 15
    assert prof["detected_read_type"] == "interval"
    assert prof["gap_runs_by_length_intervals"]["17-96"] == 1
    assert prof["spike_counts_by_kw_ceiling"]["48.0"] == 1
    assert prof["dst_fall_back_single_labels"] == 0


def test_inputs_are_not_mutated():
    raw, _ = raw_meter()
    before = raw.copy()
    vee_meter(raw, cfg())
    pd.testing.assert_frame_equal(raw, before)
