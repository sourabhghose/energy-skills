# Analyzing electrical grid assets with computer vision

## Identity

- Name: Analyzing electrical grid assets with computer vision
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/utilities-cv
- Install doc: `RUNME.py` notebook
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2024-03-16
- Maturity: stale (>18 months)
- Reviewed: 2026-10-28 against commit 6df13d9

## Use it for

- Detecting distribution assets (and damage) in drone imagery; multi-GPU segmentation model training and inference
- Reconciling field reality with GIS asset records

## Do not use it for

- 30 m multispectral satellite imagery (burn scars, floods, vegetation): use `energy-foundation-models` (Prithvi)
- Vegetation-encroachment risk scoring: use `wildfire-asset-risk`

## Data

Downloads a labelled drone-image dataset into UC (notebook 01).

## Deploy signals

Job created by `RUNME.py`.

## Smallest path

Run `01_DownloadData` and `02_CreateTables`, then `03_MultiGPU_ModelTraining` on a GPU cluster.

## Pitfalls

1. Last commit March 2024; pinned libraries (pytorch-lightning, segmentation-models-pytorch) may need updates on current ML runtimes.
2. Multi-GPU training requires classic GPU clusters.

## Pair with Energy Skills

`wildfire-asset-risk`, `energy-foundation-models`
