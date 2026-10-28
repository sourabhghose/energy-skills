"""Energy semantic layer core: catalog loading, validation, scope inference, SQL generation.

Purpose
    Pure Python + PyYAML. Loads the canonical model, decision registry and measure catalog
    from ../references, validates the catalog, infers which metric views a customer mapping
    can support, and generates:
        01_silver.sql        one conforming view per mapped entity
        03_metric_views.sql  one CREATE VIEW ... WITH METRICS LANGUAGE YAML per metric view
        plan.md              built vs. skipped, with reasons
        manifest.json        decisions, mapping, catalog version, skill version
    Decision placeholders ({gas_mcf_per_boe}, {gads_weighting}) are substituted from the
    user's confirmed decisions; nothing has a default.

Usage
    from semantic_core import load_catalog, validate_catalog, plan_scope, generate
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
REFS = SKILL_ROOT / "references"
MV_RE = re.compile(r"^mv_([a-z0-9_]+?)__[a-z0-9_]+$")
MEASURE_RE = re.compile(r"MEASURE\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
QUOTED_RE = re.compile(r"'[^']*'")
UC_NAME = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
REQUIRED_KEYS = {"name", "type", "metric_view", "expr", "definition", "unit"}
SQL_WORDS = {
    "count", "distinct", "case", "when", "then", "else", "end", "sum", "avg", "min", "max",
    "and", "or", "not", "null", "cast", "as", "coalesce", "is", "in", "true", "false",
    "measure", "nullif", "abs", "round", "if", "between", "like",
}


class DecisionRequired(ValueError):
    """A decision that belongs to the customer was not supplied."""

    def __init__(self, decision: str, options, question: str):
        super().__init__(f"Decision required: '{decision}' — {question} Options: {list(options)}")
        self.decision = decision
        self.options = list(options)


@dataclass(frozen=True)
class Catalog:
    entities: dict
    decisions: dict
    metric_views: dict          # name -> {entity, grain, domain}
    measures: tuple             # measure dicts (with _domain, _file)
    version: str = "0.1.0"

    def measures_for(self, mv: str) -> list[dict]:
        return [m for m in self.measures if m["metric_view"] == mv]


@dataclass
class ValidationReport:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _load(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_catalog(refs: Path = REFS) -> Catalog:
    canon = _load(refs / "canonical_model.yaml")
    decisions = _load(refs / "decisions.yaml").get("decisions", {})
    mvs, measures = {}, []
    for f in sorted((refs / "measure_catalog").glob("*.yaml")):
        doc = _load(f)
        domain = doc.get("domain") or f.stem
        for mv in doc.get("metric_views") or []:
            mvs[mv["name"]] = {"entity": mv.get("entity"), "grain": mv.get("grain"),
                               "domain": domain}
        measures.extend({**m, "_domain": domain, "_file": f.name} for m in doc.get("measures") or [])
    return Catalog(canon.get("entities", {}), decisions, mvs, tuple(measures),
                   str(canon.get("version", "0.1.0")))


# --------------------------------------------------------------------------- validation

def _field_refs(expr: str) -> set[str]:
    bare = PLACEHOLDER_RE.sub(" ", QUOTED_RE.sub(" ", expr))
    return {t for t in IDENT_RE.findall(bare) if t.lower() not in SQL_WORDS}


def _check_measure(m: dict, cat: Catalog, rep: ValidationReport) -> None:
    tag = f"[{m['_file']}] {m.get('name', '<unnamed>')}"
    missing = REQUIRED_KEYS - m.keys()
    if missing:
        rep.errors.append(f"{tag}: missing keys {sorted(missing)}")
        return
    mo = MV_RE.match(m["metric_view"])
    if not mo or mo.group(1) != m["_domain"]:
        rep.errors.append(f"{tag}: metric_view '{m['metric_view']}' must be mv_{m['_domain']}__<name>")
    if m["metric_view"] not in cat.metric_views:
        rep.errors.append(f"{tag}: metric_view '{m['metric_view']}' is not declared")
    _check_placeholders(m, cat, rep, tag)
    if m["type"] == "atomic":
        _check_atomic(m, cat, rep, tag)
    elif m["type"] == "composite":
        _check_composite(m, cat, rep, tag)
    else:
        rep.errors.append(f"{tag}: unknown type '{m['type']}'")


def _check_placeholders(m: dict, cat: Catalog, rep: ValidationReport, tag: str) -> None:
    used = set(PLACEHOLDER_RE.findall(m["expr"]))
    declared = set(m.get("decisions") or [])
    for p in used - set(cat.decisions):
        rep.errors.append(f"{tag}: placeholder {{{p}}} not in decisions.yaml")
    if used != declared:
        rep.errors.append(f"{tag}: placeholders {sorted(used)} != decisions {sorted(declared)}")


def _check_atomic(m: dict, cat: Catalog, rep: ValidationReport, tag: str) -> None:
    ent = m.get("entity")
    if ent not in cat.entities:
        rep.errors.append(f"{tag}: atomic entity '{ent}' not in canonical model")
        return
    if "MEASURE(" in m["expr"]:
        rep.errors.append(f"{tag}: atomic measures must not use MEASURE()")
    declared_entity = cat.metric_views.get(m["metric_view"], {}).get("entity")
    if declared_entity and declared_entity != ent:
        rep.errors.append(f"{tag}: entity '{ent}' != metric view entity '{declared_entity}'")
    fields = set(cat.entities[ent].get("fields", {}))
    for ref in _field_refs(m["expr"]) - fields:
        rep.warnings.append(f"{tag}: '{ref}' is not a field of '{ent}'")


def _check_composite(m: dict, cat: Catalog, rep: ValidationReport, tag: str) -> None:
    refs = set(MEASURE_RE.findall(m["expr"]))
    if not refs:
        rep.errors.append(f"{tag}: composite without MEASURE() (non-additive trap)")
    local = {x["name"] for x in cat.measures_for(m["metric_view"])}
    for r in refs - local:
        rep.errors.append(f"{tag}: MEASURE({r}) not defined in {m['metric_view']}")
    if refs != set(m.get("depends_on") or []):
        rep.errors.append(f"{tag}: depends_on {sorted(m.get('depends_on') or [])} != MEASURE refs {sorted(refs)}")


def validate_catalog(cat: Catalog) -> ValidationReport:
    rep = ValidationReport()
    seen = set()
    for m in cat.measures:
        key = (m.get("metric_view"), m.get("name"))
        if key in seen:
            rep.errors.append(f"duplicate measure {key}")
        seen.add(key)
        _check_measure(m, cat, rep)
    for name, mv in cat.metric_views.items():
        if mv["entity"] not in cat.entities:
            rep.errors.append(f"metric view {name}: unknown entity '{mv['entity']}'")
    return rep


# --------------------------------------------------------------------------- scope

def _defaulted(spec: dict) -> set[str]:
    return {f for f, s in (spec.get("fields") or {}).items() if "default_if_unmapped" in s}


def mapped_fields(mapping: dict, entities: dict | None = None) -> dict[str, set]:
    """Fields each mapped entity provides (mapped, enum, or defaulted when unmapped)."""
    out = {}
    for entity, emap in (mapping.get("entities") or {}).items():
        have = set((emap.get("fields") or {})) | set((emap.get("enums") or {}))
        out[entity] = have | _defaulted((entities or {}).get(entity, {}))
    return out


def _resolve_measures(measures: list[dict], have: set, fields: set) -> tuple[list, list]:
    """Atomics survive when their fields are mapped; composites when their deps survive."""
    survived, emitted, skipped = set(), [], []
    for m in (x for x in measures if x["type"] == "atomic"):
        missing = (_field_refs(m["expr"]) & fields) - have
        if missing:
            skipped.append(f"{m['name']} (unmapped {sorted(missing)})")
        else:
            survived.add(m["name"])
            emitted.append(m)
    for m in (x for x in measures if x["type"] == "composite"):
        need = set(m.get("depends_on") or [])
        if need <= survived:
            survived.add(m["name"])
            emitted.append(m)
        else:
            skipped.append(f"{m['name']} (needs {sorted(need - survived)})")
    return emitted, skipped


def plan_scope(cat: Catalog, mapping: dict) -> dict:
    """Which metric views / measures the mapping supports, and which decisions they need."""
    avail = {e: f for e, f in mapped_fields(mapping, cat.entities).items() if e in cat.entities}
    domains = set((mapping.get("scope") or {}).get("domains") or [])
    views = {}
    for name, mv in sorted(cat.metric_views.items()):
        if domains and mv["domain"] not in domains:
            continue
        ent = mv["entity"]
        if ent not in avail:
            views[name] = {"built": False, "reason": f"entity '{ent}' not mapped"}
            continue
        fields = set(cat.entities[ent]["fields"])
        emitted, skipped = _resolve_measures(cat.measures_for(name), avail[ent], fields)
        views[name] = {"built": bool(emitted), "entity": ent, "measures": emitted,
                       "skipped": skipped, "have": avail[ent],
                       "reason": "" if emitted else "no measures survived"}
    return {"views": views, "decisions_needed": _decisions_needed(cat, views, avail)}


def _decisions_needed(cat: Catalog, views: dict, avail: dict) -> list[str]:
    needed = set()
    for v in views.values():
        for m in v.get("measures", []):
            needed |= set(m.get("decisions") or [])
    all_fields = set().union(*avail.values()) if avail else set()
    for name, d in cat.decisions.items():
        if d.get("kind") == "attestation" and set(d.get("fields") or []) & all_fields:
            needed.add(name)
    return sorted(needed)


def require_decisions(cat: Catalog, needed: list[str], decisions: dict | None) -> dict:
    """Validate the user's choices; return {name: substitution value or option key}."""
    decisions = decisions or {}
    resolved = {}
    for name in needed:
        spec = cat.decisions[name]
        choice = decisions.get(name)
        if choice not in spec["options"]:
            raise DecisionRequired(name, spec["options"], spec["question"])
        resolved[name] = spec["options"][choice].get("value", choice)
    return resolved


