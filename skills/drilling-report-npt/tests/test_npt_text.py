"""Span grounding, negation, subject, and parsing behaviour of the remark classifier."""

from __future__ import annotations

from npt_text import build_prompt, classify_remarks, ground_events, parse_response, primary_text_category


def test_prompt_embeds_remark_and_categories():
    prompt = build_prompt("Stuck pipe at 5000 ft")
    assert "<<<Stuck pipe at 5000 ft>>>" in prompt
    assert "LOST_CIRCULATION" in prompt and "verbatim" in prompt


def test_parse_tolerates_prose_and_rejects_garbage():
    assert parse_response('Sure: {"events": [{"category": "FISHING", "quote": "x"}]}')[0]["category"] == "FISHING"
    assert parse_response("not json at all") == []
    assert parse_response('{"events": "oops"}') == []


def test_quote_must_be_in_remark():
    ev = ground_events("r1", "Circulated and conditioned mud.",
                       [{"category": "LOST_CIRCULATION", "quote": "total losses", "subject": "this_well"}])
    assert not ev[0].kept and ev[0].drop_reason == "quote_not_in_remark"


def test_quote_match_ignores_case_and_whitespace():
    ev = ground_events("r1", "Jarred  on STUCK pipe 3 hrs",
                       [{"category": "STUCK_PIPE", "quote": "jarred on stuck pipe", "subject": "this_well"}])
    assert ev[0].kept


def test_negation_backstop_catches_model_error():
    ev = ground_events("r1", "Drilled ahead. No losses observed.",
                       [{"category": "LOST_CIRCULATION", "quote": "losses observed", "negated": False}])
    assert not ev[0].kept and ev[0].drop_reason == "negated_in_text"


def test_model_negation_and_subject_respected():
    remark = "Kick detected, shut in well."
    neg = ground_events("r1", remark, [{"category": "WELL_CONTROL", "quote": "Kick detected", "negated": True}])
    off = ground_events("r1", remark, [{"category": "WELL_CONTROL", "quote": "Kick detected", "subject": "offset_well"}])
    assert neg[0].drop_reason == "negated_by_model"
    assert off[0].drop_reason == "subject_offset_well"


def test_offset_and_hypothetical_backstops():
    off = ground_events("r1", "Offset well had stuck pipe here.", [{"category": "STUCK_PIPE", "quote": "stuck pipe here"}])
    hyp = ground_events("r1", "Short trip as precaution for possible stuck pipe.", [{"category": "STUCK_PIPE", "quote": "stuck pipe"}])
    assert off[0].drop_reason == "offset_well_in_text"
    assert hyp[0].drop_reason == "hypothetical_in_text"


def test_unknown_category_dropped():
    ev = ground_events("r1", "Rig move", [{"category": "RIG_MOVE", "quote": "Rig move"}])
    assert ev[0].drop_reason == "unknown_category"


def test_classify_remarks_with_fake_llm(ops_raw, llm):
    events = classify_remarks(ops_raw, llm)
    kept = set(events[events["kept"]]["row_id"])
    assert kept == {"r2", "r3", "r4"}
    cats = primary_text_category(events).set_index("row_id")["text_category"].to_dict()
    assert cats == {"r2": "EQUIPMENT_RIG", "r3": "LOST_CIRCULATION", "r4": "WAIT_WEATHER"}


def test_multi_category_rows_flagged():
    events = classify_remarks(
        __import__("pandas").DataFrame({"row_id": ["a"], "remarks": ["Lost circulation then stuck pipe"]}),
        lambda _p: '{"events": [{"category": "LOST_CIRCULATION", "quote": "Lost circulation"},'
                   '{"category": "STUCK_PIPE", "quote": "stuck pipe"}]}')
    prim = primary_text_category(events)
    assert bool(prim.loc[0, "multi_category"]) and prim.loc[0, "text_category"] == "LOST_CIRCULATION"
