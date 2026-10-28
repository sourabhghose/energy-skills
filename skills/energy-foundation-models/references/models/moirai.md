# Salesforce Moirai 2.0 — NON-COMMERCIAL

## Identity

- Model family: Salesforce Moirai (decoder-only in 2.0; masked-encoder in 1.x; MoE variant)
- HF repo: Salesforce/moirai-2.0-R-small
- HF revision: 30f43ff08c8494f4943ae1521e9d4e94a0fbb389
- Code repo: https://github.com/SalesforceAIResearch/uni2ts
- Code revision: cfd46d4510ed8896f263116f32928eede05b0a75 (latest release 2.0.0)
- Weights license: cc-by-nc-4.0
- Code license: Apache-2.0
- Commercial use: NO (non-commercial)
- Reviewed: 2026-10-28

Also non-commercial: `Salesforce/moirai-1.1-R-small` and `Salesforce/moirai-moe-1.0-R-small`
(both `cc-by-nc-4.0`). The model card adds: "This release is for research purposes only."
The Apache-2.0 code licence does **not** extend to the weights.

## Energy use cases

- Research benchmarking and academic comparisons only. A utility, IPP, or trading firm
  forecasting its own load, prices, or output is commercial use — choose Chronos-2,
  Chronos-Bolt, TimesFM 2.5, or TTM instead.

## Integration contract

- `config.json`: `max_seq_len` 512 patches × `patch_size` 16 = 8192 points shared between
  context and horizon; native quantiles are deciles 0.1 … 0.9.
- Inference through `uni2ts` (`Moirai2Forecast` + `Moirai2Module.from_pretrained`) with
  explicit `context_length` and `prediction_length`.

## Artifacts and runtime

- `uni2ts` from git at the pinned commit. Many Models Forecasting reports (Feb 2026) that
  uni2ts requires `torch<2.5`, incompatible with current Databricks Runtimes, and disabled
  Moirai for that reason. Expect a custom environment.

## Wrapper boundary

No adapter in this skill. `build_manifest` will accept it only with an explicit licence
acceptance, and `preview` flags it unusable when `commercial_use=True`.

## Deployment recommendation

Do not deploy to production endpoints. Research notebooks only.

## Pitfalls

1. Reading "Apache-2.0" on the GitHub repo and assuming the weights are too.
2. Runtime conflict on torch versions.

## Validation

Only for research comparisons; same backtest protocol as the other models.
