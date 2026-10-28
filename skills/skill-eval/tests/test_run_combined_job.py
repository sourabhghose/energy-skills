# Adapted from databricks-industry-solutions/vital-skills (skills/skill-eval/tests/test_run_combined_job.py); modified for the energy industry.
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "run_combined_job.py"
SPEC = importlib.util.spec_from_file_location("run_combined_job", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_spec():
    return {
        "tasks": [
            {"task_key": "baseline", "environment_key": "baseline_env"},
            {"task_key": "candidate", "environment_key": "candidate_env"},
            {
                "task_key": "score",
                "depends_on": [
                    {"task_key": "baseline"},
                    {"task_key": "candidate"},
                ],
                "run_if": "ALL_SUCCESS",
                "environment_key": "score_env",
            },
        ],
        "environments": [
            {"environment_key": "baseline_env", "spec": {"client": "4"}},
            {"environment_key": "candidate_env", "spec": {"client": "4"}},
            {"environment_key": "score_env", "spec": {"client": "4"}},
        ],
    }


def test_accepts_two_independent_arms_and_dependent_scorer():
    MODULE.validate_job(valid_spec())


def test_rejects_scorer_missing_one_arm_dependency():
    spec = valid_spec()
    spec["tasks"][2]["depends_on"] = [{"task_key": "baseline"}]
    with pytest.raises(ValueError, match="depend on both arm tasks"):
        MODULE.validate_job(spec)


def test_rejects_non_success_scoring_trigger():
    spec = valid_spec()
    spec["tasks"][2]["run_if"] = "ALL_DONE"
    with pytest.raises(ValueError, match="ALL_SUCCESS"):
        MODULE.validate_job(spec)


def test_rejects_serverless_client_other_than_four():
    spec = valid_spec()
    spec["environments"][0]["spec"]["client"] = "1"
    with pytest.raises(ValueError, match="client"):
        MODULE.validate_job(spec)
