import numpy as np
import pandas as pd
import pytest

from iso_analytics import check_components, da_rt_spread, hourly, normalized_congestion, settle
from iso_core import DecisionRequired, from_utc
from iso_entry import build_confirmed_price_analysis, build_confirmed_settlement, preview_market_data

BASE = dict(hourly_aggregation="time_weighted", peak_definition="5x16", peak_timezone="America/New_York",
            price_floor=-150.0, price_cap=3700.0)


def test_pjm_components_reconcile(pjm):
    out = check_components(from_utc(pjm, "timestamp", "interval_beginning", 5), "PJM")
    assert not out.component_mismatch.any()


def test_nyiso_sign_convention():
    df = pd.DataFrame({"lmp": [34.0], "energy": [30.0], "loss": [1.0], "congestion": [-3.0]})
    assert not check_components(df, "NYISO").component_mismatch.any()
    assert check_components(df, "PJM").component_mismatch.any()
    assert normalized_congestion(df, "NYISO").iloc[0] == 3.0


def test_time_weighted_hourly_with_missing_interval(pjm):
    p = from_utc(pjm, "timestamp", "interval_beginning", 5)
    p = p.drop(index=p.index[(p.node == "NODE_A")][:1])
    h = hourly(p, "time_weighted")
    first = h[(h.node == "NODE_A")].iloc[0]
    assert first.covered_minutes == 55 and first.incomplete


def test_energy_weighted_needs_mwh(pjm):
    with pytest.raises(ValueError, match="MWh"):
        hourly(from_utc(pjm, "timestamp", "interval_beginning", 5), "energy_weighted")


def test_build_requires_decisions_and_real_nodes(pjm):
    kw = dict(iso="PJM", market="RT", time_format="utc_column", source_timestamp_convention="interval_beginning")
    with pytest.raises(DecisionRequired, match="nodes"):
        build_confirmed_price_analysis(pjm, **kw, **BASE)
    with pytest.raises(ValueError, match="no substitution"):
        build_confirmed_price_analysis(pjm, nodes=["NODE_B"], **kw, **BASE)
    with pytest.raises(DecisionRequired, match="peak_definition"):
        build_confirmed_price_analysis(pjm, nodes=["NODE_A"], **kw, **{**BASE, "peak_definition": None})
    with pytest.raises(DecisionRequired, match="source_timestamp_convention"):
        build_confirmed_price_analysis(pjm, nodes=["NODE_A"], **{**kw, "source_timestamp_convention": None}, **BASE)
    with pytest.raises(DecisionRequired, match="price_cap"):
        build_confirmed_price_analysis(pjm, nodes=["NODE_A"], **kw, **{**BASE, "price_cap": None})


def test_build_basis_and_manifest(pjm):
    out = build_confirmed_price_analysis(pjm, iso="PJM", market="RT", time_format="utc_column",
                                         source_timestamp_convention="interval_beginning", nodes=["NODE_A"],
                                         hub="WESTERN HUB", **BASE)
    assert out["basis"]["basis"].mean() == pytest.approx(8.0, abs=0.5)
    assert out["manifest"]["decisions"]["nodes"] == ["NODE_A"]
    assert out["manifest"]["convention_registry_status"] == "verify_before_use"


def test_negative_prices_flagged_not_dropped(pjm):
    neg = pjm.assign(lmp=pjm.lmp - 60, energy=pjm.energy - 60)
    out = build_confirmed_price_analysis(neg, iso="PJM", market="RT", time_format="utc_column",
                                         source_timestamp_convention="interval_beginning", nodes=["NODE_A"], **BASE)
    assert out["prices"].flag_negative.any() and len(out["prices"]) == (neg.node == "NODE_A").sum()


def test_ercot_build_from_hour_ending(ercot):
    out = build_confirmed_price_analysis(ercot, iso="ERCOT", market="RT", time_format="hour_ending",
                                         repeated_col="dst_flag", interval_col="interval", nodes=["RN_WIND1"],
                                         hub="HB_NORTH", **{**BASE, "peak_timezone": "America/Chicago",
                                                            "price_cap": 5000.0, "price_floor": -251.0})
    assert len(out["hourly"][out["hourly"].node == "RN_WIND1"]) == 73  # 24 + 25 + 24 hours
    assert (out["basis"].basis == 5.0).all()


def _two_settlement_inputs():
    hour = pd.Timestamp("2025-07-01T16:00:00Z")
    da = pd.DataFrame({"node": "N", "interval_start_utc": [hour], "interval_minutes": 60, "lmp": [50.0]})
    rt_ts = pd.date_range(hour, periods=12, freq="5min")
    rt = pd.DataFrame({"node": "N", "interval_start_utc": rt_ts, "interval_minutes": 5,
                       "lmp": np.r_[np.full(6, 40.0), np.full(6, 100.0)]})
    meter = pd.DataFrame({"node": "N", "interval_start_utc": rt_ts, "mwh": np.r_[np.full(6, 10 / 12), np.full(6, 0.0)]})
    awards = pd.DataFrame({"node": "N", "interval_start_utc": [hour], "mw": [10.0]})
    return da, rt, meter, awards


def test_two_settlement_hand_calc():
    da, rt, meter, awards = _two_settlement_inputs()
    out = build_confirmed_settlement(rt_meter=meter, settlement="two_settlement", rt_prices=rt, da_prices=da,
                                     da_awards=awards)
    t = out["totals"].iloc[0]
    assert t.da_revenue == pytest.approx(500.0)
    # first half: delivered = award, no deviation; second half short 10/12 MWh x 6 at $100
    assert t.rt_revenue == pytest.approx(-6 * (10 / 12) * 100.0)


def test_rt_only_battery_charging_costs_money():
    _, rt, meter, _ = _two_settlement_inputs()
    batt = meter.assign(mwh=np.r_[np.full(6, -1.0), np.full(6, 1.0)])
    out = build_confirmed_settlement(rt_meter=batt, settlement="rt_only", rt_prices=rt)
    assert out["totals"].revenue.iloc[0] == pytest.approx(6 * (100 - 40))


def test_settlement_decision_required():
    _, rt, meter, _ = _two_settlement_inputs()
    with pytest.raises(DecisionRequired):
        build_confirmed_settlement(rt_meter=meter, rt_prices=rt)


def test_da_rt_spread():
    hour = pd.Timestamp("2025-07-01T16:00:00Z")
    da = pd.DataFrame({"node": ["N"], "hour_start_utc": [hour], "lmp": [50.0]})
    rt = pd.DataFrame({"node": ["N"], "hour_start_utc": [hour], "lmp": [70.0], "incomplete": [False]})
    assert da_rt_spread(da, rt).da_minus_rt.iloc[0] == -20.0


def test_preview_read_only(ercot, pjm):
    before = pjm.copy()
    p = preview_market_data(pjm, iso="PJM", market="RT", time_format="utc_column", nodes=["NODE_A", "NODE_Z"])
    pd.testing.assert_frame_equal(pjm, before)
    assert "NODE_Z" in p["grounding"]["missing"] and "nothing built" in p["readout"]
    assert set(p["consequences"]["peak_block_avg_lmp"]) == {"5x16", "2x16", "7x8", "wrap", "7x24"}
    e = preview_market_data(ercot, iso="ERCOT", market="RT", time_format="hour_ending",
                            repeated_col="dst_flag", interval_col="interval")
    assert "2025-11-02" in e["readout"]
