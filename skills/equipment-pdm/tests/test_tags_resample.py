"""Tag grounding, unit conversion, digital states, and gap-limited resampling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resample import resample_grid, resample_series
from tags import canonical_unit, ground_tags, normalize_samples


def test_grounding_reports_unmapped_and_missing(fleet):
    historian, tag_map, _ = fleet
    g = ground_tags(historian, tag_map)
    assert "ESP-101.SPARE1" in g.unmapped_tags
    assert g.missing_in_historian == ["ESP-104.MTR_AMPS"]
    assert len(g.mapped) == 12


def test_unknown_unit_excluded():
    hist = pd.DataFrame({"tag": ["T1"], "ts": [pd.Timestamp("2026-01-01", tz="UTC")], "value": ["1"]})
    tmap = pd.DataFrame({"tag": ["T1"], "asset_id": ["A"], "equipment_class": ["pump"],
                         "measurement": ["discharge_pressure"], "unit": ["furlongs"]})
    g = ground_tags(hist, tmap)
    assert g.mapped.empty and list(g.unit_problems["problem"]) == ["unit_unknown"]


def test_units_converted_and_digital_states_dropped(fleet):
    historian, tag_map, _ = fleet
    samples, dropped = normalize_samples(historian, ground_tags(historian, tag_map).mapped)
    temp = samples[(samples["asset_id"] == "ESP-102") & (samples["measurement"] == "motor_temperature")]
    assert temp["value"].median() == pytest.approx((230 - 32) * 5 / 9, abs=0.5)
    pip = samples[(samples["asset_id"] == "ESP-102") & (samples["measurement"] == "intake_pressure")]
    assert pip["value"].median() == pytest.approx(850 * 6.894757, rel=0.01)
    assert dropped["value"].str.contains("I/O Timeout").sum() == 3
    assert set(samples.loc[samples["measurement"] == "run_status", "value"]) == {0.0, 1.0}


def test_naive_timestamps_rejected():
    hist = pd.DataFrame({"tag": ["T1"], "ts": [pd.Timestamp("2026-01-01")], "value": ["1"]})
    tmap = pd.DataFrame({"tag": ["T1"], "asset_id": ["A"], "equipment_class": ["pump"],
                         "measurement": ["motor_current"], "unit": ["amps"]})
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_samples(hist, ground_tags(hist, tmap).mapped)


def test_unit_aliases():
    assert canonical_unit("°F") == "degF" and canonical_unit("Amps") == "A"


def _raw(times, values):
    return pd.DataFrame({"ts": pd.to_datetime(times, utc=True), "value": values})


def test_linear_interpolation_and_gap_limit():
    raw = _raw(["2026-01-01 00:00", "2026-01-01 00:20", "2026-01-01 03:00"], [0.0, 20.0, 50.0])
    grid = pd.date_range("2026-01-01 00:00", "2026-01-01 03:00", freq="10min", tz="UTC")
    s = resample_series(raw, grid, "linear", pd.Timedelta("30min"), is_state=False)
    assert s.iloc[1] == pytest.approx(10.0)
    assert np.isnan(s.loc[pd.Timestamp("2026-01-01 01:00", tz="UTC")])  # 2h40m gap not bridged
    assert s.iloc[-1] == 50.0


def test_step_and_state_hold():
    raw = _raw(["2026-01-01 00:00", "2026-01-01 05:00"], [1.0, 0.0])
    grid = pd.date_range("2026-01-01 00:00", "2026-01-01 05:00", freq="1h", tz="UTC")
    step = resample_series(raw, grid, "step", pd.Timedelta("30min"), is_state=False)
    state = resample_series(raw, grid, "step", pd.Timedelta("30min"), is_state=True)
    assert np.isnan(step.iloc[2])
    assert list(state) == [1.0, 1.0, 1.0, 1.0, 1.0, 0.0]


def test_resample_grid_wide(fleet):
    historian, tag_map, _ = fleet
    samples, _ = normalize_samples(historian, ground_tags(historian, tag_map).mapped)
    wide = resample_grid(samples, "30min", "linear", "30min")
    assert {"motor_current", "motor_temperature", "intake_pressure", "run_status"} <= set(wide.columns)
    assert wide["asset_id"].nunique() == 3
    with pytest.raises(ValueError):
        resample_grid(samples, "30min", "spline", "30min")
