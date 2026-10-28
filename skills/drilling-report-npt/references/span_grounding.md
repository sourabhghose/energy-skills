# Span-grounded remark classification

The model runs through `ai_query` with the prompt from `scripts/npt_text.py` (version
`npt-span-v1`) and must return JSON events with a **verbatim quote**. The core keeps an event
only if all of these hold:

1. `category` is one of the skill's categories.
2. The quote appears in the remark (whitespace- and case-normalized substring match).
3. The model did not mark it `negated`.
4. `subject == this_well` (not `offset_well`, `historical`, or `planned_or_contingency`).
5. A deterministic backstop finds no negation, hypothetical, or offset-well cue in the 80
   characters before the quote, within the same clause.

Rule 5 catches common model errors:

| Remark | Model error | Backstop |
|---|---|---|
| "Drilled ahead. No losses observed." | LOST_CIRCULATION, negated=false | `negated_in_text` |
| "Offset well had stuck pipe at this depth." | STUCK_PIPE, subject=this_well | `offset_well_in_text` |
| "Short trip as precaution for possible stuck pipe." | STUCK_PIPE | `hypothetical_in_text` |
| "Circulated." with quote "total losses" | invented quote | `quote_not_in_remark` |

Every dropped event is kept in the events frame with its `drop_reason`, and the preview
reports the counts. The shareable evidence table carries only the verbatim quote, never the
full remark, so it can go to a contractor without exposing other operational detail.

Use a strong instruction-following endpoint. Pay-per-token Foundation Model API endpoints work.
Pin the endpoint name in the manifest so reruns are comparable.
