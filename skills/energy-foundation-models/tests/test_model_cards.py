"""Model cards, catalog and SKILL.md stay consistent (offline)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from geo_contract import validate_chip_manifest
from tsfm_catalog import CATALOG

SKILL_DIR = Path(__file__).resolve().parent.parent
REFS = SKILL_DIR / "references"
MODELS = REFS / "models"
SKILL_MD = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
INDEX_MD = (MODELS / "index.md").read_text(encoding="utf-8")
CARDS = sorted(p for p in MODELS.glob("*.md") if p.name != "index.md")
TEMPLATE_SECTIONS = re.findall(r"^## (.+)$", (REFS / "model-template.md").read_text(), re.MULTILINE)
IDENTITY_FIELDS = ("HF repo", "HF revision", "Code repo", "Weights license", "Commercial use", "Reviewed")


def _field(text: str, name: str) -> str:
    m = re.search(rf"^- {re.escape(name)}: (.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def test_index_lists_every_card():
    linked = sorted(re.findall(r"\]\(([a-z0-9-]+\.md)\)", INDEX_MD))
    assert linked == sorted(p.name for p in CARDS)


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_card_has_template_sections_and_identity(card: Path):
    text = card.read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", text, re.MULTILINE)
    assert not [s for s in TEMPLATE_SECTIONS if s not in sections]
    for name in IDENTITY_FIELDS:
        assert _field(text, name), f"{card.name}: missing '{name}'"
    assert re.fullmatch(r"[0-9a-f]{40}", _field(text, "HF revision")), card.name
    assert re.match(r"\d{4}-\d{2}-\d{2}", _field(text, "Reviewed")), card.name


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.stem)
def test_non_commercial_licences_are_flagged(card: Path):
    text = card.read_text(encoding="utf-8")
    nc = "-nc-" in _field(text, "Weights license").lower() or "non-commercial" in _field(text, "Weights license").lower()
    assert nc == _field(text, "Commercial use").upper().startswith("NO"), card.name


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_catalog_matches_card(key: str):
    entry = CATALOG[key]
    card = SKILL_DIR / entry.card
    assert card.is_file(), entry.card
    text = card.read_text(encoding="utf-8")
    assert _field(text, "HF repo") == entry.hf_repo
    assert _field(text, "HF revision") == entry.hf_revision
    assert _field(text, "Weights license") == entry.weights_license
    assert entry.commercial_use == (not _field(text, "Commercial use").upper().startswith("NO"))


def test_skill_md_pointers_resolve():
    for rel in set(re.findall(r"`((?:references|scripts)/[^`<>*]+\.(?:md|py))`", SKILL_MD)):
        assert (SKILL_DIR / rel).is_file(), f"SKILL.md points to missing {rel}"


def _chip(**kw) -> dict:
    row = {"chip_uri": "/Volumes/main/geo/chips/tile_001.tif", "bands": "B02,B03,B04,B05,B06,B07",
           "height": 224, "width": 224, "n_timesteps": 2, "units": "reflectance_x10000",
           "acquired_dates": "2026-07-01,2026-07-17", "crs": "EPSG:32614"}
    return {**row, **kw}


def test_chip_manifest_accepts_l30_and_s30_codes():
    df = pd.DataFrame([_chip(), _chip(bands="B02,B03,B04,B8A,B11,B12")])
    assert validate_chip_manifest(df, "300M-TL") == []


@pytest.mark.parametrize("override,needle", [
    ({"bands": "B02,B03,B04,B05,B06,B07".replace("B05", "B08")}, "band order"),
    ({"bands": "B04,B03,B02,B05,B06,B07"}, "band order"),
    ({"height": 512}, "expected 224x224"),
    ({"units": "dn"}, "units"),
    ({"acquired_dates": "2026-07-17,2026-07-01"}, "chronological"),
    ({"chip_uri": "s3://bucket/x.tif"}, "/Volumes"),
])
def test_chip_manifest_problems(override, needle):
    problems = validate_chip_manifest(pd.DataFrame([_chip(**override)]), "300M-TL")
    assert any(needle in p for p in problems), problems
