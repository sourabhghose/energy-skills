# Adapted from databricks-industry-solutions/vital-skills (skills/presentation-builder/tests/test_presentation_builder.py); modified for the energy industry.
"""Unit tests for the presentation builder — pure, offline, sub-second (no warehouse).

Covers the invariants that make a generated deck trustworthy:
  1. The FROZEN framework is emitted verbatim (nav runtime, protocol marker, print CSS),
     so navigation and "Save as PDF" always work.
  2. The layout renderers are deterministic and SAFE: all content is HTML-escaped, the tiny
     inline markup resolves, bars auto-scale, and an unknown layout fails loud.
  3. The grounding reader shapes figures as the renderers expect (ground.py — the pure part).

  4. Grounding validates identifiers, requires units, passes filters as parameters, can suppress
     small groups, and turns a facts ledger into tiles.

Customer-level / CEII de-identification is delegated to grid-data-guard and not tested here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import build_deck as bd  # noqa: E402
import deck_framework as fw  # noqa: E402
import ground as g  # noqa: E402
import layouts as L  # noqa: E402


# --- framework is emitted verbatim -------------------------------------------

def _mini():
    return {
        "title": "T", "footer_left": "F",
        "slides": [
            {"type": "cover", "title": "Hello", "theme": "dark"},
            {"type": "statement", "statement": "Thesis."},
        ],
    }


def test_doc_is_self_contained_and_well_formed():
    html = bd.render_html(_mini())
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert 'data-od-deck-protocol="1"' in html
    # frozen framework strings present verbatim
    assert fw.NAV_JS.strip() in html
    assert fw.NAV_MARKUP.strip() in html
    assert "od:deck-ready" in html and "OD_DECK_PROTOCOL_VERSION = 1" in html
    assert "@media print" in html  # Save-as-PDF path
    assert ".deck-stage" in html and "1920px" in html


def test_navigation_chrome_is_visible():
    # Standalone decks must surface the prev/counter/next pill + keyboard hint (the frozen
    # framework hides them for host-embedded use; the editable layer re-shows them).
    html = bd.render_html(_mini())
    assert ".deck-counter { display: flex; }" in html
    assert ".deck-hint { display: block; }" in html
    assert 'id="deck-prev"' in html and 'id="deck-next"' in html


def test_one_section_per_slide():
    html = bd.render_html(_mini())
    # data-screen-label only appears on real slides (not in the framework comment).
    assert html.count("data-screen-label=") == 2


def test_speaker_notes_in_aside_and_json():
    spec = _mini()
    spec["slides"][0]["notes"] = "Say this out loud."
    html = bd.render_html(spec)
    assert '<aside class="speaker-notes">Say this out loud.</aside>' in html
    notes_json = html.split('id="speaker-notes">', 1)[1].split("</script>", 1)[0]
    assert json.loads(notes_json) == ["Say this out loud.", ""]


# --- renderers are safe + deterministic --------------------------------------

def test_content_is_html_escaped():
    html = bd.render_html({"slides": [
        {"type": "statement", "statement": "<script>alert(1)</script> & \"x\""}]})
    assert "<script>alert(1)" not in html.split('id="speaker-notes"')[0]
    assert "&lt;script&gt;alert(1)" in html


def test_inline_markup():
    assert L._inline("a [[b]] c") == 'a <span class="hl">b</span> c'
    assert L._inline("a **b** c") == "a <strong>b</strong> c"
    assert L._inline("<x>") == "&lt;x&gt;"


def test_bar_chart_autoscales_first_bar_accent():
    html = bd.render_html({"slides": [{"type": "bar_chart", "title": "t", "chart": {
        "heading": "h", "bars": [{"label": "a", "value": 200}, {"label": "b", "value": 50}]}}]})
    assert "width:100.0%" in html   # max value -> full width
    assert "width:25.0%" in html    # 50/200
    assert "200" in html and "50" in html


def test_cards_grid_class_clamped():
    html = bd.render_html({"slides": [{"type": "cards", "title": "t", "cards": [
        {"heading": "a"}, {"heading": "b"}, {"heading": "c", "featured": True}]}]})
    assert 'class="cards n3"' in html
    assert "card featured" in html


def test_unknown_layout_fails_loud():
    with pytest.raises(ValueError):
        bd.render_html({"slides": [{"type": "pie_of_pie"}]})


def test_empty_deck_fails_loud():
    with pytest.raises(ValueError):
        bd.render_html({"slides": []})


def test_bad_theme_fails_loud():
    with pytest.raises(ValueError):
        bd.render_html({"slides": [{"type": "statement", "statement": "x", "theme": "neon"}]})


def test_accent_override_rejects_injection():
    with pytest.raises(ValueError):
        bd.render_html({"accent": "red; } body{display:none", "slides": [
            {"type": "statement", "statement": "x"}]})
    ok = bd.render_html({"accent": "#00a972", "slides": [{"type": "statement", "statement": "x"}]})
    assert "--accent: #00a972" in ok


def test_build_deck_writes_file(tmp_path):
    out = tmp_path / "deck.html"
    summ = bd.build_deck(_mini(), str(out))
    assert out.exists() and summ["slides"] == 2 and summ["bytes"] > 1000


# --- grounding (pure parts of ground.py, fake SQL runner) ---------------------

class FakeQ:
    """Records statements and parameters; returns canned rows."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, stmt, params=None):
        self.calls = [*self.calls, (stmt, params)]
        return self.rows


