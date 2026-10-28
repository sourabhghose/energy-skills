"""Harness behaviour as README.md describes it: answer-key isolation, selection, scheduling, blinding, grading,
statistics and dataset pinning. Offline: no network, no Genie, no Databricks."""

import json
import subprocess
import zipfile

import pytest

import analyze
import fetch
import generate
import judge
import run
import taskset
from rubric import parse_rubric_levels, redact, score_response
from helpers import perfect_answer


def has_head() -> bool:
    return subprocess.run(["git", "-C", str(run.REPO_ROOT), "rev-parse", "--verify", "HEAD"],
                          capture_output=True).returncode == 0


# --- taskset ---------------------------------------------------------------------------------------------------------

def test_combine():
    assert taskset.combine(["a", "b"], ["b"]) == ("covered", ["b"])
    assert taskset.combine([], []) == ("control", [])
    assert taskset.combine(["a"], []) == ("disputed", ["a"])


def test_select_covered_and_controls():
    tasks = [{"task_id": "p1", "tier": "P", "coverage": "covered", "energy_skills": ["x"]},
             {"task_id": "p2", "tier": "P", "coverage": "covered", "energy_skills": ["y"]},
             {"task_id": "r1", "tier": "R", "coverage": "covered", "energy_skills": ["x"]},
             {"task_id": "c1", "tier": "P", "coverage": "control", "energy_skills": []},
             {"task_id": "c2", "tier": "P", "coverage": "control", "energy_skills": []},
             {"task_id": "d1", "tier": "P", "coverage": "disputed", "energy_skills": ["x"]}]
    assert taskset.select(tasks, "x", None) == ["p1", "r1", "c1", "c2"]
    assert taskset.select(tasks, "x", None, tier="P") == ["p1", "c1", "c2"]
    assert len(taskset.select(tasks, None, 1, seed=3)) == 4
    with pytest.raises(SystemExit):
        taskset.select(tasks, "nope")


def test_merge_partial_relabel_keeps_frozen_rows():
    doc = {"labels": {"skills_sha": "old"}, "tasks": [{"task_id": "a", "coverage": "control"},
                                                      {"task_id": "b", "coverage": "control"}]}
    merged = taskset.merge(doc, [{"task_id": "b", "coverage": "covered"}], {"skills_sha": "new"})
    assert merged["labels"]["skills_sha"] == "old" and merged["labels"]["updates"][0]["tasks"] == ["b"]
    assert [t["coverage"] for t in merged["tasks"]] == ["control", "covered"]


def test_save_roundtrip(tmp_path):
    doc = taskset.load()
    taskset.save(doc, tmp_path / "t.json")
    assert taskset.load(tmp_path / "t.json") == doc


# --- generate: answer-key isolation --------------------------------------------------------------------------------

def test_materialise_separates_data_and_grading(tmp_path):
    home, grading = tmp_path / "home", tmp_path / "grading"
    data, key = generate.materialise("p04-reliability-caidi", 7, home, grading)
    files = {p.name for p in data.rglob("*")}
    assert "answer_key.json" not in files and "rubric.txt" not in files and "task.toml" not in files
    g = grading / "p04-reliability-caidi"
    assert json.loads((g / "answer_key.json").read_text()) == key
    assert "./answer.json" in (g / "instruction.md").read_text()
    assert json.loads((g / "data_manifest.json").read_text())["seed"] == 7
    with pytest.raises(FileExistsError):
        generate.materialise("p04-reliability-caidi", 7, home, grading)
    generate.materialise("p04-reliability-caidi", 8, home, grading, force=True)


def test_materialise_rejects_tier_r(tmp_path):
    with pytest.raises(SystemExit):
        generate.materialise("r01-eia930-ercot-peak", 1, tmp_path, tmp_path)


# --- run ---------------------------------------------------------------------------------------------------------

def test_schedule_is_seeded_and_complete():
    a = run.build_schedule(["t1", "t2", "t3"], ["x", "y"], [1, 2], seed=5)
    assert a == run.build_schedule(["t1", "t2", "t3"], ["x", "y"], [1, 2], seed=5)
    assert len(a) == 12 and {(i["task"], i["arm"], i["rep"]) for i in a} == {
        (t, arm, r) for t in ("t1", "t2", "t3") for arm in ("x", "y") for r in (1, 2)}
    assert [i["rep"] for i in a[:6]] == [1] * 6


