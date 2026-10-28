"""Canonical upstream entities with their OSDU and PPDM targets, plus reference value lists.

Purpose: the target side of every mapping. Each canonical field records its type, whether it
is required, the OSDU well-known-schema (WKS) data-block path it lands in, the PPDM 3.9-style
column, and name synonyms used to propose source columns. OSDU paths follow the community
master-data--Well / master-data--Wellbore / work-product-component--WellLog schemas; verify
them against the schema version deployed on your OSDU platform before ingesting.

Usage:
    from canonical_model import ENTITIES, field_names, REFERENCE_LISTS
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    dtype: str            # string | double | date | int
    required: bool
    osdu_path: str
    ppdm_column: str
    synonyms: tuple[str, ...] = ()
    kind: str = "plain"   # plain | identifier | latitude | longitude | depth | status | fluid | crs


def _f(name, dtype, required, osdu, ppdm, synonyms=(), kind="plain") -> Field:
    return Field(name, dtype, required, osdu, ppdm, tuple(synonyms), kind)


WELL = (
    _f("well_uwi", "string", True, "data.NameAliases[UWI].AliasName", "WELL.UWI",
       ("uwi", "api", "api10", "api_no", "api_number", "well_id", "wellid", "well_api"), "identifier"),
    _f("well_name", "string", True, "data.FacilityName", "WELL.WELL_NAME", ("well_name", "name", "lease_well", "wellname")),
    _f("operator_name", "string", False, "data.FacilityOperators[].FacilityOperatorOrganisationID",
       "WELL.OPERATOR", ("operator", "operator_name", "current_operator", "company")),
    _f("country", "string", False, "data.GeoContexts[Country].GeoPoliticalEntityID", "WELL.COUNTRY", ("country",)),
    _f("state_province", "string", False, "data.GeoContexts[StateProvince].GeoPoliticalEntityID",
       "WELL.PROVINCE_STATE", ("state", "province", "state_province")),
    _f("county", "string", False, "data.GeoContexts[County].GeoPoliticalEntityID", "WELL.COUNTY", ("county", "parish")),
    _f("field_name", "string", False, "data.GeoContexts[Field].FieldID", "WELL.ASSIGNED_FIELD", ("field", "field_name")),
    _f("surface_latitude", "double", False, "data.SpatialLocation.AsIngestedCoordinates (y)",
       "WELL.SURFACE_LATITUDE", ("lat", "latitude", "surface_lat", "surf_lat", "shl_lat"), "latitude"),
    _f("surface_longitude", "double", False, "data.SpatialLocation.AsIngestedCoordinates (x)",
       "WELL.SURFACE_LONGITUDE", ("lon", "long", "longitude", "surface_lon", "surf_long", "shl_lon"), "longitude"),
    _f("spud_date", "date", False, "data.FacilityEvents[Spud].EffectiveDateTime", "WELL.SPUD_DATE",
       ("spud", "spud_date", "spud_dt")),
    _f("well_status", "string", False, "data.FacilityStates[].FacilityStateTypeID", "WELL.CURRENT_STATUS",
       ("status", "well_status", "current_status"), "status"),
    _f("elevation_reference", "string", False, "data.VerticalMeasurements[].VerticalMeasurementTypeID",
       "WELL.DEPTH_DATUM", ("elev_ref", "datum", "depth_datum", "elevation_reference")),
    _f("elevation_value", "double", False, "data.VerticalMeasurements[].VerticalMeasurement",
       "WELL.DEPTH_DATUM_ELEV", ("elevation", "kb_elev", "kb", "gl_elev", "elev"), "depth"),
)

WELLBORE = (
    _f("wellbore_uwi", "string", True, "data.NameAliases[UWI].AliasName", "WELL.UWI (wellbore component)",
       ("api12", "api_12", "api", "api_no", "api_number", "wellbore_id", "wellbore_uwi", "sidetrack_api", "uwi"), "identifier"),
    _f("well_uwi", "string", True, "data.WellID", "WELL.PARENT_UWI", ("api10", "api", "api_no", "api_number", "parent_api", "well_id", "well_uwi", "uwi"),
       "identifier"),
    _f("wellbore_name", "string", False, "data.FacilityName", "WELL.WELL_NAME", ("wellbore_name", "name", "bore_name", "well_name", "lease_well")),
    _f("trajectory_type", "string", False, "data.TrajectoryTypeID", "WELL.PROFILE_TYPE",
       ("trajectory", "profile", "drill_type", "hole_direction", "well_type")),
    _f("total_depth_md", "double", False, "data.VerticalMeasurements[TotalDepth MD].VerticalMeasurement",
       "WELL.DRILL_TD", ("td", "td_md", "total_depth", "md", "measured_depth"), "depth"),
    _f("total_depth_tvd", "double", False, "data.VerticalMeasurements[TotalDepth TVD].VerticalMeasurement",
       "WELL.FINAL_TD (TVD)", ("tvd", "td_tvd", "true_vertical_depth"), "depth"),
    _f("bottom_hole_latitude", "double", False, "data.ProjectedBottomHoleLocation (y)", "WELL.BOTTOM_HOLE_LATITUDE",
       ("bhl_lat", "bh_lat", "bottom_hole_lat"), "latitude"),
    _f("bottom_hole_longitude", "double", False, "data.ProjectedBottomHoleLocation (x)", "WELL.BOTTOM_HOLE_LONGITUDE",
       ("bhl_lon", "bh_long", "bottom_hole_lon"), "longitude"),
    _f("wellbore_status", "string", False, "data.FacilityStates[].FacilityStateTypeID", "WELL.CURRENT_STATUS",
       ("status", "wellbore_status"), "status"),
)

COMPLETION = (
    _f("completion_id", "string", True, "data.NameAliases[UWI].AliasName (completion)",
       "WELL_COMPLETION.COMPLETION_OBS_NO", ("api14", "api_14", "api", "api_no", "api_number", "completion_id", "comp_id"), "identifier"),
    _f("wellbore_uwi", "string", True, "data.WellboreID", "WELL_COMPLETION.UWI", ("api12", "api", "api_no", "api_number", "wellbore_id", "wellbore_uwi"),
       "identifier"),
    _f("top_md", "double", False, "data.TopMeasuredDepth", "WELL_COMPLETION.TOP_DEPTH", ("top", "top_md", "perf_top"), "depth"),
    _f("base_md", "double", False, "data.BaseMeasuredDepth", "WELL_COMPLETION.BASE_DEPTH",
       ("base", "bottom", "base_md", "perf_btm", "perf_base"), "depth"),
    _f("formation", "string", False, "data.GeologicUnitInterpretationIDs[]", "WELL_COMPLETION.COMPLETION_STRAT_UNIT_ID",
       ("formation", "zone", "reservoir", "producing_formation")),
    _f("completion_date", "date", False, "data.FacilityEvents[Completion].EffectiveDateTime",
       "WELL_COMPLETION.COMPLETION_DATE", ("completion_date", "comp_date")),
    _f("primary_fluid", "string", False, "data.ProductionFluidTypeID (where supported)",
       "WELL_COMPLETION.PRODUCTION_FLUID", ("fluid", "product", "well_type", "primary_product"), "fluid"),
)

PRODUCTION = (
    _f("reporting_entity_id", "string", True, "(production volumes are not a core OSDU WKS; see references)",
       "PDEN_VOL_SUMMARY.PDEN_ID", ("api", "api14", "uwi", "entity_id", "lease_id", "well_id", "completion_id"),
       "identifier"),
    _f("period_start", "date", True, "-", "PDEN_VOL_SUMMARY.PERIOD_ID (start)", ("prod_date", "month", "period", "date")),
    _f("oil_volume", "double", False, "-", "PDEN_VOL_SUMMARY.VOLUME (oil)", ("oil", "oil_bbl", "oil_vol", "liquid")),
    _f("gas_volume", "double", False, "-", "PDEN_VOL_SUMMARY.VOLUME (gas)", ("gas", "gas_mcf", "gas_vol")),
    _f("water_volume", "double", False, "-", "PDEN_VOL_SUMMARY.VOLUME (water)", ("water", "water_bbl", "wtr")),
)

ENTITIES: dict[str, tuple[Field, ...]] = {
    "well": WELL, "wellbore": WELLBORE, "completion": COMPLETION, "production": PRODUCTION,
}

REFERENCE_LISTS: dict[str, dict[str, tuple[str, ...]]] = {
    "status": {
        "PLANNED": ("planned", "proposed", "location"),
        "PERMITTED": ("permitted", "permit", "approved", "apd"),
        "DRILLING": ("drilling", "spudded", "active drilling"),
        "COMPLETED": ("completed", "completion", "drilled and completed"),
        "PRODUCING": ("producing", "active", "prod", "pr", "flowing", "on production"),
        "INJECTING": ("injecting", "injection", "inj", "swd", "disposal"),
        "SHUT_IN": ("shut in", "shut-in", "si", "shutin", "inactive"),
        "TEMPORARILY_ABANDONED": ("ta", "temporarily abandoned", "temp abandoned"),
        "PLUGGED_AND_ABANDONED": ("pa", "p&a", "plugged and abandoned", "plugged", "abandoned"),
        "DRY_HOLE": ("dry", "dry hole", "d&a", "dry and abandoned"),
    },
    "fluid": {
        "OIL": ("oil", "o", "crude"),
        "GAS": ("gas", "g", "natural gas"),
        "CONDENSATE": ("condensate", "cond", "gas condensate"),
        "WATER": ("water", "w", "swd", "saltwater"),
        "OIL_AND_GAS": ("oil & gas", "o&g", "og", "oil and gas"),
        "CO2": ("co2", "carbon dioxide"),
        "STEAM": ("steam",),
    },
}

TARGET_STANDARDS: tuple[str, ...] = ("osdu", "ppdm", "both")


def field_names(entity: str) -> list[str]:
    return [f.name for f in fields(entity)]


def fields(entity: str) -> tuple[Field, ...]:
    if entity not in ENTITIES:
        raise ValueError(f"unknown entity {entity!r}; choose one of {list(ENTITIES)}")
    return ENTITIES[entity]


def get_field(entity: str, name: str) -> Field:
    for f in fields(entity):
        if f.name == name:
            return f
    raise KeyError(f"{entity}.{name} is not a canonical field")
