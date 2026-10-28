# Energy model reference index

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/open-weight-models/references/models/index.md); modified for the energy industry. -->

Load only the card that matches the request. Licences verified on the Hugging Face API on
2026-10-28; re-verify before production use.

| Model | Modality | Weights licence | Commercial | Default deployment | Reference |
| --- | --- | --- | --- | --- | --- |
| Chronos-2 | time series + covariates | apache-2.0 | yes | CPU serving or batch Job | [chronos-2.md](chronos-2.md) |
| Chronos-Bolt | univariate time series | apache-2.0 | yes | CPU serving or batch Job | [chronos-bolt.md](chronos-bolt.md) |
| TimesFM 2.5 | long-context time series | apache-2.0 | yes | CPU/GPU serving or batch Job | [timesfm.md](timesfm.md) |
| Granite TTM r2 | point forecasts, telemetry | apache-2.0 | yes | batch Job | [granite-ttm.md](granite-ttm.md) |
| Moirai 2.0 | time series | cc-by-nc-4.0 | **NO** | research only | [moirai.md](moirai.md) |
| Prithvi-EO-2.0 | multispectral satellite imagery | apache-2.0 | yes | GPU batch Job | [prithvi-eo-2.md](prithvi-eo-2.md) |

Licence traps:

- **TimesFM 3.0** weights are under a non-commercial licence (2.5 and earlier are Apache-2.0).
- **Moirai** weights are CC-BY-NC-4.0 even though the uni2ts code is Apache-2.0.

Not covered:

- **Methane plume detection.** As of 2026-10-28 the Hugging Face search returns only small,
  unlicensed or CC-BY-NC community checkpoints. No card until a model with a clear
  commercial licence and published validation exists; treat plume detection as a custom
  training project (e.g. fine-tune a geospatial backbone on labelled plumes) and route
  inventory accounting to `ghg-emissions-calculator`.

To add a model: copy [model-template.md](../model-template.md), pin HF and code SHAs, record
both licences, add a row here and (for time series) a `CATALOG` entry in
`scripts/tsfm_catalog.py`.