def test_token_usage_and_skill_opens(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join([
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 7}}),
        "not json",
        json.dumps({"type": "item.started", "item": {"type": "command_execution",
                                                     "command": "cat .agents/skills/reliability-metrics/SKILL.md"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 50, "output_tokens": 3}}),
    ]))
    assert run.token_usage(events) == {"input_tokens": 150, "cached_input_tokens": 80, "output_tokens": 10}
    assert run.opened_skills(events) == ["reliability-metrics"]


def test_rate_limited_needs_failed_turn(tmp_path):
    events = tmp_path / "events.jsonl"
    limit = {"type": "error", "message": "429 REQUEST_LIMIT_EXCEEDED"}
    events.write_text(json.dumps(limit) + "\n" + json.dumps({"type": "turn.completed", "usage": {}}))
    assert not run.rate_limited(events)
    events.write_text(json.dumps(limit) + "\n" + json.dumps({"type": "turn.failed", "error": limit}))
    assert run.rate_limited(events)


def test_genie_profile_disables_user_skills(tmp_path, monkeypatch):
    skills = tmp_path / "skills" / "mine"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: mine\n---\n")
    monkeypatch.setattr(run, "GENIE_HOME", tmp_path)
    monkeypatch.setattr(run, "USER_SKILL_DIRS", (tmp_path / "skills",))
    text = run.write_genie_profile().read_text()
    assert 'approval_policy = "never"' in text and 'name = "mine"\nenabled = false' in text


def test_bad_arm_specs_exit():
    assert run.resolve_arms(["no_skills"]) == {"no_skills": {"ref": None, "sha": None, "skills_tree": None}}
    for bad in ("x=", "no_skills=HEAD", "plain"):
        with pytest.raises(SystemExit):
            run.resolve_arms([bad])


@pytest.mark.skipif(not has_head(), reason="repository has no commit yet")
def test_installed_skills_exclude_answer_keys(tmp_path):
    names = run.install_skills(run.git("rev-parse", "HEAD"), tmp_path)
    for name in names:
        assert (tmp_path / name / "SKILL.md").is_file()
        assert not (tmp_path / name / "eval").exists() and not (tmp_path / name / "tests").exists()


# --- rubric and blinding -------------------------------------------------------------------------------------------

RUBRIC = """Criterion 1: A
    Levels: A=60 B=20 C=0
Criterion 2: B
    Levels: A=40 B=10 C=0
"""


def test_points_come_from_rubric_not_model():
    assert parse_rubric_levels(RUBRIC) == {"criterion_1": {"A": 60, "B": 20, "C": 0},
                                           "criterion_2": {"A": 40, "B": 10, "C": 0}}
    resp = json.dumps({"criteria": {"criterion_1": {"level": "A", "score": 99}, "criterion_2": {"level": "b"}}})
    assert score_response(RUBRIC, "Here:\n" + resp)["total"] == 70
    assert score_response(RUBRIC, "I cannot grade this.")["total"] == 0


def test_redact_removes_arm_identity():
    text = "Read .agents/skills/reliability-metrics/SKILL.md then ran scripts/reliability_run.py with Genie Code"
    out = redact(text, ["reliability-metrics"])
    assert "reliability-metrics" not in out and "SKILL.md" not in out and "Genie" not in out
    assert "reliability_run.py" not in out


def test_leak_markers_include_answer_key(tmp_path):
    (tmp_path / "events.jsonl").write_text('{"cmd": "cat ~/.cache/energybench-grading/p01/answer_key.json"}')
    assert judge.leaked(tmp_path)


# --- judge: deterministic grading end to end ----------------------------------------------------------------------

def _fake_run(home, task, arm, rep, answer):
    wd = home / "runs" / "r1" / task / arm / f"rep{rep}"
    wd.mkdir(parents=True)
    (wd / "run.json").write_text(json.dumps({"skills": ["unit-guard"] if arm == "skills" else []}))
    (wd / "answer.json").write_text(json.dumps(answer))
    (wd / "trace.md").write_text("Used unit-guard.")
    return wd


def test_judge_no_llm_grades_planted_task(tmp_path):
    home, grading = tmp_path / "home", tmp_path / "grading"
    _, key = generate.materialise("p11-boe", 3, home, grading)
    spec = taskset.load_spec("p11-boe")
    _fake_run(home, "p11-boe", "skills", 1, perfect_answer(spec, key))
    _fake_run(home, "p11-boe", "no_skills", 1, {"total_mboe": key["_pitfall"]["total_mboe_mmcf_as_mcf"]})
    rows = judge.collect_rows(["r1"], home)
    assert all("unit-guard" not in r["trace"] for r in rows)
    grades = {g["arm"]: g for g in judge.grade_all(rows, None, None, 1, tmp_path, 1, grading)}
    assert grades["skills"]["det_score"] == 100 and grades["no_skills"]["det_score"] == 0
    assert grades["skills"]["complete"] is False  # det_weight 0.7: needs the rubric for a full score


