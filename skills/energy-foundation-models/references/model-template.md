# Energy model card template

<!-- Adapted from databricks-industry-solutions/vital-skills (skills/open-weight-models/references/model-template.md); modified for the energy industry. -->

Copy to `references/models/<model>.md`, replace every placeholder, add a row to
`references/models/index.md`, and (for time-series models) an entry in `scripts/tsfm_catalog.py`.
`tests/test_model_cards.py` checks that every card has these sections and identity fields.

## Identity

- Model family:
- HF repo:
- HF revision: <40-char commit SHA from https://huggingface.co/api/models/<repo>>
- Code repo:
- Code revision: <40-char commit SHA>
- Weights license:
- Code license:
- Commercial use: yes | NO (non-commercial)
- Reviewed: <YYYY-MM-DD>

## Energy use cases

Which energy problems this model fits (load, price, renewable output, production, imagery),
and which it does not.

## Integration contract

Native input shape, context length, maximum horizon, native quantile levels, covariate
support (none / past-only / known-future), supported frequencies, scaling requirements,
missing-value handling, and the Databricks transport representation (long-format frame,
governed Volume URI, ...).

## Artifacts and runtime

Packages and pins, checkpoint files, CPU vs GPU, memory, and whether the model can run
fully offline once staged to a UC Volume.

## Wrapper boundary

What `load_context` loads, what `predict` does, and which upstream call the adapter makes.

## Deployment recommendation

Model Serving, batch Job, or hybrid, with the reason.

## Pitfalls

Energy-specific failure modes, each with the fix.

## Validation

Smoke, contract, backtest (vs seasonal naive), and negative tests specific to this model.
