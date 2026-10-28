"""Each deterministic check type behaves as scoring.py documents."""

import json

import pytest

from scoring import load_answer, norm, score_checks, to_number

KEY = {"x": 100.0, "alt": 200.0, "lo": 1.0, "hi": 3.0, "m": {"A-1": 10.0, "B-2": 20.0}, "ids": ["P1", "P2"],
       "date": "2024-06-17", "n": 18, "bad_re": [r"(?<![\d.])38\.582"], "bad_lit": ["Maria Garcia"],
       "t_all": 50.0, "t_small": 40.0}


def score(check, answer, tmp_path):
    return score_checks([{**check, "points": 10}], KEY, answer, tmp_path)["det_score"]


def test_number_parsing():
    assert to_number("1,234.5 MWh") == 1234.5 and to_number(7) == 7.0
    assert to_number(True) is None and to_number("n/a") is None and to_number(float("nan")) is None


def test_norm():
    assert norm("Lost Circulation") == norm("lost_circulation") == "lost_circulation"


@pytest.mark.parametrize("check, answer, expected", [
    ({"type": "numeric", "key": "x", "rel_tol": 0.01}, {"x": 100.9}, 100),
    ({"type": "numeric", "key": "x", "rel_tol": 0.01}, {"x": 102}, 0),
    ({"type": "numeric", "key": "x", "abs_tol": 5}, {"X": "104"}, 100),
    ({"type": "numeric_any", "key": "x", "expected_any": ["x", "alt"], "rel_tol": 0.001}, {"x": 200}, 100),
    ({"type": "numeric_range", "key": "x", "low": "lo", "high": "hi"}, {"x": 2.5}, 100),
    ({"type": "numeric_range", "key": "x", "low": "lo", "high": "hi"}, {"x": 0.5}, 0),
    ({"type": "numeric_map", "key": "m", "abs_tol": 0.5}, {"m": {"a_1": 10.2, "B-2": 25}}, 50),
    ({"type": "exact", "key": "date"}, {"date": "2024-06-17"}, 100),
    ({"type": "exact", "key": "n"}, {"n": "18"}, 100),
    ({"type": "exact", "key": "n"}, {"n": 19}, 0),
    ({"type": "set_f1", "key": "ids"}, {"ids": ["p1"]}, pytest.approx(66.667, abs=0.01)),
    ({"type": "decision", "patterns": [["DST", "daylight"], ["read_seq"]]},
     {"decisions": [{"decision": "Daylight saving: used read_seq"}]}, 100),
    ({"type": "decision", "patterns": [["DST"]]}, {"decisions": []}, 0),
    ({"type": "forbid_in_list", "key": "f", "patterns": ["temp_actual"]}, {"f": ["temp_forecast_f"]}, 100),
    ({"type": "forbid_in_list", "key": "f", "patterns": ["temp_actual"]}, {"f": ["temp_actual_f"]}, 0),
    ({"type": "forbid_in_list", "key": "f", "patterns": ["temp_actual"]}, {"f": []}, 0),
])
def test_answer_checks(check, answer, expected, tmp_path):
    assert score(check, answer, tmp_path) == expected


def test_file_checks(tmp_path):
    share = tmp_path / "share"
    share.mkdir()
    (share / "s.csv").write_text("feeder_id,customer_count,total_mwh,lat\nF1,5,30,38.58\nF2,7,20,38.59\n")
    assert score({"type": "file_exists", "path": "share/s.csv"}, {}, tmp_path) == 100
    assert score({"type": "csv_min", "path": "share/s.csv", "column": "customer_count", "min": 5}, {}, tmp_path) == 100
    assert score({"type": "csv_sum_any", "path": "share/s.csv", "column": "total_mwh",
                  "expected_any": ["t_all", "t_small"], "rel_tol": 0.001}, {}, tmp_path) == 100
    assert score({"type": "file_forbid", "path": "share/*", "regex_from": "bad_re", "literals_from": "bad_lit"},
                 {}, tmp_path) == 100
    (share / "s.csv").write_text("feeder_id,customer_count,total_mwh,lat\nF1,2,30,38.5823\n")
    assert score({"type": "csv_min", "path": "share/s.csv", "column": "customer_count", "min": 5}, {}, tmp_path) == 0
    assert score({"type": "file_forbid", "path": "share/*", "regex_from": "bad_re"}, {}, tmp_path) == 0


def test_forbidden_coordinate_regex_ignores_digits_inside_larger_numbers(tmp_path):
    (tmp_path / "s.csv").write_text("total_mwh\n1238.5821\n")
    assert score({"type": "file_forbid", "path": "s.csv", "regex_from": "bad_re"}, {}, tmp_path) == 100


def test_missing_answer_scores_zero_but_file_checks_still_run(tmp_path):
    (tmp_path / "out.csv").write_text("a\n1\n")
    result = score_checks([{"type": "numeric", "key": "x", "points": 50},
                           {"type": "file_exists", "path": "out.csv", "points": 50}], KEY, None, tmp_path)
    assert result["det_score"] == 50


def test_pitfall_values_are_never_scoring_targets(tmp_path):
    with pytest.raises(ValueError, match="pitfall"):
        score_checks([{"type": "numeric", "key": "x", "expected": "_pitfall", "points": 1}],
                     {"_pitfall": 1}, {"x": 1}, tmp_path)


def test_load_answer_tolerates_fences(tmp_path):
    (tmp_path / "answer.json").write_text("```json\n" + json.dumps({"a": 1}) + "\n```")
    assert load_answer(tmp_path) == ({"a": 1}, "")
    (tmp_path / "answer.json").write_text("[1, 2]")
    assert load_answer(tmp_path)[0] is None
    assert load_answer(tmp_path / "missing")[1] == "no answer.json"
