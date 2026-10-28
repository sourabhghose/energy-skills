"""Type curves: PRMS percentile convention, normalization, survivor-bias truncation."""

import pytest
from conftest import synth_well

from dca_config import TypeCurveDecisions
from dca_typecurve import build_type_curve, eur_percentiles, prms_percentiles


def test_prms_convention_p10_is_high():
    p = prms_percentiles(range(1, 101))
    assert p["p10_high"] > p["p50"] > p["p90_low"]
    assert p["p10_high"] == pytest.approx(90.1)
    assert p["p90_low"] == pytest.approx(10.9)


def test_lateral_normalization_scales_eur():
    tcd = TypeCurveDecisions.from_kwargs("lateral_length", 10_000)
    p = eur_percentiles({"a": 500_000.0}, {"a": 5_000.0}, tcd)
    assert p["p50"] == pytest.approx(1_000_000.0)


def test_missing_lateral_excluded(decisions):
    tcd = TypeCurveDecisions.from_kwargs("lateral_length", 10_000)
    wells = {f"w{i}": synth_well(qi=600 + 50 * i, seed=i) for i in range(6)}
    laterals = {f"w{i}": 7_500.0 + 500 * i for i in range(5)}          # w5 has no lateral
    tc = build_type_curve(wells, laterals, decisions, tcd, min_wells=5)
    assert tc.wells_excluded == {"w5": "missing_or_invalid_lateral_length"}
    assert (tc.curve["p10_high_rate"] >= tc.curve["p50_rate"]).all()
    assert (tc.curve["p50_rate"] >= tc.curve["p90_low_rate"]).all()
    assert tc.fits["p50_rate"] is not None


def test_survivor_bias_truncation(decisions):
    tcd = TypeCurveDecisions.from_kwargs("none")
    wells = {f"w{i}": synth_well(months=24 + 12 * i, seed=i) for i in range(6)}
    tc = build_type_curve(wells, {}, decisions, tcd, min_wells=5)
    assert tc.curve["n_wells"].min() >= 5
    assert tc.curve["month_index"].max() < 24 + 12 * 5 - 2