# --------------------------------------------------------------------------- generation

def check_uc_name(name: str) -> str:
    if not UC_NAME.match(str(name)):
        raise ValueError(f"Invalid Unity Catalog identifier: {name!r}")
    return ".".join(f"`{p}`" for p in str(name).split("."))


def _sql_literal(value) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def build_silver(entity: str, emap: dict, target: str, spec: dict | None = None) -> str:
    """Conforming view: physical -> canonical names, enum CASE, to-one joins, filter.

    Field expressions come from the reviewed mapping file (trusted SA input); table
    names are validated as UC identifiers.
    """
    fields = emap.get("fields") or {}
    lines = [f"  {expr} AS `{canon}`" for canon, expr in fields.items()]
    for canon in sorted(_defaulted(spec or {}) - set(fields)):
        default = spec["fields"][canon]["default_if_unmapped"]
        lines.append(f"  CAST({float(default)} AS DOUBLE) AS `{canon}`")
    for canon, spec in (emap.get("enums") or {}).items():
        col = spec["source_column"]
        whens = " ".join(f"WHEN {col} = {_sql_literal(k)} THEN {_sql_literal(v)}"
                         for k, v in (spec.get("map") or {}).items())
        lines.append(f"  CASE {whens} ELSE {_sql_literal(spec.get('default', 'other'))} END AS `{canon}`")
    sql = (f"CREATE OR REPLACE VIEW {check_uc_name(f'{target}.{entity}')} AS\nSELECT\n"
           + ",\n".join(lines) + f"\nFROM {check_uc_name(emap['source'])}")
    for j in emap.get("joins") or []:
        sql += f"\n{j.get('type', 'left').upper()} JOIN {check_uc_name(j['table'])} ON {j['on']}"
    if emap.get("filter"):
        sql += f"\nWHERE {emap['filter']}"
    return sql + ";"


