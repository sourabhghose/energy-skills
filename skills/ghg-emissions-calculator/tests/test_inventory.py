import pandas as pd
import pytest

from ghg_core import DecisionRequired
from ghg_inventory import build_confirmed_inventory, preview_inventory


def test_missing_decision_raises(activity, decisions):
    with pytest.raises(DecisionRequired, match="gwp_set"):
        build_confirmed_inventory(activity, **{**decisions, "gwp_set": None})
    with pytest.raises(DecisionRequired, match="flare_efficiency_tier"):
        build_confirmed_inventory(activity, **{**decisions, "flare_efficiency_tier": None})


def test_not_applicable_decisions_may_be_none(activity, decisions):
    out = build_confirmed_inventory(activity, **decisions)
    assert out["manifest"]["decisions"]["tank_method"] == "not_applicable"


def test_operational_control_excludes_non_operated(activity, decisions):
    out = build_confirmed_inventory(activity, **decisions)
    assert set(out["inventory"].query("co2e_t > 0").facility_id) == {"F1"}


def test_equity_share_halves_f2(activity, decisions):
    out = build_confirmed_inventory(activity, **{**decisions, "consolidation": "equity_share"})
    f2 = out["inventory"].query("facility_id == 'F2' and gas == 'CH4'")
    assert f2.co2e_t.sum() == pytest.approx(2.0 * 28 * 0.5)


def test_summary_reports_both_scope2_methods(activity, decisions):
    out = build_confirmed_inventory(activity, **{**decisions, "consolidation": "equity_share"})
    s = out["summary"].set_index("metric").tco2e
    assert s["scope2_location"] > 0 and s["scope2_market"] > 0
    assert s["scope1_plus_scope2_market"] == pytest.approx(s["scope1"] + s["scope2_market"])


def test_gwp_choice_changes_ch4(activity, decisions):
    a = build_confirmed_inventory(activity, **{**decisions, "gwp_set": "AR4"})["summary"]
    b = build_confirmed_inventory(activity, **{**decisions, "gwp_set": "AR6"})["summary"]
    assert b.set_index("metric").tco2e["scope1"] > a.set_index("metric").tco2e["scope1"]


def test_manifest_lineage(activity, decisions):
    m = build_confirmed_inventory(activity, **decisions)["manifest"]
    assert "hub25_ng_co2" in m["factors_used"] and "w1a_pneu_high_bleed" in m["unverified_factors_used"]
    assert m["decisions"]["gwp_set"] == "AR5" and m["skill_version"] == "0.1.0"


def test_build_refuses_rows_with_issues(activity, decisions):
    bad = pd.concat([activity, activity.iloc[[0]].assign(unit="m3")], ignore_index=True)
    with pytest.raises(ValueError, match="could not be computed"):
        build_confirmed_inventory(bad, **decisions)


def test_intensity(activity, decisions):
    prod = pd.DataFrame([{"facility_id": "F1", "oil_bbl": 100_000, "gas_mcf": 600_000,
                          "gas_marketed_mcf": 550_000}])
    out = build_confirmed_inventory(activity, prod, **{**decisions, "boe_mcf_per_boe": 6.0})
    row = out["intensity"].iloc[0]
    assert row.kboe == pytest.approx(200.0)
    assert row.methane_intensity_basis == "gas_marketed_mcf"
    assert 0 < row.methane_intensity_pct < 100


def test_preview_is_read_only_and_shows_consequences(activity):
    before = activity.copy()
    p = preview_inventory(activity)
    pd.testing.assert_frame_equal(activity, before)
    assert set(p["consequences"]["gwp_set_gross_tco2e"]) == {"AR4", "AR5", "AR6"}
    assert set(p["consequences"]["flare_ch4_t_by_tier"]) == {"tier1_de98", "tier2_de95", "tier3_de92",
                                                             "legacy_ce98"}
    assert "flare_efficiency_tier" in p["decisions_needed"] and "tank_method" not in p["decisions_needed"]
    assert "nothing built" in p["readout"]
