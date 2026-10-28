"""Reconciliation, combine modes, weather policy, aggregation, and ILT."""

from __future__ import annotations

import pandas as pd
import pytest

from npt_core import aggregate_npt, compute_ilt, flag_npt, normalize_ops, reconcile_hours
from npt_taxonomy import resolve_code_map
from npt_text import classify_remarks, primary_text_category


@pytest.fixture
def flagged_inputs(ops_raw, llm):
    ops = normalize_ops(ops_raw, 0)
    return ops, primary_text_category(classify_remarks(ops, llm)), resolve_code_map("iadc_style")


def test_reconcile_flags_short_day(ops_raw):
    recon = reconcile_hours(normalize_ops(ops_raw, 0), 0).set_index("report_day")
    assert recon.loc[pd.Timestamp("2026-03-01"), "status"] == "ok"
    day2 = recon.loc[pd.Timestamp("2026-03-02")]
    assert day2["status"] == "short_day" and day2["internal_gap_hr"] == pytest.approx(1.0)


def test_reconcile_detects_overlap():
    raw = pd.DataFrame({"well_id": ["W"] * 2, "rig_id": ["R"] * 2, "contractor": ["C"] * 2,
                        "start_time": ["2026-01-01 00:00", "2026-01-01 11:00"],
                        "end_time": ["2026-01-01 12:00", "2026-01-02 00:00"],
                        "activity_code": ["2", "2"], "remarks": ["", ""]})
    recon = reconcile_hours(normalize_ops(raw, 0), 0)
    assert recon.loc[0, "status"] == "overlap" and recon.loc[0, "overlap_hr"] == pytest.approx(1.0)


def test_dst_fall_back_day_is_25_hours():
    tz = "America/Chicago"
    start = pd.Timestamp("2026-11-01 00:00", tz=tz)
    end = pd.Timestamp("2026-11-02 00:00", tz=tz)
    raw = pd.DataFrame({"well_id": ["W"], "rig_id": ["R"], "contractor": ["C"], "start_time": [start],
                        "end_time": [end], "activity_code": ["2"], "remarks": [""]})
    recon = reconcile_hours(normalize_ops(raw, 0), 0)
    assert recon.loc[0, "expected_hr"] == 25.0 and recon.loc[0, "logged_hr"] == 25.0
    assert recon.loc[0, "status"] == "ok"


def test_report_day_start_six_shifts_assignment(ops_raw):
    ops = normalize_ops(ops_raw, 6)
    assert ops.loc[0, "report_day"] == pd.Timestamp("2026-02-28")


@pytest.mark.parametrize("mode,expected", [
    ("code_only", {"r2"}),  # only code 8 (repair rig) maps to NPT; 21 "other" does not
    ("text_only", {"r2", "r3", "r4"}),
    ("union", {"r2", "r3", "r4"}),
    ("intersection", {"r2"}),
])
def test_combine_modes(flagged_inputs, mode, expected):
    ops, text, code_map = flagged_inputs
    flagged = flag_npt(ops, text, code_map, mode, "npt")
    got = set(flagged.loc[flagged["is_npt"], "row_id"])
    assert got == expected


def test_weather_policies(flagged_inputs):
    ops, text, code_map = flagged_inputs
    npt = flag_npt(ops, text, code_map, "union", "npt")
    sep = flag_npt(ops, text, code_map, "union", "separate")
    assert npt.set_index("row_id").loc["r4", "npt_category"] == "WAIT_WEATHER"
    assert not sep.set_index("row_id").loc["r4", "is_npt"]
    agg = aggregate_npt(sep, ["well_id", "npt_category"], "separate")
    assert agg["weather_downtime_hr"].dropna().iloc[0] == pytest.approx(8.0)


def test_union_prefers_code_category(flagged_inputs):
    ops, text, code_map = flagged_inputs
    flagged = flag_npt(ops, text, code_map, "union", "npt").set_index("row_id")
    assert flagged.loc["r2", "npt_source"] == "both"
    assert flagged.loc["r3", "npt_source"] == "text"


def test_unmapped_codes_reported():
    raw = pd.DataFrame({"well_id": ["W"], "rig_id": ["R"], "contractor": ["C"],
                        "start_time": ["2026-01-01 00:00"], "end_time": ["2026-01-01 01:00"],
                        "activity_code": ["99X"], "remarks": [""]})
    ops = normalize_ops(raw, 0)
    flagged = flag_npt(ops, primary_text_category(classify_remarks(ops, lambda p: "{}")),
                       resolve_code_map("iadc_style"), "code_only", "npt")
    assert bool(flagged.loc[0, "unmapped_code"]) and not bool(flagged.loc[0, "is_npt"])


def test_aggregate_npt_pct(flagged_inputs):
    ops, text, code_map = flagged_inputs
    agg = aggregate_npt(flag_npt(ops, text, code_map, "union", "npt"), ["well_id", "npt_category"], "npt")
    lc = agg.set_index("npt_category").loc["LOST_CIRCULATION"]
    assert lc["npt_hr"] == pytest.approx(6.0)
    assert lc["npt_pct"] == pytest.approx(round(100 * 6 / 47, 2))


def test_ilt_rate_based_p10():
    n = 6
    raw = pd.DataFrame({
        "well_id": [f"W{i}" for i in range(n)], "rig_id": ["R"] * n, "contractor": ["C"] * n,
        "start_time": ["2026-01-01 00:00"] * n,
        "end_time": [f"2026-01-01 {h:02d}:00" for h in (10, 10, 10, 10, 10, 20)],
        "activity_code": ["2"] * n, "remarks": [""] * n, "footage_ft": [1000] * n})
    ops = normalize_ops(raw, 0)
    flagged = flag_npt(ops, primary_text_category(classify_remarks(ops, lambda p: "{}")), {"2": None}, "code_only", "npt")
    ilt = compute_ilt(flagged, "p10", ["activity_code"])
    assert ilt["ilt_hr"].iloc[-1] == pytest.approx(10.0)
    assert ilt["ilt_hr"].iloc[0] == pytest.approx(0.0)


def test_ilt_too_few_offsets_is_nan(flagged_inputs):
    ops, text, code_map = flagged_inputs
    ilt = compute_ilt(flag_npt(ops, text, code_map, "union", "npt"), "p10", ["activity_code"])
    assert ilt["ilt_hr"].isna().all()
