import hashlib

import pandas as pd
import pytest

import synth
from gdg_classify import apply_overrides, classify_columns
from gdg_core import (apply_rule, column_plan, complementary_suppression, coordinate_uniqueness,
                      generalize_point, group_stats, hmac_token, risk_summary)
from gdg_decisions import DecisionRequired, make_config
from gdg_run import build_confirmed_guard
from gdg_sql import column_tag_sql, group_stats_sql, internal_view_sql


@pytest.fixture(scope="module")
def usage():
    return synth.monthly_usage(synth.customers())


def test_classification_finds_ceii_pii_and_geo(usage):
    c = {k: v["class"] for k, v in classify_columns(usage).items()}
    assert c["customer_name"] == c["service_address"] == c["email"] == "PII_DIRECT"
    assert c["account_number"] == c["premise_id"] == "PII_ID"
    assert c["feeder_id"] == c["substation"] == "CEII_TOPOLOGY"
    assert c["relay_pickup_amps"] == "CEII_SETTINGS"
    assert c["lat"] == c["lon"] == "GEO_PRECISE"
    assert c["kwh"] == "CONSUMPTION" and c["zip"] == "QUASI" and c["read_month"] == "TIME"


def test_value_rules_catch_misnamed_columns():
    df = pd.DataFrame({"notes": ["a@b.com"] * 5, "col7": ["10.2.3.4"] * 5,
                       "premise_type": ["house"] * 5})
    c = {k: v["class"] for k, v in classify_columns(df).items()}
    assert c == {"notes": "PII_DIRECT", "col7": "CEII_SETTINGS", "premise_type": "QUASI"}


def test_overrides_are_applied_without_mutation(usage):
    classes = classify_columns(usage)
    out = apply_overrides(classes, {"zip": "OTHER"})
    assert out["zip"]["class"] == "OTHER" and classes["zip"]["class"] == "QUASI"
    with pytest.raises(ValueError):
        apply_overrides(classes, {"zip": "SECRET"})


def test_fifteen_fifteen_suppresses_small_and_dominated_cells(usage):
    stats = apply_rule(group_stats(usage, ["zip", "read_month"], "premise_id", "kwh"),
                       "15_15", 15, 15.0)
    by_zip = stats.groupby("zip")["passes_rule"].all()
    assert not by_zip["60604"]          # ~12 customers < 15
    assert not by_zip["60603"]          # one industrial customer dominates the cell
    assert by_zip["60601"] and by_zip["60602"]
    k_only = apply_rule(group_stats(usage, ["zip"], "premise_id", "kwh"), "k_only", 15, 15.0)
    assert k_only.set_index("zip").loc["60603", "passes_rule"]   # k-only misses dominance


def test_complementary_suppression_blocks_subtraction():
    cells = pd.DataFrame({"period": ["m1"] * 3, "zip": ["a", "b", "c"], "total": [100.0, 50, 10],
                          "passes_rule": [True, True, False], "suppression_reason": ["", "", "k"]})
    out = complementary_suppression(cells, ["period"])
    assert out.set_index("zip").loc["b", "complementary"]
    assert out["passes_rule"].sum() == 1


def test_risk_summary(usage):
    stats = apply_rule(group_stats(usage, ["zip"], "premise_id", "kwh"), "15_15", 15, 15.0)
    s = risk_summary(stats)
    assert s["cells_suppressed"] == 2 and s["pct_value_suppressed"] > 0


def test_geo_generalization_and_uniqueness(usage):
    cells = generalize_point(usage["lat"], usage["lon"], "round", 2)
    assert cells.nunique() < usage["lat"].nunique()
    assert coordinate_uniqueness(usage["lat"].head(400), usage["lon"].head(400))["unique_points_pct"] > 90


def test_h3_when_available(usage):
    pytest.importorskip("h3")
    cells = generalize_point(usage["lat"].head(10), usage["lon"].head(10), "h3", 7)
    assert cells.nunique() <= 3


def test_hmac_token_is_salted_and_stable():
    a = hmac_token("9000000001", b"salt-1")
    assert a == hmac_token("9000000001", b"salt-1") != hmac_token("9000000001", b"salt-2")
    assert a != hashlib.sha256(b"9000000001").hexdigest()[:16]
    assert hmac_token(None, b"s") is None


def test_plan_blocks_ceii_grouping_for_public(usage):
    classes = classify_columns(usage)
    with pytest.raises(ValueError, match="topology"):
        column_plan(classes, "public", ("feeder_id",))
    with pytest.raises(ValueError, match="Cannot group"):
        column_plan(classes, "external_partner", ("account_number",))
    plan = column_plan(classes, "external_partner", ("feeder_id",))
    assert plan["feeder_id"]["action"] == "group_by"
    assert plan["relay_pickup_amps"]["action"] == "drop"
    internal = column_plan(classes, "internal_need_to_know")
    assert internal["account_number"]["action"] == "tokenize"
    assert internal["relay_pickup_amps"]["action"] == "mask_privileged"


