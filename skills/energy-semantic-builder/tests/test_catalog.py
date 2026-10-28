"""Catalog validation: the correctness gate catches non-additive and placeholder traps."""

import pytest

from semantic_core import Catalog, load_catalog, validate_catalog


def test_shipped_catalog_is_clean_and_large_enough():
    cat = load_catalog()
    rep = validate_catalog(cat)
    assert rep.ok, rep.errors
    assert not rep.warnings, rep.warnings
    assert len(cat.measures) >= 30
    assert {mv["domain"] for mv in cat.metric_views.values()} >= {
        "upstream", "generation", "grid", "renewables", "emissions", "customer"}


def test_every_measure_has_unit_and_definition():
    for m in load_catalog().measures:
        assert m.get("unit") and m.get("definition"), m["name"]


def _toy(measures: list[dict]) -> Catalog:
    base = load_catalog()
    mv = {"mv_upstream__well_day": base.metric_views["mv_upstream__well_day"]}
    tagged = tuple({**m, "_domain": "upstream", "_file": "toy.yaml",
                    "metric_view": "mv_upstream__well_day", "unit": "x",
                    "definition": "d"} for m in measures)
    return Catalog(base.entities, base.decisions, mv, tagged)


def test_composite_without_measure_is_rejected():
    cat = _toy([{"name": "oil", "type": "atomic", "entity": "well_day", "expr": "SUM(oil_bbl)"},
                {"name": "bad_cut", "type": "composite", "expr": "AVG(water_bbl / oil_bbl)",
                 "depends_on": []}])
    assert any("non-additive" in e for e in validate_catalog(cat).errors)


def test_undeclared_placeholder_is_rejected():
    cat = _toy([{"name": "boe", "type": "atomic", "entity": "well_day",
                 "expr": "SUM(oil_bbl + gas_mcf / {mystery_ratio})"}])
    errors = validate_catalog(cat).errors
    assert any("mystery_ratio" in e for e in errors)


def test_cross_view_measure_reference_is_rejected():
    cat = _toy([{"name": "r", "type": "composite", "expr": "MEASURE(loe_total_usd) / 2",
                 "depends_on": ["loe_total_usd"]}])
    assert any("not defined" in e for e in validate_catalog(cat).errors)


@pytest.mark.parametrize("name", ["water_cut_pct", "boe_per_day", "capacity_factor_pct",
                                  "net_heat_rate_btu_per_kwh", "caidi_min",
                                  "performance_ratio_pct", "avg_revenue_cents_per_kwh"])
def test_rates_are_ratio_of_measures(name):
    m = next(x for x in load_catalog().measures if x["name"] == name)
    assert m["type"] == "composite" and "MEASURE(" in m["expr"]
