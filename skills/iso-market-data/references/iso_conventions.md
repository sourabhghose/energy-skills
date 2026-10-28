# ISO/RTO price data conventions and traps

Machine-readable registry: `assets/iso_conventions.json` (every entry `verify_before_use`: confirm
against the ISO's current specification for the exact report you load, and edit the JSON rather
than the code).

| ISO | Local time | Native labels | Default convention | RT settlement | Price & components |
|---|---|---|---|---|---|
| CAISO | Pacific prevailing | OASIS GMT start/end | beginning (start column) | 5-min RTD (15-min FMM) | LMP = energy + congestion + loss + GHG |
| ERCOT | Central prevailing | Date + HourEnding + Interval + DSTFlag | ending | 15-min SPP | SPP; RT includes ORDC adders; no loss component |
| PJM | Eastern prevailing | datetime_beginning_utc/_ept | beginning | 5-min (since Feb 2021) | total_lmp = energy + congestion + loss |
| MISO | **EST all year** | Market date + HE | ending | 5-min | LMP, MCC, MLC; energy = LMP − MCC − MLC |
| NYISO | Eastern prevailing | Time Stamp | check per report | 5-min | **LBMP = energy + loss − published congestion** |
| ISO-NE | Eastern prevailing | Date + HE, repeated hour "02X" | ending | 5-min (since 2017) | LMP = energy + congestion + loss |
| SPP | Central prevailing | GMTIntervalEnd | ending | 5-min | LMP = MEC + MCC + MLC |

## Traps this skill guards against

1. **Interval beginning vs ending.** A 5-minute price labelled 10:05 is either 10:00–10:05 or
   10:05–10:10. Mixing conventions across ISOs (or across reports of the same ISO) shifts every
   interval, misaligns DA with RT, and moves the first interval of each day into the previous
   day. The preview shows the registry default and the data's evidence; the user confirms.
2. **DST.** Hour-ending local data has a 23-hour day in spring (HE3 absent) and a 25-hour day in
   fall (repeated HE2, flagged `DSTFlag=Y` in ERCOT, `02X` in ISO-NE). Unflagged duplicates are
   rejected; spring-forward labels that cannot exist are rejected. MISO publishes in EST all year,
   so its summer hours are one hour off Eastern prevailing time.
3. **Hourly averages.** RT hourly prices must be time-weighted over the intervals in the hour. A
   simple mean of present intervals hides missing intervals; the skill reports covered minutes
   and flags incomplete hours. Settlement uses interval prices × interval MWh, never hourly
   average × hourly MWh.
4. **Component signs.** NYISO's published congestion component has the opposite sign; the preview
   fits both sign conventions to the data and shows which reconciles.
5. **ERCOT SPP is not LMP.** RT settlement point prices include ORDC and reliability adders; SCED
   bus LMPs are not what resources are paid.
6. **Identity.** Pricing nodes, hubs and zones change names over time. Requested nodes are matched
   exactly; close matches are suggested, never substituted.
7. **Negative prices and caps.** Negative prices are real (wind/solar PTC, curtailment economics)
   and are flagged, never dropped. Price floors and caps differ by ISO and change over time
   (e.g. ERCOT's high system-wide offer cap); the user states the bounds used for outlier flags.

## Sources

- FERC Order 825 (settlement intervals equal dispatch intervals; shortage pricing):
  https://www.ferc.gov/media/order-no-825
- CAISO OASIS interface specification: https://www.caiso.com/library/oasis-interface-specification
- ERCOT data products and public API: https://www.ercot.com/mp/data-products ;
  https://developer.ercot.com/
- PJM Data Miner 2: https://dataminer2.pjm.com/
- MISO market reports: https://www.misoenergy.org/markets-and-operations/real-time--market-data/market-reports/
- NYISO Market Participant User's Guide (LBMP components): https://www.nyiso.com/documents/20142/3625950/mpug.pdf
- ISO Express (ISO-NE): https://www.iso-ne.com/isoexpress/
- SPP Integrated Marketplace: https://marketplace.spp.org/groups/integrated-marketplace
- EIA-930 notes on BA time conventions: https://www.eia.gov/electricity/930-content/about.html
