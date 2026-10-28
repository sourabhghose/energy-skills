"""Preview / build entrypoints."""

import pandas as pd
import pytest

from conftest import RES, WEIGHTS
from wildfire_api import build_confirmed_wildfire_risk, preview_wildfire_risk
from wildfire_core import DecisionRequired

MITIGATIONS = pd.DataFrame({"mitigation": ["covered_conductor", "undergrounding"],
                            "effectiveness": [0.6, 0.97],
                            "cost_per_mile_usd": [700_000.0, 3_500_000.0]})


def test_preview_needs_no_decisions(segments, layers, forecast):
    out = preview_wildfire_risk(segments, layers, RES, 1, forecast)
    assert out["ok"]
    assert "Decisions needed" in out["readout"]
    assert len(out["psps_sensitivity"]) == 3


def test_preview_reports_bad_coordinates(segments, layers):
    bad = segments.assign(lat1=200.0)
    assert not preview_wildfire_risk(bad, layers, RES, 1)["ok"]


def test_build_requires_weights(segments, layers):
    with pytest.raises(DecisionRequired):
        build_confirmed_wildfire_risk(segments, layers, RES, 1, likelihood_weights=None,
                                      consequence_basis="structures")


def test_build_full_outputs(segments, layers, forecast):
    res = build_confirmed_wildfire_risk(
        segments, layers, RES, 1, likelihood_weights=WEIGHTS,
        consequence_basis="structures_and_population",
        psps_thresholds={"wind_gust_mph": 45, "rh_pct": 15}, forecast=forecast,
        mitigation_assumptions=MITIGATIONS, budget_usd=5_000_000)
    assert res["circuit_risk"].iloc[0]["circuit_id"] == "A"
    assert list(res["psps_candidates"]["circuit_id"]) == ["A"]
    assert res["mitigation_plan"]["selected"].any()
    assert res["manifest"]["decisions"]["likelihood_weights"] == WEIGHTS
    share = res["shareable_cells"]
    assert not {"segment_id", "lat1", "lon1"} & set(share.columns)
