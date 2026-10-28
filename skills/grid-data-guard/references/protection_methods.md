# Protection methods used by grid-data-guard

## Column plan by audience

| Class | internal_need_to_know (record-level view) | external_partner / public (aggregate only) |
|-------|-------------------------------------------|--------------------------------------------|
| PII_DIRECT | NULL unless in `privileged_group` | dropped |
| PII_ID | salted token unless privileged | counted (distinct customers), never published |
| GEO_PRECISE | NULL unless privileged; `geo_cell` added | only as a generalized grouping cell |
| CEII_TOPOLOGY | NULL unless privileged | dropped; may group for external partner, never for public |
| CEII_SETTINGS | NULL unless privileged | dropped |
| CONSUMPTION | kept | summed per cell after the rule |
| QUASI | kept | grouping key if selected, otherwise dropped |

## Why each method

- **Salted tokens, not plain hashes.** Account numbers and meter IDs live in small, structured
  spaces (often 10 digits). `sha2(account)` can be reversed by hashing every candidate. The
  view uses `sha2(concat(secret(scope, key), col))`, so without the secret no lookup table
  can be built. Keep the secret in a Databricks secret scope and rotate it on exposure.
- **The 15/15 check uses per-customer totals.** Count *customers*, not rows: a meter with
  2,976 interval rows is still one customer. A dominant customer (an industrial site in a
  residential ZIP) fails the 15 % share test even when k ≥ 15. `k_only` does not catch this.
- **Complementary suppression.** If a parent total (all ZIPs for a month) is published and
  exactly one child cell is suppressed, the child can be recovered by subtraction. The skill
  then also suppresses the smallest visible cell in that parent.
- **Never publish the largest-customer statistics.** `max_customer_value` and its share are
  used to apply the rule but are dropped from the release, since publishing them would
  reveal the dominant customer's usage.
- **Coarser time is safer.** Hourly or 15-minute load shapes expose occupancy and appliance
  signatures (Molina-Markham et al., 2010). Prefer monthly aggregates for public releases.
  Hourly releases need larger cells.
- **Geography.** Precise coordinates identify single premises (the preview reports the share
  of unique points). Use H3 cells (resolution 7 ≈ 5.2 km², 8 ≈ 0.74 km²) or rounding
  (2 decimals ≈ 1.1 km). Databricks `h3_longlatash3(lon, lat, res)` takes **longitude
  first**; swapping the arguments silently produces cells in the wrong place.

## Sources

- Molina-Markham, A. et al. (2010), "Private Memoirs of a Smart Meter", ACM BuildSys: https://doi.org/10.1145/1878431.1878446
- Databricks H3 functions: https://docs.databricks.com/en/sql/language-manual/sql-ref-h3-geospatial-functions.html
- Databricks dynamic views / `is_account_group_member`: https://docs.databricks.com/en/data-governance/unity-catalog/filters-and-masks/
- Databricks `secret` SQL function: https://docs.databricks.com/en/sql/language-manual/functions/secret.html
- H3 cell areas by resolution: https://h3geo.org/docs/core-library/restable/
