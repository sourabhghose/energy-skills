"""Span-grounded NPT extraction from daily drilling report (DDR) remark text.

Purpose: build the ai_query prompt, parse the model's JSON, and keep an extracted NPT event
only when (1) its quote is literally present in the remark, (2) it is asserted (not negated,
not hypothetical), and (3) it happened on *this* well (not an offset or historical well).
The model call itself is injected (`llm` callable) so tests run offline with a fake.

Usage:
    from npt_text import build_prompt, parse_response, ground_events, classify_remarks
    events = classify_remarks(df, llm=lambda prompt: call_endpoint(prompt))
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass

import pandas as pd

from npt_taxonomy import CATEGORY_HINTS, NPT_CATEGORIES

LOG = logging.getLogger(__name__)
PROMPT_VERSION = "npt-span-v1"
SUBJECTS = ("this_well", "offset_well", "historical", "planned_or_contingency")

NEGATION_CUES = re.compile(
    r"\b(no|nil|not|without|none|zero|free of|no sign of|no signs of|no indication of|"
    r"did not|didn't|was not|wasn't|absence of|negative for)\b[^.;]{0,40}$",
    re.IGNORECASE,
)
HYPOTHETICAL_CUES = re.compile(
    r"\b(possible|potential|risk of|contingency|in case of|prepare(d)? for|plan(ned)? for|"
    r"to prevent|precaution(ary)?|monitor(ing)? for|watch(ing)? for)\b[^.;]{0,40}$",
    re.IGNORECASE,
)
OFFSET_CUES = re.compile(r"\b(offset well|offset|neighbou?r(ing)? well|previous well|last well|"
                         r"on well [A-Z0-9-]+|historically)\b[^.;]{0,60}$", re.IGNORECASE)


@dataclass(frozen=True)
class NptEvent:
    row_id: str
    category: str
    quote: str
    subject: str
    negated: bool
    equipment_owner: str | None
    grounded: bool
    kept: bool
    drop_reason: str | None


def build_prompt(remark: str) -> str:
    """Prompt asking for span-grounded, negation- and subject-aware NPT events as JSON."""
    return prompt_head() + remark + PROMPT_TAIL


PROMPT_TAIL = ">>>"


def prompt_head() -> str:
    """Instruction text before the remark; the runner concatenates it in SQL around ai_query."""
    cats = "\n".join(f"- {c}: {CATEGORY_HINTS[c]}" for c in NPT_CATEGORIES)
    return (
        "You classify non-productive time (NPT) in one drilling operations time-log remark.\n"
        "Return ONLY JSON: {\"events\": [{\"category\": <one of the categories>, "
        "\"quote\": <exact verbatim substring of the remark that supports it>, "
        "\"negated\": <true if the remark says it did NOT happen>, "
        f"\"subject\": <one of {list(SUBJECTS)}>, "
        "\"equipment_owner\": <\"rig\", \"service_company\", or null>}]}.\n"
        "Rules: copy quotes character-for-character; never paraphrase. "
        "Mentions of an offset/previous well are subject offset_well. Precautions, plans, or "
        "risks are planned_or_contingency. 'No losses' is negated=true. "
        "Return {\"events\": []} if the time was productive.\n"
        f"Categories:\n{cats}\n\nRemark:\n<<<"
    )


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in model response")
    return json.loads(match.group(0))


def parse_response(text: str) -> list[dict]:
    """Parse model output into raw event dicts. Malformed output yields [] with a warning."""
    try:
        payload = _extract_json(text)
    except (ValueError, json.JSONDecodeError) as exc:
        LOG.warning("unparseable NPT response (%s): %.120s", exc, text)
        return []
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return [e for e in events if isinstance(e, dict)]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def quote_position(remark: str, quote: str) -> int:
    """Index of the whitespace/case-normalized quote in the remark, or -1 if absent."""
    q = _norm(quote)
    return _norm(remark).find(q) if q else -1


def _context_drop_reason(remark: str, pos: int) -> str | None:
    """Deterministic backstop: negation / hypothetical / offset cues just before the quote."""
    prefix = _norm(remark)[max(0, pos - 80):pos]
    if NEGATION_CUES.search(prefix):
        return "negated_in_text"
    if HYPOTHETICAL_CUES.search(prefix):
        return "hypothetical_in_text"
    if OFFSET_CUES.search(prefix):
        return "offset_well_in_text"
    return None


def _decide(raw: dict, remark: str) -> tuple[bool, bool, str | None]:
    """Return (grounded, kept, drop_reason) for one raw event."""
    category = raw.get("category")
    pos = quote_position(remark, str(raw.get("quote", "")))
    if category not in NPT_CATEGORIES:
        return pos >= 0, False, "unknown_category"
    if pos < 0:
        return False, False, "quote_not_in_remark"
    if bool(raw.get("negated")):
        return True, False, "negated_by_model"
    if raw.get("subject", "this_well") != "this_well":
        return True, False, f"subject_{raw.get('subject')}"
    reason = _context_drop_reason(remark, pos)
    return True, reason is None, reason


def ground_events(row_id: str, remark: str, raw_events: list[dict]) -> list[NptEvent]:
    """Apply span-grounding + negation/subject filters to raw model events."""
    out = []
    for raw in raw_events:
        grounded, kept, reason = _decide(raw, remark)
        owner = raw.get("equipment_owner")
        out.append(NptEvent(
            row_id=str(row_id), category=str(raw.get("category")), quote=str(raw.get("quote", "")),
            subject=str(raw.get("subject", "this_well")), negated=bool(raw.get("negated")),
            equipment_owner=owner if owner in ("rig", "service_company") else None,
            grounded=grounded, kept=kept, drop_reason=reason,
        ))
    return out


def events_frame(events: list[NptEvent]) -> pd.DataFrame:
    cols = list(NptEvent.__dataclass_fields__)
    return pd.DataFrame([asdict(e) for e in events], columns=cols)


def classify_remarks(ops: pd.DataFrame, llm, row_id_col: str = "row_id",
                     remark_col: str = "remarks") -> pd.DataFrame:
    """Call `llm(prompt) -> str` per remark and return all grounded/dropped events.

    In the runner `llm` is replaced by a single batched ai_query SQL call; this function is
    the offline equivalent used by tests and small interactive runs.
    """
    events: list[NptEvent] = []
    for row_id, remark in zip(ops[row_id_col], ops[remark_col].fillna("")):
        if not str(remark).strip():
            continue
        events.extend(ground_events(row_id, str(remark), parse_response(llm(build_prompt(str(remark))))))
    return events_frame(events)


def events_from_responses(ops: pd.DataFrame, responses: pd.Series, row_id_col: str = "row_id",
                          remark_col: str = "remarks") -> pd.DataFrame:
    """Ground events from precomputed model responses aligned with `ops` (runner path)."""
    events: list[NptEvent] = []
    for row_id, remark, text in zip(ops[row_id_col], ops[remark_col].fillna(""), responses):
        events.extend(ground_events(row_id, str(remark), parse_response(str(text or ""))))
    return events_frame(events)


def primary_text_category(events: pd.DataFrame) -> pd.DataFrame:
    """One category per time-log row from kept events: first kept event wins.

    Rows with more than one distinct kept category are flagged `multi_category=True` so the
    preview can surface them for review rather than splitting hours silently.
    """
    kept = events[events["kept"]] if len(events) else events
    if kept.empty:
        return pd.DataFrame(columns=["row_id", "text_category", "text_quote",
                                     "equipment_owner", "multi_category"])
    grouped = kept.groupby("row_id", sort=False)
    first = grouped.first()[["category", "quote", "equipment_owner"]]
    multi = grouped["category"].nunique() > 1
    return (first.rename(columns={"category": "text_category", "quote": "text_quote"})
            .assign(multi_category=multi).reset_index())
