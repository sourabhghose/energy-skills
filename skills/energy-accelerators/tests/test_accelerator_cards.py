"""Consistency checks for the energy-accelerators skill references (offline).

The skill is instructions only, so the tests guard what an agent relies on: every index
row has a card and vice versa, every card has the template sections and identity fields
with a real https URL, repo cards record a commit, every card is routed from SKILL.md,
and Energy Skill names cited in cards exist in the canonical skill list.

Run: uv run --isolated --with pytest python -m pytest -q skills/energy-accelerators/tests
"""

# Adapted from databricks-industry-solutions/vital-skills (skills/accelerators/tests/test_references.py); modified for the energy industry.

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
REFS = SKILL_DIR / "references"
ACCEL_DIR = REFS / "accelerators"
SKILL_MD = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
INDEX_MD = (ACCEL_DIR / "index.md").read_text(encoding="utf-8")

CANONICAL_SKILLS = {
    "ami-interval-analytics", "reliability-metrics", "load-forecaster", "grid-data-guard",
    "wildfire-asset-risk", "decline-curve-analysis", "well-log-ingest", "drilling-report-npt",
    "osdu-ppdm-mapper", "equipment-pdm", "wind-solar-performance", "iso-market-data",
    "ghg-emissions-calculator", "energy-semantic-builder", "energy-foundation-models",
    "unit-guard", "energy-accelerators", "skill-eval", "energy-report-writer", "presentation-builder",
}
REQUIRED_FIELDS = ("Name", "Kind", "URL", "Install doc", "Maintainers", "Licence", "Last updated",
                   "Maturity", "Reviewed")
KINDS = {"accelerator", "library", "partner-solution", "vendor-integration"}
MATURITY = re.compile(r"^(maintained|reference-only|stale \(>18 months\)|deprecated)$")


def h2_sections(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, re.MULTILINE)


def field(text: str, name: str) -> str:
    m = re.search(rf"^- {re.escape(name)}: (.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


TEMPLATE_SECTIONS = h2_sections((REFS / "accelerator-template.md").read_text(encoding="utf-8"))
CARDS = sorted(p for p in ACCEL_DIR.glob("*.md") if p.name != "index.md")
INDEX_LINKS = re.findall(r"\]\(([a-z0-9-]+\.md)\)", INDEX_MD)


def test_template_has_sections():
    assert "Identity" in TEMPLATE_SECTIONS and len(TEMPLATE_SECTIONS) >= 7


def test_index_and_files_match():
    assert sorted(INDEX_LINKS) == sorted(p.name for p in CARDS)


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_card_has_template_sections(card: Path):
    missing = [s for s in TEMPLATE_SECTIONS if s not in h2_sections(card.read_text(encoding="utf-8"))]
    assert not missing, f"{card.name} missing sections: {missing}"


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_card_identity_fields(card: Path):
    text = card.read_text(encoding="utf-8")
    empty = [f for f in REQUIRED_FIELDS if not field(text, f)]
    assert not empty, f"{card.name} empty fields: {empty}"
    assert field(text, "URL").startswith("https://"), card.name
    assert field(text, "Kind") in KINDS, card.name
    assert MATURITY.match(field(text, "Maturity")), card.name
    assert re.match(r"\d{4}-\d{2}-\d{2}", field(text, "Last updated")), card.name


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_repo_cards_record_commit(card: Path):
    text = card.read_text(encoding="utf-8")
    reviewed = field(text, "Reviewed")
    if field(text, "URL").startswith("https://github.com/"):
        assert re.match(r"\d{4}-\d{2}-\d{2} against commit [0-9a-f]{7,40}$", reviewed), card.name
    else:
        assert re.match(r"\d{4}-\d{2}-\d{2} \(page checked", reviewed), card.name


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_card_is_routed_from_skill(card: Path):
    assert f"references/accelerators/{card.name}" in SKILL_MD


def section(text: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_cited_skills_exist(card: Path):
    """Skill names in 'Pair with Energy Skills' must be canonical skills or other cards."""
    text = card.read_text(encoding="utf-8")
    cited = set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", section(text, "Pair with Energy Skills")))
    platform = {"databricks-zerobus-ingest"}  # Databricks platform skill, not an Energy Skill
    unknown = cited - CANONICAL_SKILLS - {p.stem for p in CARDS} - platform
    assert cited, f"{card.name} pairs with no Energy Skill"
    assert not unknown, f"{card.name} cites unknown skills: {sorted(unknown)}"


def test_stale_flag_matches_last_updated():
    for card in CARDS:
        text = card.read_text(encoding="utf-8")
        year, month = map(int, field(text, "Last updated").split("-")[:2])
        months_old = (2026 - year) * 12 + (10 - month)
        if months_old > 18:
            assert field(text, "Maturity").startswith("stale"), card.name


def test_skill_file_pointers_resolve():
    for rel in set(re.findall(r"`(references/[^`]+\.md)`", SKILL_MD)):
        if "<" in rel:
            continue
        assert (SKILL_DIR / rel).is_file(), f"SKILL.md points to missing {rel}"


def test_no_placeholders_left():
    for card in CARDS:
        assert "<" not in field(card.read_text(encoding="utf-8"), "URL"), card.name