def substitute(expr: str, resolved: dict) -> str:
    return PLACEHOLDER_RE.sub(lambda mo: str(resolved[mo.group(1)]), expr)


def metric_view_body(cat: Catalog, view: str, info: dict, target: str, resolved: dict,
                     skill_version: str) -> dict:
    """Metric view YAML (spec v1.1) as a dict; dumped with yaml.safe_dump."""
    ent = info["entity"]
    fields = cat.entities[ent]["fields"]
    dims = [{"name": f, "expr": f} for f, spec in fields.items()
            if spec.get("role") in ("dimension", "date", "key") and f in info["have"]]
    measures = [{"name": m["name"], "expr": substitute(m["expr"], resolved),
                 "comment": f"{m['definition']} [{m['unit']}]"} for m in info["measures"]]
    return {"version": "1.1",
            "comment": f"{view} — energy-semantic-builder v{skill_version}, catalog {cat.version}",
            "source": f"{target}.{ent}", "dimensions": dims, "measures": measures}


def metric_view_sql(view_name: str, body: dict) -> str:
    return (f"CREATE OR REPLACE VIEW {check_uc_name(view_name)}\nWITH METRICS\nLANGUAGE YAML\n"
            f"AS $$\n{yaml.safe_dump(body, sort_keys=False, width=120)}$$;")
