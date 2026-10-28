"""Task specs, tasks.json and the dataset registry must agree, and every domain skill must have a covered task."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

import taskset
from generators import REGISTRY
from rubric import parse_rubric_levels

SPECS = taskset.all_specs()
DOMAIN_SKILLS = [
    "ami-interval-analytics", "reliability-metrics", "load-forecaster", "grid-data-guard", "wildfire-asset-risk",
    "decline-curve-analysis", "well-log-ingest", "drilling-report-npt", "osdu-ppdm-mapper", "equipment-pdm",
    "wind-solar-performance", "iso-market-data", "ghg-emissions-calculator", "energy-semantic-builder", "unit-guard",
]


@pytest.mark.parametrize("task_id", sorted(SPECS))
def test_spec_is_valid(task_id):
    assert taskset.validate_spec(task_id, SPECS[task_id], REGISTRY) == []


def test_tasks_json_matches_specs():
    rows = {t["task_id"]: t for t in taskset.load()["tasks"]}
    assert set(rows) == set(SPECS)
    for task_id, row in rows.items():
        assert row["tier"] == SPECS[task_id]["task"]["tier"]
        assert row["coverage"] in taskset.COVERAGE


def test_counts_by_tier_and_coverage():
    tasks = taskset.load()["tasks"]
    planted = [t for t in tasks if t["tier"] == "P"]
    assert sum(t["coverage"] == "covered" for t in planted) >= 24
    assert sum(t["coverage"] == "control" for t in planted) >= 8
    assert sum(t["tier"] == "R" for t in tasks) >= 8


@pytest.mark.parametrize("skill", DOMAIN_SKILLS)
def test_every_domain_skill_has_a_planted_task(skill):
    covered = [t for t in taskset.load()["tasks"] if t["tier"] == "P" and skill in t["energy_skills"]]
    assert covered, f"no tier-P task covers {skill}"


def test_controls_name_no_skills():
    for spec in SPECS.values():
        if spec["task"]["domain"] == "Control":
            assert spec["task"]["intended_skills"] == []


def test_tier_r_datasets_are_registered_with_license():
    registry = taskset.datasets()
    for spec in SPECS.values():
        for ds in spec["task"].get("datasets", []):
            assert ds in registry, ds
            assert registry[ds]["license"] and registry[ds]["files"]


def _credential_params(url):
    query = parse_qs(urlsplit(url).query)
    return {name: values for name, values in query.items() if "key" in name.lower() or "token" in name.lower()}


def test_secrets_are_placeholders_not_values():
    registry = json.loads(taskset.DATASETS_JSON.read_text())["datasets"]
    urls = [f["url"] for meta in registry.values() for f in meta["files"]]
    found = [_credential_params(url) for url in urls if _credential_params(url)]
    assert found, "expected at least one credentialed URL (NSRDB) to exercise this check"
    for params in found:
        for name, values in params.items():
            assert all(v.startswith("{") and v.endswith("}") for v in values), f"{name} must be an env placeholder"


def test_rendered_instruction_has_the_contract():
    spec = SPECS["p01-ami-dst"]
    text = taskset.render_instruction(spec)
    assert "./answer.json" in text and "`decisions`" in text and "`system_kwh_2025_11_02`" in text
    assert "answer_key" not in text and "rubric" not in text.lower()


def test_rubric_parser_reads_every_criterion():
    for spec in SPECS.values():
        levels = parse_rubric_levels(spec["task"]["rubric"])
        assert len(levels) >= 3 and all("A" in v and "C" in v for v in levels.values())
