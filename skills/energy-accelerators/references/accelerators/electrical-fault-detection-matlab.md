# Electrical fault detection with MATLAB Simulink

## Identity

- Name: Electrical fault detection with MATLAB Simulink
- Kind: accelerator
- URL: https://github.com/databricks-industry-solutions/electrical-fault-detection-matlab
- Install doc: notebooks `00_context.py` … `03_classification_model.py`
- Maintainers: see repo contributors
- Licence: Databricks License
- Last updated: 2025-01-27
- Maturity: stale (>18 months)
- Reviewed: 2026-10-28 against commit 204cdbd

## Use it for

- Generating labelled fault data by simulating faults on the IEEE 123 Node Test Feeder in Simulink, then training a fault classification model on Databricks

## Do not use it for

- Real relay records: see `comtrade-accelerator`
- Equipment condition monitoring from historian tags: use `equipment-pdm`

## Data

Simulated fault data written to Delta by notebook 02.

## Deploy signals

Not documented.

## Smallest path

If you already have simulated data, start at `03_classification_model.py`.

## Pitfalls

1. Data generation needs MATLAB and Simulink (MathWorks licences) available to the compute.
2. README DBR badge is a placeholder (`CHANGE_ME`); test on your runtime.

## Pair with Energy Skills

`comtrade-accelerator`, `equipment-pdm`
