"""Input contract for Prithvi-EO-2.0 batch inference on satellite chips (pure Python).

Prithvi-EO-2.0 was pretrained on NASA Harmonized Landsat Sentinel-2 (HLS V2, 30 m) with six
bands in a fixed order. Feeding Sentinel-2 L1C digital numbers, RGB-only imagery, or a
different band order produces confident garbage, so validate the chip manifest before a
Job spends GPU hours on it.

Chip manifest (one row per chip; files live in a governed UC Volume):
    chip_uri        /Volumes/<catalog>/<schema>/<volume>/... GeoTIFF path
    bands           comma-separated band names in file order
    height, width   pixels
    n_timesteps     number of acquisitions stacked in the chip
    units           'reflectance' (0-1) or 'reflectance_x10000' (HLS scaled integers). The
                    checkpoint's normalization means (~1000-2700) are in x10000 units, so
                    0-1 reflectance must be multiplied by 10000 before normalizing.
    acquired_dates  comma-separated ISO dates, chronological
    crs             e.g. EPSG:32614

Usage:
    from geo_contract import validate_chip_manifest
    problems = validate_chip_manifest(manifest_df, variant="300M-TL")
"""

from __future__ import annotations

import re

import pandas as pd

PRITHVI_BANDS = ("BLUE", "GREEN", "RED", "NIR_NARROW", "SWIR_1", "SWIR_2")
# config.json lists HLS L30 (Landsat) codes B02..B07. HLS S30 (Sentinel-2) uses different
# codes for the same physical bands: B8A is narrow NIR, B11/B12 are SWIR. Mixing them up
# (e.g. passing S30 B05-B07, which are red-edge bands) silently breaks the model.
BAND_ALIASES = {
    "HLS_L30": ("B02", "B03", "B04", "B05", "B06", "B07"),
    "HLS_S30": ("B02", "B03", "B04", "B8A", "B11", "B12"),
}
VOLUME_URI = re.compile(r"^/Volumes/[A-Za-z0-9_]+/[A-Za-z0-9_]+/[A-Za-z0-9_]+/.+\.tif{1,2}$")
ALLOWED_UNITS = ("reflectance", "reflectance_x10000")
CHIP_SIZE = 224  # fine-tuning examples use 224 x 224 chips; confirm per downstream head


def _bands_ok(bands: tuple[str, ...]) -> bool:
    return bands == PRITHVI_BANDS or bands in BAND_ALIASES.values()


def _row_problems(row: pd.Series, needs_dates: bool) -> list[str]:
    problems = []
    if not VOLUME_URI.match(str(row["chip_uri"])):
        problems.append("chip_uri is not a GeoTIFF under /Volumes/<catalog>/<schema>/<volume>/")
    bands = tuple(b.strip().upper() for b in str(row["bands"]).split(","))
    if not _bands_ok(bands):
        problems.append(f"band order {bands} matches none of {PRITHVI_BANDS} / {BAND_ALIASES}")
    if (int(row["height"]), int(row["width"])) != (CHIP_SIZE, CHIP_SIZE):
        problems.append(f"chip is {row['height']}x{row['width']}, expected {CHIP_SIZE}x{CHIP_SIZE}")
    if row["units"] not in ALLOWED_UNITS:
        problems.append(f"units {row['units']!r} not in {ALLOWED_UNITS}")
    dates = [d for d in str(row.get("acquired_dates") or "").split(",") if d]
    if len(dates) != int(row["n_timesteps"]):
        problems.append(f"{len(dates)} acquisition dates for {row['n_timesteps']} timesteps")
    elif dates != sorted(dates):
        problems.append("acquisition dates are not chronological")
    if needs_dates and not dates:
        problems.append("TL variants need acquisition dates and location for temporal/location embeddings")
    return problems


def validate_chip_manifest(manifest: pd.DataFrame, variant: str) -> list[str]:
    """Return problems (empty list == ready). variant like '300M', '300M-TL', '600M-TL'."""
    required = {"chip_uri", "bands", "height", "width", "n_timesteps", "units", "acquired_dates", "crs"}
    missing = required - set(manifest.columns)
    if missing:
        return [f"manifest missing columns: {sorted(missing)}"]
    needs_dates = variant.upper().endswith("-TL")
    out = []
    for i, row in manifest.iterrows():
        out.extend(f"row {i} ({row['chip_uri']}): {p}" for p in _row_problems(row, needs_dates))
    if manifest["crs"].nunique() > 1:
        out.append("chips span multiple CRSs; reproject to one CRS per Job run")
    return out
