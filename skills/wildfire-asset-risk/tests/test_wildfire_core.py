"""Spatial joins, scoring, PSPS screening and mitigation selection."""

import pandas as pd
import pytest

from conftest import RES, WEIGHTS, make_forecast
from h3grid import BACKEND, cell_for, disk
from wildfire_core import (
    DecisionRequired,
    check_coordinates,
    fuel_hazard,
    plan_mitigation,
    psps_candidates,
    score_segments,
    segment_cells,
    validate_weights,
)


def test_densified_spans_cover_more_cells_than_endpoints(segments):
    dense = segment_cells(segments.head(1), RES)
    row = segments.iloc[0]
    endpoints = {cell_for(row.lat1, row.lon1, RES), cell_for(row.lat2, row.lon2, RES)}
    assert dense["cell"].nunique() > len(endpoints)


def test_swapped_coordinates_detected(segments):
    swapped = segments.assign(lat1=segments["lon1"], lon1=segments["lat1"])
    assert any("swapped" in p for p in check_coordinates(swapped))


def test_fuel_hazard_families():
    h = fuel_hazard(pd.Series(["SH5", "nb1", "GR2", "XX9"]))
    assert h.iloc[0] > h.iloc[2] > h.iloc[1] == 0.0
    assert pd.isna(h.iloc[3])


def test_weights_are_a_decision():
    with pytest.raises(DecisionRequired):
        validate_weights(None)
    with pytest.raises(ValueError, match="sum to 1"):
        validate_weights({"vegetation": 0.5, "fuel": 0.2})


def test_hazardous_populated_circuit_ranks_first(segments, layers):
    cells = segment_cells(segments, RES)
    scored = score_segments(cells, segments, layers, WEIGHTS, "structures_and_population", 1)
    assert set(scored.head(5)["circuit_id"]) == {"A"}
    assert scored["risk"].between(0, 1).all()
    c_seg = scored.loc[scored["circuit_id"] == "C"]
    assert (c_seg["consequence"] < scored.loc[scored["circuit_id"] == "A", "consequence"].min()).all()


def test_consequence_basis_required(segments, layers):
    cells = segment_cells(segments, RES)
    with pytest.raises(DecisionRequired):
        score_segments(cells, segments, layers, WEIGHTS, None, 1)


def test_ignition_buffer_counts_nearby_history(segments, layers):
    cells = segment_cells(segments, RES)
    near = score_segments(cells, segments, layers, WEIGHTS, "structures", 2)
    assert near.loc[near["circuit_id"] == "A", "ignition_history"].max() > 0
    assert near.loc[near["circuit_id"] == "C", "ignition_history"].max() == 0


def test_inputs_not_mutated(segments, layers):
    before = segments.copy()
    score_segments(segment_cells(segments, RES), segments, layers, WEIGHTS, "structures", 1)
    pd.testing.assert_frame_equal(segments, before)


def test_psps_flags_only_hftd_circuits_meeting_thresholds(segments, forecast):
    cells = segment_cells(segments, RES)
    out = psps_candidates(cells, segments, forecast, {"wind_gust_mph": 45, "rh_pct": 15})
    assert list(out["circuit_id"]) == ["A"]  # C meets weather but is not in an HFTD
    calm = make_forecast(gust=20, rh=40)
    assert psps_candidates(cells, segments, calm, {"wind_gust_mph": 45, "rh_pct": 15}).empty


def test_psps_thresholds_are_a_decision(segments, forecast):
    cells = segment_cells(segments, RES)
    with pytest.raises(DecisionRequired):
        psps_candidates(cells, segments, forecast, {"wind_gust_mph": 45})


def test_psps_optional_ffwi_threshold(segments, forecast):
    cells = segment_cells(segments, RES)
    strict = {"wind_gust_mph": 45, "rh_pct": 15, "ffwi": 99}
    assert psps_candidates(cells, segments, forecast, strict).empty


def test_mitigation_greedy_skips_items_that_do_not_fit():
    scored = pd.DataFrame({"segment_id": ["s1", "s2", "s3"], "circuit_id": ["A"] * 3,
                           "length_mi": [10.0, 1.0, 1.0], "risk": [0.9, 0.5, 0.4]})
    mit = pd.DataFrame({"mitigation": ["covered_conductor"], "effectiveness": [0.6],
                        "cost_per_mile_usd": [800_000.0]})
    plan = plan_mitigation(scored, mit, budget_usd=2_000_000)
    assert set(plan.loc[plan["selected"], "segment_id"]) == {"s2", "s3"}
    with pytest.raises(DecisionRequired):
        plan_mitigation(scored, None, budget_usd=1)


def test_disk_grows_with_k():
    c = cell_for(38.5, -122.5, RES)
    assert len(disk(c, 0)) == 1
    assert len(disk(c, 2)) > len(disk(c, 1)) > 1


def test_h3_backend_matches_python_h3():
    h3 = pytest.importorskip("h3")
    assert BACKEND == "h3"
    assert cell_for(38.5, -122.5, RES) == h3.latlng_to_cell(38.5, -122.5, RES)
