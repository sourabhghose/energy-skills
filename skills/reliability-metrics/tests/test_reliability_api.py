"""Preview / build entrypoints and metric view generation."""

import pandas as pd
import pytest
import yaml

from conftest import TZ
from metric_view import build_daily_fact, metric_view_sql, metric_view_yaml
from reliability_api import build_confirmed_reliability, preview_reliability_options
from reliability_core import DecisionRequired, classify_steps, summarize_events

DECISIONS = {"sustained_threshold_min": 5, "denominator_basis": "average",
             "planned_handling": "exclude_planned", "med_method": "ieee_2_5_beta"}


def test_preview_lists_all_scenarios_without_decisions(history, customers):
    out = preview_reliability_options(history, customers, 2024, TZ)
    assert out["ok"]
    assert len(out["scenarios"]) == 16
    assert "Decisions needed" in out["readout"]


def test_build_requires_decisions(history, customers):
    with pytest.raises(DecisionRequired):
        build_confirmed_reliability(history, customers, 2024, TZ,
                                    **{**DECISIONS, "med_method": None})


def test_build_reports_both_with_and_without_med(history, customers):
    res = build_confirmed_reliability(history, customers, 2024, TZ, **DECISIONS)
    assert res["excluding_med"]["saidi_min"] < res["all_days"]["saidi_min"]
    assert res["headline"] == res["excluding_med"]
    assert res["manifest"]["decisions"] == DECISIONS
    assert "2024-07-15" in res["manifest"]["major_event_days"]


def test_planned_exclusion_changes_cmi(history, customers):
    excl = build_confirmed_reliability(history, customers, 2024, TZ, **DECISIONS)
    incl = build_confirmed_reliability(history, customers, 2024, TZ,
                                       **{**DECISIONS, "planned_handling": "include_planned"})
    diff = incl["all_days"]["customer_minutes_interrupted"] - \
        excl["all_days"]["customer_minutes_interrupted"]
    assert diff == pytest.approx(30_000.0)


def test_daily_fact_reproduces_core_saidi(history, customers):
    res = build_confirmed_reliability(history, customers, 2024, TZ, **DECISIONS)
    events = summarize_events(classify_steps(history, 5), TZ)
    events = events.loc[~events["is_planned"]]
    fact = build_daily_fact(events, customers, res["major_event_days"], 2024, "average")
    assert len(fact) == 366
    n_t = fact["customers_served"].sum() / fact["event_date"].nunique()
    saidi = fact["customer_minutes"].sum() / n_t
    saidi_excl = fact.loc[~fact["is_med"], "customer_minutes"].sum() / n_t
    assert saidi == pytest.approx(res["all_days"]["saidi_min"])
    assert saidi_excl == pytest.approx(res["excluding_med"]["saidi_min"])


def test_metric_view_yaml_is_valid_and_composed():
    body = yaml.safe_load(metric_view_yaml("main.rel.daily_fact"))
    assert body["version"] == "1.1"
    measures = {m["name"]: m["expr"] for m in body["measures"]}
    assert measures["saidi_min"].startswith("MEASURE(")
    assert "COUNT(DISTINCT event_date)" in measures["customers_served"]
    sql = metric_view_sql("main.rel.mv", "main.rel.daily_fact")
    assert sql.startswith("CREATE OR REPLACE VIEW `main`.`rel`.`mv`")


def test_metric_view_rejects_bad_identifier():
    with pytest.raises(ValueError):
        metric_view_sql("main.rel.mv; DROP TABLE x", "main.rel.daily_fact")