def test_combine_scores():
    assert judge.combine_scores({"det_score": 80}, [60, 40], 0.5) == (65.0, True)
    assert judge.combine_scores({"det_score": 80}, None, 0.7) == (80, False)
    assert judge.combine_scores({"det_score": 0}, [70], 0.0) == (70, True)


# --- analyze --------------------------------------------------------------------------------------------------------

def _grades(scores: dict) -> list[dict]:
    out = []
    for (task, arm), values in scores.items():
        for rep, v in enumerate(values, 1):
            out.append({"run_id": "r", "task": task, "arm": arm, "rep": rep, "score": v, "det_score": v,
                        "complete": True, "checks": [{"type": "decision", "earned": 10 if arm == "s" else 0}]})
    return out


def test_analysis_gates(tmp_path):
    scores = {("p1", "s"): [80, 82, 78], ("p1", "b"): [60, 58, 62], ("p2", "s"): [90, 88, 92],
              ("p2", "b"): [70, 72, 68], ("c1", "s"): [50, 50, 50], ("c1", "b"): [51, 49, 50]}
    sets = {"covered": ["p1", "p2"], "control": ["c1"], "disputed": [], "all": ["p1", "p2", "c1"]}
    result = analyze.analyze(_grades(scores), sets, analyze.comparisons_for("s", "b"),
                             {"p1": ["x"], "p2": ["x"], "c1": []}, home=tmp_path)
    by = {c["set"] + c["metric"]: c for c in result["comparisons"]}
    assert by["coveredscore"]["effect"] == pytest.approx(20) and by["coveredscore"]["decision"] == "PASS"
    assert by["controlscore"]["decision"] == "PASS"
    assert result["decision_rate"] == {"b": 0.0, "s": 100.0}
    assert "EnergyBench analysis" in analyze.to_markdown(result)


def test_partial_grades_are_excluded(tmp_path):
    grades = _grades({("p1", "s"): [90], ("p1", "b"): [10]})
    grades[0]["complete"] = False
    runs = analyze.load_runs(grades, home=tmp_path)
    assert [r["excluded"] for r in runs] == [True, False]


def test_decide_rules():
    assert analyze.decide("improves", 6, -1, {"a": 6}) == "PASS"
    assert analyze.decide("improves", 6, -6, {"a": 6}) == "inconclusive"
    assert analyze.decide("no_harm", -2, -9, {"a": -16}) == "FAIL"
    assert analyze.sign_test([1, 1, 1, -1]) == (3, 1, 0.625)


# --- fetch ----------------------------------------------------------------------------------------------------------

def test_resolve_url_requires_secrets():
    url = "https://x.test/a.csv?api_key={NREL_API_KEY}&email={NREL_EMAIL}"
    assert fetch.resolve_url(url, {"NREL_API_KEY": "k", "NREL_EMAIL": "e"}).endswith("api_key=k&email=e")
    with pytest.raises(SystemExit, match="NREL_EMAIL"):
        fetch.resolve_url(url, {"NREL_API_KEY": "k"})


def test_lock_pins_and_detects_drift():
    lock = {}
    assert fetch.check_lock(lock, "ds", "f", "abc", False, write=True) == "locked"
    assert fetch.check_lock(lock, "ds", "f", "abc", False, write=False) == "pinned"
    with pytest.raises(SystemExit, match="does not match"):
        fetch.check_lock(lock, "ds", "f", "def", True, write=False)
    with pytest.raises(SystemExit, match="not in"):
        fetch.check_lock({}, "ds", "f", "abc", False, write=False)


def test_extracted_pin_ignores_member_names(tmp_path):
    for name, inner in (("a.zip", "20240101_run1.csv"), ("b.zip", "20240101_run2.csv")):
        with zipfile.ZipFile(tmp_path / name, "w") as zf:
            zf.writestr(inner, "x,y\n1,2\n")
    assert fetch.pin_hash(tmp_path / "a.zip", "extracted") == fetch.pin_hash(tmp_path / "b.zip", "extracted")
    assert fetch.pin_hash(tmp_path / "a.zip", "file") != fetch.pin_hash(tmp_path / "b.zip", "file")


def test_manual_dataset_explains_what_to_do(tmp_path):
    meta = taskset.datasets()["volve"]
    with pytest.raises(SystemExit, match="manual download"):
        fetch.obtain("volve", meta, meta["files"][0], tmp_path)
