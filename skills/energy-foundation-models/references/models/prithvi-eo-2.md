# Prithvi-EO-2.0 (NASA / IBM geospatial foundation model)

## Identity

- Model family: Prithvi-EO-2.0 (ViT MAE with 3D patch embeddings; 100M / 300M / 600M, `-TL` = time + location embeddings)
- HF repo: ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL
- HF revision: 63adbd39c271da4c42f447e69b1a7c91a338cdc9
- Code repo: https://github.com/NASA-IMPACT/Prithvi-EO-2.0 (examples) and https://github.com/torchgeo/terratorch (fine-tuning)
- Code revision: 758311280f935d4775c05b26d792768bf1fda841 (Prithvi-EO-2.0); terratorch 89a3ed13d7a6272c009c4c5fbabf62461fcfb16c (release v1.2.13)
- Weights license: apache-2.0
- Code license: MIT (NASA-IMPACT/Prithvi-EO-2.0), Apache-2.0 (terratorch)
- Commercial use: yes
- Reviewed: 2026-10-28

Fine-tuned heads (all apache-2.0, verified on the HF API):

| repo | revision | energy use |
|---|---|---|
| ibm-nasa-geospatial/Prithvi-EO-2.0-300M-BurnScars | a3f2c410e45b8ac7417976614528a872f024d831 | burn-scar mapping near lines and substations; post-fire asset inspection |
| ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11 | 91ce9d38086a80b078a192b374df758b8855b732 | flood extent over substations, well pads, pipelines |
| ibm-nasa-geospatial/Prithvi-EO-2.0-300M | 9eb1b1102806593963daa333bcc491b1c6f8562f | backbone for custom heads (vegetation encroachment, land cover for solar siting) |
| ibm-nasa-geospatial/Prithvi-EO-2.0-600M | 2a5cf6cedea1c0b31734021e2a5ac90082825414 | larger backbone |

## Energy use cases

- Wildfire: burn scars and vegetation condition along transmission corridors (feeds
  `wildfire-asset-risk`).
- Flood: inundation over grid and upstream/midstream assets (compare the `flood-prediction`
  accelerator in `energy-accelerators`).
- Solar / wind siting land-cover features; post-storm damage triage.
- Not for: methane plume detection (different sensors and physics; see index), sub-meter
  asset inspection from drones (see `utilities-cv` accelerator).

## Integration contract

- Six bands in fixed order: Blue, Green, Red, Narrow NIR, SWIR 1, SWIR 2. `config.json`
  names them with **HLS L30** codes `B02 B03 B04 B05 B06 B07`. In **HLS S30** (Sentinel-2)
  the same bands are `B02 B03 B04 B8A B11 B12`.
- Units: normalization means in `config.json` are ~1000–2700, i.e. reflectance × 10000.
- Chips: `img_size` 224, `num_frames` 4 by default (multi-temporal, chronological).
- TL variants consume acquisition date and centre lat/lon.
- Transport: a chip manifest of governed `/Volumes/...` GeoTIFF URIs, validated by
  `scripts/geo_contract.py`; never inline rasters in an HTTP payload.

## Artifacts and runtime

- `terratorch` (pin), `torch`, `rasterio`; checkpoint `Prithvi_EO_V2_300M_TL.pt` (~1.3 GB).
- GPU strongly recommended (T4/A10G for inference; larger for fine-tuning).

## Wrapper boundary

Batch Job: read the chip manifest, validate with `validate_chip_manifest`, load the
backbone via `terratorch.registry.BACKBONE_REGISTRY.build("prithvi_eo_v2_300_tl", pretrained=...)`
(or the fine-tuned task model), write per-chip masks back to a Volume and per-asset
summaries (e.g. burned share within 100 m of each structure) to a UC table.

## Deployment recommendation

**Jobs, not Model Serving**: inputs are large rasters, outputs are rasters, latency is not
critical. Expose results to apps through tables.

## Pitfalls

1. Mixing S30 band codes with L30 codes (B05–B07 are red-edge in Sentinel-2).
2. Feeding 0–1 reflectance without ×10000 before normalization.
3. Cloud and shadow: mask with the HLS Fmask layer before inference.
4. Asset coordinates of substations are often CEII; keep asset-level outputs governed.

## Validation

Chip manifest contract tests (offline); IoU against a labelled sample of local fire or
flood polygons; visual QA on a handful of chips per region.
