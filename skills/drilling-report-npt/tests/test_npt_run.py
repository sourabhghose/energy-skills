"""Runner contract: decisions are mandatory, and the offline build path is reproducible."""

from __future__ import annotations

import pandas as pd
import pytest

import npt_run
from npt_taxonomy import DecisionRequired
from conftest import fake_llm
from npt_text import build_prompt

DECISIONS = dict(code_taxonomy="iadc_style", combine_mode="union", weather_policy="separate",
                 report_day_start_hour=0, ilt_benchmark="p10")


@pytest.fixture
def patched(monkeypatch, ops_raw):
    responses = [fake_llm(build_prompt(r)) for r in ops_raw["remarks"]]
    with_llm = ops_raw.assign(npt_response=responses)
    monkeypatch.setattr(npt_run, "_read_ops_with_llm", lambda *a, **k: with_llm)
    monkeypatch.setattr(npt_run, "_read_ops", lambda *a, **k: ops_raw)
    return with_llm


@pytest.mark.parametrize("missing", list(DECISIONS))
def test_missing_decision_raises(missing, patched):
    args = {**DECISIONS, missing: None}
    with pytest.raises(DecisionRequired, match=missing):
        npt_run.build_confirmed_npt("c.s.t", "c.s.out", endpoint="ep", write=False, **args)


def test_decisions_have_no_defaults():
    with pytest.raises(TypeError):
        npt_run.build_confirmed_npt("c.s.t", "c.s.out")


def test_invalid_option_rejected(patched):
    with pytest.raises(DecisionRequired):
        npt_run.build_confirmed_npt("c.s.t", "c.s.out", endpoint="ep", write=False,
                                    **{**DECISIONS, "weather_policy": "sometimes"})


def test_text_mode_needs_endpoint(patched):
    with pytest.raises(DecisionRequired, match="endpoint"):
        npt_run.build_confirmed_npt("c.s.t", "c.s.out", write=False, **DECISIONS)


def test_bad_identifiers_rejected(patched):
    with pytest.raises(ValueError):
        npt_run.build_confirmed_npt("c.s.t; DROP TABLE x", "c.s.out", endpoint="ep", write=False, **DECISIONS)
    with pytest.raises(ValueError):
        npt_run.validate_endpoint("ep'); DROP")


def test_build_offline(patched):
    result = npt_run.build_confirmed_npt("c.s.t", "c.s.out", endpoint="ep", write=False, **DECISIONS)
    by_cat = result["npt_by_category"].set_index("npt_category")["npt_hr"].to_dict()
    assert by_cat == {"EQUIPMENT_RIG": 4.0, "LOST_CIRCULATION": 6.0}
    assert result["manifest"]["decisions"]["combine_mode"] == "union"
    assert result["manifest"]["text_events_dropped"] == 3
    assert len(result["npt_evidence"]) == 2
    assert "NPT result" in npt_run.format_result(result)


def test_preview_is_read_only_and_lists_decisions(patched, monkeypatch):
    monkeypatch.setattr(npt_run, "write_table", lambda *a, **k: pytest.fail("preview wrote a table"))
    text = npt_run.preview_npt_options("c.s.t", endpoint="ep")
    assert "READ-ONLY" in text and "| union |" in text and "06:00" in text
    assert "weather_policy" in text
