"""Preview / build on a fixture mapping; metric view YAML shape; decisions."""

import re

import pytest
import yaml

from conftest import DECISIONS
from generate_semantic_layer import (
    build_confirmed_semantic_layer,
    load_mapping,
    preview_semantic_layer,
)
from profile_source import draft_mapping
from semantic_core import DecisionRequired
from semantic_run import split_statements


def _bodies(sql: str) -> list[dict]:
    return [yaml.safe_load(b) for b in re.findall(r"AS \$\$\n(.*?)\$\$;", sql, re.S)]


def test_preview_lists_scope_and_decisions(mapping_path):
    out = preview_semantic_layer(mapping_path)
    assert out["ok"]
    assert out["decisions_needed"] == sorted(DECISIONS)
    built = {k for k, v in out["scope"]["views"].items() if v["built"]}
    assert built == {"mv_upstream__well_day", "mv_generation__unit_period"}
    assert "SKIP  mv_customer__bill" in out["readout"]


def test_unmapped_optional_field_drops_dependent_measure(mapping_path):
    view = preview_semantic_layer(mapping_path)["scope"]["views"]["mv_upstream__well_day"]
    names = {m["name"] for m in view["measures"]}
    assert "uptime_pct" not in names and "water_cut_pct" in names
    assert any(s.startswith("producing_hours_total") for s in view["skipped"])


@pytest.mark.parametrize("missing", sorted(DECISIONS))
def test_build_requires_every_decision(mapping_path, tmp_path, missing):
    decisions = {k: v for k, v in DECISIONS.items() if k != missing}
    with pytest.raises(DecisionRequired) as err:
        build_confirmed_semantic_layer(mapping_path, decisions, tmp_path)
    assert err.value.decision == missing


def test_build_emits_valid_metric_views(mapping_path, tmp_path):
    res = build_confirmed_semantic_layer(mapping_path, DECISIONS, tmp_path)
    sql = res["files"]["03_metric_views.sql"]
    bodies = {b["source"].split(".")[-1]: b for b in _bodies(sql)}
    assert set(bodies) == {"well_day", "unit_period"}
    up = {m["name"]: m["expr"] for m in bodies["well_day"]["measures"]}
    assert "/ 6.0" in up["boe_volume"] and "{" not in up["boe_volume"]
    gen = {m["name"]: m["expr"] for m in bodies["unit_period"]["measures"]}
    assert "capacity_mw" in gen["available_hours_w"]
    assert gen["eaf_pct"].count("MEASURE(") == 3
    assert all(b["version"] == "1.1" for b in bodies.values())
    assert res["manifest"]["decisions"] == DECISIONS
    assert (tmp_path / "plan.md").exists()


def test_silver_view_converts_units_and_enums(mapping_path, tmp_path):
    silver = build_confirmed_semantic_layer(mapping_path, DECISIONS, tmp_path)["files"]["01_silver.sql"]
    assert "gas_m3 * 0.0353147 AS `gas_mcf`" in silver
    assert "WHEN fuel_cd = 'NG' THEN 'natural_gas'" in silver
    assert "CREATE OR REPLACE VIEW `main`.`energy_semantic`.`well_day`" in silver


def test_unweighted_gads_substitutes_one(mapping_path, tmp_path):
    res = build_confirmed_semantic_layer(mapping_path, {**DECISIONS, "gads_weighting": "unweighted"},
                                         tmp_path)
    gen = {m["name"]: m["expr"] for b in _bodies(res["files"]["03_metric_views.sql"])
           for m in b["measures"]}
    assert gen["available_hours_w"] == "SUM(available_hours * 1)"


def test_bad_target_identifier_rejected(tmp_path):
    bad = {"target": {"catalog": "main; DROP", "schema": "x"},
           "entities": {"bill": {"source": "main.a.b", "fields": {"bill_id": "id"}}}}
    with pytest.raises(ValueError, match="Invalid Unity Catalog identifier"):
        build_confirmed_semantic_layer(bad, {}, tmp_path)


def test_extends_merges_adapter():
    merged = load_mapping({"extends": ["adapters/nerc_gads_performance.yaml"],
                           "target": {"catalog": "c", "schema": "s"},
                           "entities": {"bill": {"source": "c.s.bills", "fields": {}}}})
    assert {"unit_period", "bill"} <= set(merged["entities"])


def test_profiler_drafts_with_review_flags():
    text = draft_mapping({"main.raw.prod": ["uwi", "prod_date", "oil_bbl", "gas_vol", "wtr"]},
                         "main", "sem")
    draft = yaml.safe_load(text)
    fields = draft["entities"]["well_day"]["fields"]
    assert fields["well_id"] == "uwi" and fields["gas_mcf"] == "gas_vol"
    assert "# REVIEW: matched by synonym" in text


def test_split_statements_keeps_yaml_bodies(mapping_path, tmp_path):
    files = build_confirmed_semantic_layer(mapping_path, DECISIONS, tmp_path)["files"]
    statements = split_statements(files["03_metric_views.sql"])
    assert len(statements) == 2
    assert all(s.rstrip().endswith("$$") for s in statements)


def test_unmapped_ngl_defaults_to_zero(mapping_path, tmp_path):
    silver = build_confirmed_semantic_layer(mapping_path, DECISIONS, tmp_path)["files"]["01_silver.sql"]
    assert "CAST(0.0 AS DOUBLE) AS `ngl_bbl`" in silver