def test_decisions_depend_on_audience():
    with pytest.raises(DecisionRequired, match="release_audience"):
        make_config(has_id_columns=True)
    with pytest.raises(DecisionRequired, match="privileged_group"):
        make_config(has_id_columns=True, release_audience="internal_need_to_know")
    with pytest.raises(DecisionRequired, match="tokenization_secret"):
        make_config(has_id_columns=True, release_audience="internal_need_to_know",
                    privileged_group="grid_ceii_readers")
    with pytest.raises(DecisionRequired, match="aggregation_rule"):
        make_config(has_id_columns=True, release_audience="public")
    with pytest.raises(DecisionRequired, match="15/15 fixes"):
        make_config(has_id_columns=True, release_audience="public", aggregation_rule="15_15",
                    k_min=5, group_by=("zip",), time_grain="month")
    with pytest.raises(DecisionRequired, match="geo_method"):
        make_config(has_id_columns=True, release_audience="public", aggregation_rule="15_15",
                    group_by=("geo",), time_grain="month")
    cfg = make_config(has_id_columns=True, release_audience="public", aggregation_rule="15_15",
                      group_by=["zip"], time_grain="month")
    assert cfg.k_min == 15 and cfg.aggregate_only


def test_internal_view_sql_masks_tokenizes_and_quotes(usage):
    plan = column_plan(classify_columns(usage), "internal_need_to_know")
    sql = internal_view_sql("main.ami.usage", "main.ami.usage_guarded", plan, "grid_ceii_readers",
                            "grid-scope/token-salt", ("lat", "lon", "h3", 8))
    assert "is_account_group_member('grid_ceii_readers')" in sql
    assert "secret('grid-scope', 'token-salt')" in sql
    assert "h3_longlatash3(`lon`, `lat`, 8)" in sql      # longitude first
    assert "CASE WHEN is_account_group_member('grid_ceii_readers') THEN `relay_pickup_amps`" in sql
    with pytest.raises(ValueError):
        internal_view_sql("main.ami.usage; DROP", "a.b.c", plan, "g", "s/k")


def test_group_stats_sql_shape():
    sql = group_stats_sql("main.ami.usage", ["zip", "geo"], "premise_id", "kwh", "read_month",
                          "month", ("lat", "lon", "round", 2))
    assert "date_trunc('month', `read_month`) AS `period`" in sql
    assert "count(*) AS `n_customers`" in sql and "GROUP BY `zip`, `geo_cell`, `period`" in sql
    assert column_tag_sql("main.ami.usage", {"kwh": {"class": "CONSUMPTION", "action": "keep"}})


def test_build_refuses_without_audience(monkeypatch, usage):
    import gdg_run
    monkeypatch.setattr(gdg_run, "_sample", lambda *a, **k: usage.head(100))
    with pytest.raises(DecisionRequired, match="release_audience"):
        build_confirmed_guard("main.ami.usage", "main.share.out")


def test_phone_needs_separators():
    df = pd.DataFrame({"contact": ["(312) 555-0100", "312-555-0101"] * 3,
                       "acct_no": ["9000000001", "9000000002"] * 3})
    c = {k: v["class"] for k, v in classify_columns(df).items()}
    assert c == {"contact": "PII_DIRECT", "acct_no": "PII_ID"}


def test_aggregate_build_publishes_only_passing_cells_without_max_customer(monkeypatch, usage):
    import gdg_run

    written = {}
    monkeypatch.setattr(gdg_run, "_sample", lambda *a, **k: usage.head(200))
    monkeypatch.setattr(gdg_run, "_stats", lambda table, grouping, cust, val, *a: group_stats(
        usage.rename(columns={"read_month": "period"}), list(grouping) + ["period"], cust, val))
    monkeypatch.setattr(gdg_run, "write_table",
                        lambda df, fqn, **k: written.__setitem__(fqn, df) or fqn)
    monkeypatch.setattr(gdg_run, "write_manifest", lambda m, fqn: written.__setitem__(fqn, m))
    text = build_confirmed_guard("main.ami.usage", "main.share.by_zip", release_audience="public",
                                 aggregation_rule="15_15", group_by=["zip"], time_grain="month",
                                 customer_col="premise_id", value_col="kwh",
                                 time_col="read_month")
    out = written["main.share.by_zip"]
    assert set(out["zip"]) == {"60601", "60602"}
    assert "max_customer_value" not in out.columns and "total_kwh" in out.columns
    assert (out["n_customers"] >= 15).all()
    assert written["main.share.by_zip_manifest"]["decisions"]["k_min"] == 15
    assert "never published" in text
