"""Unit tests for skills/skill-eval/scripts/validate_eval_dir.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_eval_dir import main, validate  # noqa: E402

DS = "/Volumes/c/s/eval/demo/data.parquet"


def _tasks(levels=("easy", "hard", "edge")):
    evalset = [{"task_id": f"demo-{i:03d}", "dataset": DS, "query": f"Do task {i}"}
               for i, _ in enumerate(levels, 1)]
    expectations = [{"task_id": f"demo-{i:03d}", "dataset": DS, "difficulty": level,
                     "expectations": {"expected_facts": ["x"]}}
                    for i, level in enumerate(levels, 1)]
    return evalset, expectations


def _write(tmp_path: Path, evalset, expectations, extra=()):
    for name in ("README.md", "scorers.py", "generate_data.py", *extra):
        (tmp_path / name).write_text("x", encoding="utf-8")
    (tmp_path / "evalset.json").write_text(json.dumps(evalset), encoding="utf-8")
    (tmp_path / "expectations.json").write_text(json.dumps(expectations), encoding="utf-8")
    return tmp_path


def test_valid_folder_passes(tmp_path):
    assert validate(_write(tmp_path, *_tasks())) == []
    assert main([str(tmp_path)]) == 0


def test_missing_required_file(tmp_path):
    _write(tmp_path, *_tasks())
    (tmp_path / "scorers.py").unlink()
    assert any("scorers.py" in e for e in validate(tmp_path))
    assert validate(tmp_path, {"scorers.py"}) == []


def test_task_count_bounds(tmp_path):
    errors = validate(_write(tmp_path, *_tasks(("easy", "hard"))))
    assert any("need 3-5" in e for e in errors)


def test_answer_key_leak_in_evalset(tmp_path):
    evalset, expectations = _tasks()
    evalset = [{**evalset[0], "difficulty": "easy"}, *evalset[1:]]
    errors = validate(_write(tmp_path, evalset, expectations))
    assert any("answer-key fields" in e for e in errors)


def test_join_mismatch(tmp_path):
    evalset, expectations = _tasks()
    expectations = [{**expectations[0], "dataset": "/other"}, *expectations[1:]]
    errors = validate(_write(tmp_path, evalset, expectations))
    assert sum("not expectations.json" in e or "not evalset.json" in e for e in errors) == 2


def test_difficulty_spread(tmp_path):
    errors = validate(_write(tmp_path, *_tasks(("hard", "hard", "edge"))))
    assert any("at least one easy" in e for e in errors)
    bad = validate(_write(tmp_path, *_tasks(("easy", "medium", "easy"))))
    assert any("difficulty 'medium'" in e for e in bad)


def test_scores_without_report_fail(tmp_path):
    errors = validate(_write(tmp_path, *_tasks(), extra=("baseline_scores.json",)))
    assert any("real run" in e for e in errors)


def test_report_needs_both_score_files(tmp_path):
    errors = validate(_write(tmp_path, *_tasks(), extra=("eval_report.md", "baseline_scores.json")))
    assert any("with_skill_scores.json" in e for e in errors)
    ok = validate(_write(tmp_path, *_tasks(), extra=("with_skill_scores.json",)))
    assert ok == []


def test_bad_json(tmp_path):
    _write(tmp_path, *_tasks())
    (tmp_path / "evalset.json").write_text("{not json", encoding="utf-8")
    assert any("cannot parse" in e for e in validate(tmp_path))


def test_not_a_directory(tmp_path):
    assert validate(tmp_path / "nope") == [f"not a directory: {tmp_path / 'nope'}"]
