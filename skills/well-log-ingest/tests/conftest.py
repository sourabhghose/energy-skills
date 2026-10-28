"""Put this skill's scripts/ on sys.path so tests import the vetted modules directly."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SAMPLE_LAS = """~Version Information
 VERS.                 2.0 :   CWLS LOG ASCII STANDARD - VERSION 2.0
 WRAP.                  NO :   ONE LINE PER DEPTH STEP
~Well Information
 STRT.F             5000.0 :   START DEPTH
 STOP.F             5002.0 :   STOP DEPTH
 STEP.F                0.5 :   STEP
 NULL.             -999.25 :   NULL VALUE
 COMP.        DEMO ENERGY  :   COMPANY
 WELL.      SMITH 1H       :   WELL
 FLD .      WOLFCAMP       :   FIELD
 API .    05-123-45678     :   API NUMBER
 DATE.      2024-03-02     :   LOG DATE
 EKB .F             5125.0 :   KELLY BUSHING ELEVATION
 EGL .F             5100.0 :   GROUND LEVEL ELEVATION
 LMF .      KB             :   LOG MEASURED FROM
~Curve Information
 DEPT.F                    :   DEPTH
 GR  .GAPI                 :   GAMMA RAY
 RHOZ.K/M3                 :   BULK DENSITY
 TNPH.                     :   NEUTRON POROSITY
 AT90.OHMM                 :   DEEP RESISTIVITY
 GR  .GAPI                 :   GAMMA RAY REPEAT
~ASCII
 5000.0   45.2  2450.0  18.5   12.1  44.0
 5000.5   60.1  2460.0  21.0 -999.25  59.0
 5001.0 -9999.0 2470.0  22.5   10.4  77.0
 5001.5   80.3  2480.0  24.0    9.8  80.0
 5002.0   90.0  2490.0  25.5    9.1  90.5
"""


def make_parsed(source="a.las", api="05-123-45678", curves=None, data=None, well_extra=None,
                depth_unit="F", log_date="2024-03-02"):
    """Build a ParsedLas directly (no lasio) for core tests."""
    from las_parse import CurveInfo, HeaderItem, ParsedLas

    curves = curves or [("DEPT", "F"), ("GR", "GAPI"), ("RHOZ", "K/M3"), ("TNPH", ""), ("AT90", "OHMM")]
    curves = [(curves[0][0], depth_unit)] + list(curves[1:])
    data = data if data is not None else np.array([
        [5000.0, 45.2, 2450.0, 18.5, 12.1],
        [5000.5, 60.1, 2460.0, 21.0, np.nan],
        [5001.0, -9999.0, 2470.0, 22.5, 10.4],
        [5001.5, 80.3, 2480.0, 24.0, 9.8],
    ])
    well = {"API": HeaderItem("API", "", api, ""), "WELL": HeaderItem("WELL", "", "SMITH 1H", ""),
            "EKB": HeaderItem("EKB", "F", "5125.0", ""), "EGL": HeaderItem("EGL", "F", "5100.0", ""),
            "LMF": HeaderItem("LMF", "", "KB", ""), "DATE": HeaderItem("DATE", "", log_date, ""),
            "NULL": HeaderItem("NULL", "", "-999.25", "")}
    well.update(well_extra or {})
    infos = tuple(CurveInfo(m, m.split(":")[0], u, "") for m, u in curves)
    frame = pd.DataFrame(data, columns=[m for m, _ in curves])
    return ParsedLas(source=source, sha256="x", version="2.0", wrap=False, well=well, params={},
                     curves=infos, data=frame, null_value=-999.25)


def decisions(**over):
    from las_core import IngestDecisions

    base = dict(sentinel_policy="common_sentinels", depth_unit="ft", depth_datum="as_logged",
                family_conflict_policy="keep_all", unit_resolution={"TNPH": "PU"}, api_zero_pad="pad")
    return IngestDecisions.from_kwargs(**{**base, **over})
