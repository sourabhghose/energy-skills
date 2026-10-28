"""OSDU manifest record skeletons for canonical Well / Wellbore rows.

Purpose: turn canonical rows into OSDU storage-record dicts (id, kind, acl, legal, data) that
can be wrapped in a manifest for the OSDU manifest-ingestion workflow. Platform settings
(kind version, data-partition namespace, ACL groups, legal tags) are required arguments with
no defaults: they come from the target OSDU instance and are never invented here. Validate
records with the platform's Schema service before ingesting.

Usage:
    from osdu_records import to_osdu_records
    recs = to_osdu_records(canonical, "well", kind="osdu:wks:master-data--Well:1.2.0",
                           namespace="opendes", acl={"owners": [...], "viewers": [...]},
                           legal={"legaltags": [...], "otherRelevantDataCountries": ["US"]})
"""

from __future__ import annotations

import re

import pandas as pd

ENTITY_TYPES = {"well": "master-data--Well", "wellbore": "master-data--Wellbore"}
ID_SAFE = re.compile(r"[^A-Za-z0-9_\-.]")


def _clean(value):
    return None if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)) else value


def _ref(namespace: str, ref_type: str, code) -> str | None:
    return f"{namespace}:reference-data--{ref_type}:{code}:" if _clean(code) else None


def _record_id(namespace: str, entity: str, uwi: str) -> str:
    return f"{namespace}:{ENTITY_TYPES[entity]}:{ID_SAFE.sub('_', str(uwi))}"


def _spatial(row: dict, prefix: str) -> dict | None:
    lat, lon = _clean(row.get(f"{prefix}_latitude")), _clean(row.get(f"{prefix}_longitude"))
    crs = _clean(row.get("source_crs"))
    if lat is None or lon is None:
        return None
    return {"AsIngestedCoordinates": {
        "type": "AnyCrsFeatureCollection", "CoordinateReferenceSystemID": crs,
        "features": [{"type": "AnyCrsFeature",
                      "geometry": {"type": "AnyCrsPoint", "coordinates": [float(lon), float(lat)]}}]}}


def _well_data(row: dict, namespace: str) -> dict:
    data = {
        "FacilityName": _clean(row.get("well_name")),
        "NameAliases": [{"AliasName": row["well_uwi"], "AliasNameTypeID": _ref(namespace, "AliasNameType", "UWI")}],
        "SpatialLocation": _spatial(row, "surface"),
        "FacilityStates": ([{"FacilityStateTypeID": _ref(namespace, "FacilityStateType", row["well_status"])}]
                           if _clean(row.get("well_status")) else None),
    }
    return {k: v for k, v in data.items() if v is not None}


def _wellbore_data(row: dict, namespace: str) -> dict:
    data = {
        "FacilityName": _clean(row.get("wellbore_name")),
        "NameAliases": [{"AliasName": row["wellbore_uwi"],
                         "AliasNameTypeID": _ref(namespace, "AliasNameType", "UWI")}],
        "WellID": _record_id(namespace, "well", row["well_uwi"]) + ":" if _clean(row.get("well_uwi")) else None,
        "TrajectoryTypeID": _ref(namespace, "WellboreTrajectoryType", _clean(row.get("trajectory_type"))),
        "ProjectedBottomHoleLocation": _spatial(row, "bottom_hole"),
    }
    return {k: v for k, v in data.items() if v is not None}


def to_osdu_records(canonical: pd.DataFrame, entity: str, *, kind: str, namespace: str,
                    acl: dict, legal: dict) -> list[dict]:
    """One OSDU record dict per canonical row (well or wellbore)."""
    if entity not in ENTITY_TYPES:
        raise ValueError(f"OSDU record skeletons support {list(ENTITY_TYPES)}, not {entity!r}")
    if not all([kind, namespace, acl, legal]):
        raise ValueError("kind, namespace, acl and legal come from the target OSDU platform and are required")
    if ENTITY_TYPES[entity] not in kind:
        raise ValueError(f"kind {kind!r} does not match entity {entity!r}")
    key = "well_uwi" if entity == "well" else "wellbore_uwi"
    builder = _well_data if entity == "well" else _wellbore_data
    return [{"id": _record_id(namespace, entity, row[key]), "kind": kind, "acl": acl, "legal": legal,
             "data": builder(row, namespace)}
            for row in canonical.to_dict("records") if _clean(row.get(key))]
