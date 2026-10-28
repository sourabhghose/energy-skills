# Time, DST, and interval conventions

## Interval-ending vs interval-beginning

- **Interval-ending** (common for AMI head-ends and Green Button exports): the read stamped
  `14:15` covers `14:00–14:15`.
- **Interval-beginning** (common in MDMs, markets, and data warehouses): `14:15` covers
  `14:15–14:30`.
- This skill always outputs `interval_start_utc` (interval-beginning, UTC) plus
  `interval_start_local` with its UTC offset, so the convention is explicit downstream.

## The DST pitfalls

For a US zone such as `America/Chicago`:

| Day | Local length | 15-min intervals | What goes wrong in naive code |
|-----|--------------|------------------|-------------------------------|
| Spring forward (2nd Sunday of March) | 23 h | 92 | Expecting 96 creates 4 phantom "missing" intervals; labels 02:00–02:59 cannot exist |
| Fall back (1st Sunday of November) | 25 h | 100 | Labels 01:00–01:59 occur twice; `drop_duplicates` silently deletes an hour of energy, a pivot double-counts it |

How this skill resolves it:

1. Localize labels in **record order**: the first occurrence of an ambiguous wall-clock label is
   DST, the second is standard time. A label seen only once is flagged
   `dst_ambiguous_single`.
2. Labels in the spring-forward gap are flagged `nonexistent_time` and dropped.
3. Convert to UTC, **then** subtract one interval for interval-ending data. Subtracting
   before localizing is wrong at the fall-back boundary (the label `01:00` that ends the last
   DST interval becomes `00:45`, which then collides with a real `00:45`).
4. Completeness is measured against the DST-aware expected count per local day.

If the source carries offsets (`2024-11-03T01:15:00-05:00`) use `timestamp_basis='offset_aware'`;
if it is UTC, use `'utc'`. Never guess: the preview reports whether timestamps carry a
timezone.

## Sources

- IANA Time Zone Database: https://www.iana.org/time-zones
- US Energy Policy Act of 2005, §110 (current US DST dates):
  https://www.congress.gov/bill/109th-congress/house-bill/6
- pandas time zone handling (ambiguous / nonexistent):
  https://pandas.pydata.org/docs/user_guide/timeseries.html#time-zone-handling