def test_column_distribution_shapes_bars():
    q = FakeQ([["North", 100, 100], ["South", 30, 30], [None, 3, 3]])
    out = g.column_distribution("c.s.t", "region", q=q)
    assert [b["label"] for b in out["bars"]] == ["North", "South", "(null)"]
    assert [b["value"] for b in out["bars"]] == [100, 30, 3]
    assert out["source"].startswith("Source: c.s.t")
    assert "`c`.`s`.`t`" in q.calls[0][0] and "`region`" in q.calls[0][0]


def test_column_distribution_sum_requires_unit_and_suppresses():
    with pytest.raises(ValueError, match="unit"):
        g.column_distribution("c.s.t", "feeder", value_col="customer_minutes", unit="", q=FakeQ([]))
    q = FakeQ([["F1", 9000.0, 400], ["F2", 1200.0, 12], ["F3", 50.0, 3], ["F4", 20.0, 2]])
    out = g.column_distribution("c.s.t", "feeder", value_col="customer_minutes",
                                unit="customer-min", suppress_below=10, q=q)
    assert [b["label"] for b in out["bars"]] == ["F1", "F2", "(suppressed)"]
    assert out["bars"][-1]["value"] == 70
    assert "suppressed" in out["source"] and "(customer-min)" in out["source"]


@pytest.mark.parametrize("table", ["t", "c.s", "c.s.t; DROP TABLE x", "c.s.t-1"])
def test_bad_table_names_rejected(table):
    with pytest.raises(ValueError):
        g.dataset_summary(table, q=FakeQ([[1, 1]]))


def test_bad_column_rejected():
    with pytest.raises(ValueError):
        g.numeric_summary("c.s.t", "x) FROM y --", unit="MW", q=FakeQ([[1, 1, 1, 1, 1]]))


def test_numeric_summary_requires_unit_and_formats():
    with pytest.raises(ValueError, match="unit"):
        g.numeric_summary("c.s.t", "saidi_min", unit=None, q=FakeQ([]))
    out = g.numeric_summary("c.s.t", "load_mw", unit="MW", q=FakeQ([[8760, 410.5, 1912.25, 980.123, 955.0]]))
    assert out["count"] == 8760 and out["max"] == 1912.25
    assert out["display"]["max"] == "1,912 MW" and out["display"]["min"] == "410 MW"
    assert out["source"].endswith("(MW)")


def test_dataset_summary_with_and_without_id():
    assert g.dataset_summary("c.s.t", id_col="meter_id", q=FakeQ([[96000, 1000]]))["n_entities"] == 1000
    assert g.dataset_summary("c.s.t", q=FakeQ([[5, None]]))["n_entities"] is None


def test_filtered_total_uses_parameters():
    q = FakeQ([[1234.5, 10]])
    out = g.filtered_total("c.s.t", "co2e_t", unit="tCO2e", where={"scope": "1", "year": 2025}, q=q)
    stmt, params = q.calls[0]
    assert "`scope` = :p0 AND `year` = :p1" in stmt and "2025" not in stmt
    assert params == {"p0": "1", "p1": 2025}
    assert out["display"] == "1,234 tCO2e" and "scope=1" in out["source"]


def test_time_range():
    out = g.time_range("c.s.t", "interval_end_utc", q=FakeQ([["2025-01-01 00:15:00", "2026-01-01 00:00:00"]]))
    assert out["start"].startswith("2025-01-01")


@pytest.mark.parametrize("value, unit, expected", [
    (132.44, "min", "132 min"), (1.0812, "-", "1.08"), (12.345, "bbl/d", "12.3 bbl/d"),
    (412345, "-", "412,345"), (None, "MW", "n/a"),
])
def test_format_value(value, unit, expected):
    assert g.format_value(value, unit) == expected


def test_tiles_from_facts(tmp_path):
    records = [{"fact_id": "y2025_saidi", "value": 109.8, "unit": "min", "source": "main.rel.idx"},
               {"fact_id": "eur_total", "value": 1354.7, "unit": "Mbbl", "source": "derived: sum", "decimals": 1}]
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    tiles = g.tiles_from_facts(path, ["y2025_saidi", "eur_total"], labels={"y2025_saidi": "SAIDI 2025"})
    assert tiles[0] == {"value": "110 min", "label": "SAIDI 2025", "caption": "Source: main.rel.idx"}
    assert tiles[1]["value"] == "1,354.7 Mbbl"
    with pytest.raises(KeyError):
        g.tiles_from_facts(records, ["nope"])


def test_energy_deck_end_to_end(tmp_path):
    tiles = g.tiles_from_facts([{"fact_id": "saidi", "value": 109.8, "unit": "min", "source": "t"}], ["saidi"])
    bars = g.column_distribution("c.s.t", "cause", value_col="customer_minutes", unit="customer-min",
                                 q=FakeQ([["Vegetation", 5000.0, 50], ["Equipment", 3000.0, 40]]))
    spec = {"title": "Reliability 2025", "footer_left": "Databricks · Energy", "slides": [
        {"type": "metrics", "title": "Headline", "tiles": tiles},
        {"type": "bar_chart", "title": "Causes", "chart": {"heading": "Customer-minutes by cause",
         "unit": bars["unit"], "bars": bars["bars"]}, "notes": bars["source"]}]}
    out = bd.build_deck(spec, str(tmp_path / "deck.html"))
    html = (tmp_path / "deck.html").read_text(encoding="utf-8")
    assert out["slides"] == 2 and "110 min" in html and "Vegetation" in html
