"""Fitting, conditioning, EUR, flags, and decisions on planted-truth synthetic wells."""

import numpy as np
import pytest
from conftest import synth_well

from dca_config import DcaDecisions, DecisionRequired, TypeCurveDecisions
from dca_fit import fit_decline
from dca_models import modified_rate, terminal_effective_to_nominal
from dca_prep import condition_well
from dca_well import analyze_well, forecast_well


def test_fit_recovers_planted_parameters():
    d_lim = terminal_effective_to_nominal(0.08)
    t = (np.arange(48) + 0.5) / 12
    fit = fit_decline(t, modified_rate(t, 800, 3.0, 1.3, d_lim), (0.0, 2.0), d_lim)
    assert fit.b == pytest.approx(1.3, abs=1e-3)
    assert fit.di == pytest.approx(3.0, rel=1e-3)
    assert fit.qi == pytest.approx(800, rel=1e-3)


def test_fit_respects_b_bounds():
    d_lim = terminal_effective_to_nominal(0.08)
    t = (np.arange(48) + 0.5) / 12
    fit = fit_decline(t, modified_rate(t, 800, 3.0, 1.8, d_lim), (0.0, 1.0), d_lim)
    assert 0.0 <= fit.b <= 1.0
    assert fit.b == pytest.approx(1.0)


def test_fit_is_deterministic():
    pdf = synth_well(seed=7)
    t = np.arange(len(pdf)) / 12 + 1 / 24
    q = pdf["volume"] / pdf["days_on"]
    a = fit_decline(t[2:], q[2:].to_numpy(), (0, 2), 0.08)
    b = fit_decline(t[2:], q[2:].to_numpy(), (0, 2), 0.08)
    assert a == b


def test_fit_rejects_zero_rates():
    with pytest.raises(ValueError, match="shut-in"):
        fit_decline([0.1, 0.2, 0.3], [10.0, 0.0, 5.0], (0, 1), None)


def test_peak_start_excludes_ramp():
    cw = condition_well(synth_well(), "monthly", "producing_day", "peak", "none")
    assert cw.exclusions.get("pre_decline") == 2
    assert cw.decline_start.isoformat().startswith("2020-03-01")


def test_shut_in_excluded_and_counted_in_cum():
    pdf = synth_well(shut_in=(20,))
    cw = condition_well(pdf, "monthly", "producing_day", "peak", "none")
    assert cw.exclusions["shut_in_or_zero"] == 1
    assert cw.cum_volume == pytest.approx(pdf["volume"].sum())


def test_producing_day_vs_calendar_day_rates():
    pdf = synth_well(downtime={10: 10.0})
    prod = condition_well(pdf, "monthly", "producing_day", "peak", "none").frame.loc[10, "rate"]
    cal = condition_well(pdf, "monthly", "calendar_day", "peak", "none").frame.loc[10, "rate"]
    calendar_days = pdf["period_start"].dt.days_in_month[10]
    assert prod == pytest.approx(cal * calendar_days / 10)
    assert prod > cal


def test_producing_day_requires_days_on():
    with pytest.raises(ValueError, match="days_on"):
        condition_well(synth_well().drop(columns="days_on"), "monthly", "producing_day", "peak", "none")


def test_mad_flags_workover_spike():
    cw = condition_well(synth_well(spike=30), "monthly", "producing_day", "peak", "mad")
    assert cw.frame.loc[30, "exclude_reason"] == "outlier"


def test_duplicate_periods_rejected():
    pdf = synth_well()
    with pytest.raises(ValueError, match="duplicate"):
        condition_well(pdf.iloc[[0, 0, 1, 2]], "monthly", "calendar_day", "peak", "none")


def test_eur_close_to_planted_truth(decisions):
    from dca_models import DAYS_PER_YEAR, modified_cum, time_to_rate

    pdf = synth_well(months=48)
    res = analyze_well(pdf, "monthly", decisions)
    d_lim = terminal_effective_to_nominal(0.08)
    t_end = time_to_rate(5.0, 900, 4.0, 1.3, d_lim)
    truth = pdf["volume"].iloc[:2].sum() + float(modified_cum(t_end, 900, 4.0, 1.3, d_lim)) * DAYS_PER_YEAR
    assert res["status"] == "ok"
    assert res["eur"] == pytest.approx(truth, rel=0.03)
    assert res["flags"] == []


def test_forecast_volumes_sum_to_remaining(decisions):
    res = analyze_well(synth_well(), "monthly", decisions)
    assert forecast_well(res)["volume"].sum() == pytest.approx(res["remaining"], rel=1e-9)


def test_flags_unbounded_hyperbolic():
    d = DcaDecisions.from_kwargs(rate_basis="producing_day", decline_start="peak", outlier_method="none",
                                 b_bounds=(0.0, 2.5), terminal_decline_eff="none", econ_limit_rate=1.0,
                                 max_life_years=60.0)
    res = analyze_well(synth_well(b=2.3, terminal=None), "monthly", d)
    assert "hyperbolic_b_ge_1_without_terminal_decline" in res["flags"]
    assert "b_above_2" in res["flags"]


def test_max_life_truncation_flag(decisions):
    short = DcaDecisions(**{**decisions.as_dict(), "max_life_years": 6.0})
    res = analyze_well(synth_well(), "monthly", short)
    assert res["end_reason"] == "max_life"
    assert "eur_truncated_by_max_life" in res["flags"]


@pytest.mark.parametrize("missing", ["rate_basis", "decline_start", "outlier_method", "b_bounds",
                                     "terminal_decline_eff", "econ_limit_rate", "max_life_years"])
def test_every_decision_is_required(missing):
    kw = dict(rate_basis="producing_day", decline_start="peak", outlier_method="mad", b_bounds=(0, 1.5),
              terminal_decline_eff=0.08, econ_limit_rate=5.0, max_life_years=50)
    kw.pop(missing)
    with pytest.raises(DecisionRequired) as exc:
        DcaDecisions.from_kwargs(**kw)
    assert exc.value.decision == missing


def test_b_bounds_sanity():
    with pytest.raises(DecisionRequired):
        DcaDecisions.from_kwargs(rate_basis="calendar_day", decline_start="peak", outlier_method="none",
                                 b_bounds=(0, 5), terminal_decline_eff=0.08, econ_limit_rate=1, max_life_years=30)


def test_type_curve_decisions():
    with pytest.raises(DecisionRequired):
        TypeCurveDecisions.from_kwargs("lateral_length", None)
    assert TypeCurveDecisions.from_kwargs("none").reference_lateral_ft is None
