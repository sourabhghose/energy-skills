# Peak blocks and NERC holidays

Decision `peak_definition` and `peak_timezone`. Blocks are evaluated in the **local prevailing
time of the product definition** (`peak_timezone`), which may differ from the ISO's publication
timezone (MISO publishes in EST; many MISO products define peak in Eastern prevailing time — check
the contract).

| Block | Days | Hours (hour ending) | Local clock |
|---|---|---|---|
| `5x16` | Mon–Fri excluding NERC holidays | HE7–HE22 | 06:00–22:00 |
| `2x16` | Sat, Sun and NERC holidays | HE7–HE22 | 06:00–22:00 |
| `7x8` | Every day | HE1–HE6, HE23–HE24 | 22:00–06:00 |
| `wrap` | 2x16 + 7x8 | | |
| `7x24` | All hours | | |

5x16 + 2x16 + 7x8 partition every hour exactly once (tested).

## NERC off-peak holidays

New Year's Day, Memorial Day (last Monday in May), Independence Day, Labor Day (first Monday in
September), Thanksgiving (fourth Thursday in November), Christmas Day. When a fixed-date holiday
falls on a Sunday, the following Monday is the holiday; when it falls on a Saturday, it is **not**
moved. Source: NERC Operating Committee definition of "Additional Off-Peak Days" (https://www.nerc.com;
URL not pinned here: verify before use) and the product specs of ICE/NYMEX power contracts, which
reference it. Confirm the calendar your contract uses.

On DST days a 5x16 weekday still has 16 peak hours (the transition happens at 02:00, in the 7x8
block): the 23- or 25-hour day changes the off-peak count.
