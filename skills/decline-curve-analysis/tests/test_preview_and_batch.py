"""Preview readout and the pure-pandas batch used by the runner."""

import pytest
from conftest import synth_well

from dca_config import DecisionRequired
from dca_preview import preview_wells
from dca_run import _check_columns, _check_stream, analyze_all


def test_preview_is_readonly_and_shows_sensitivity():
    text = preview_wells({"42-123-45678": synth_well(downtime={8: 12.0})}, "monthly", "bbl")
    assert "READ-ONLY" in text
    assert "periods with downtime: 1" in text
    assert "ILLUSTRATIVE" in text
    assert "b_bounds" in text and "terminal_decline_eff" in text


def test_batch_marks_bad_wells_without_failing(decisions):
    bad = synth_well(months=4).assign(volume=0.0)
    fits, forecast = analyze_all({"good": synth_well(), "bad": bad}, "monthly", decisions, "bbl")
    status = dict(zip(fits["well_id"], fits["status"]))
    assert status["good"] == "ok"
    assert status["bad"].startswith("error")
    assert set(forecast["well_id"]) == {"good"}
    assert (fits["volume_unit"] == "bbl").all()


def test_stream_and_column_validation():
    with pytest.raises(DecisionRequired):
        _check_stream("boe/d", "monthly")
    with pytest.raises(ValueError):
        _check_columns(volume_col="oil; DROP TABLE x")
