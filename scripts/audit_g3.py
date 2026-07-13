from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audit_artifacts import EXECUTED, audit_cad, audit_cae
from audit_helpers import list_cell, read_object, safe_project_file, unique_rows, valid_revision, value
from common import issue, read_csv, read_json
from engineering_audit import run_engineering_audit


REQUIRED_CALC_CATEGORIES = {
    "part_mass", "cavity_count", "injection_capacity", "clamp_force", "cooling", "ejection",
}


def referenced_id(raw: str, prefix: str) -> str:
    match = re.search(rf"\b{re.escape(prefix)}-[A-Za-z0-9_-]+\b", raw)
    return match.group(0) if match else ""


def audit_g3(root: Path, manifest: dict[str, Any], requirements: list[dict[str, str]], issues: list[dict[str, str]]) -> dict[str, Any]:
    engineering = run_engineering_audit(root)
    issues.extend(engineering["issues"])  # type: ignore[arg-type]
    parameters = read_csv(root / "03_engineering" / "parameters.csv")
    confirmed_parameters = [row for row in parameters if value(row, "status") == "confirmed"]
    if len(confirmed_parameters) < 8:
        issues.append(issue("G3-PARAMCOVER", "blocker", "Engineering baseline requires at least eight confirmed parameters", location="03_engineering/parameters.csv"))

    try:
        raw_calculations = read_json(root / "03_engineering" / "calculations.json").get("calculations", [])
        calculations = [item for item in raw_calculations if isinstance(item, dict)] if isinstance(raw_calculations, list) else []
    except Exception:
        calculations = []
    confirmed_calculations = [item for item in calculations if str(item.get("status", "")).strip() in {"confirmed", "verified"}]
    calculation_ids = {str(item.get("id", "")).strip() for item in confirmed_calculations}
    categories = {str(item.get("category", "")).strip() for item in confirmed_calculations}
    missing = sorted(REQUIRED_CALC_CATEGORIES - categories)
    if missing:
        issues.append(issue("G3-CALCCOVER", "blocker", "Required calculation categories are missing: " + ", ".join(missing), location="03_engineering/calculations.json"))
    for index, calc in enumerate(confirmed_calculations):
        calc_id = str(calc.get("id", "")).strip()
        for field in ("applicability", "input_ids", "substitution", "acceptance", "margin", "independent_check", "revision"):
            current = calc.get(field)
            if current in (None, "", []):
                issues.append(issue("G3-CALCFIELD", "blocker", f"Confirmed calculation lacks {field}", calc_id, f"03_engineering/calculations.json:calculations[{index}]"))
        if not valid_revision(calc.get("revision")):
            issues.append(issue("G3-CALCREV", "blocker", "Calculation revision must be a positive integer", calc_id, f"03_engineering/calculations.json:calculations[{index}]"))

    cad = read_object(root / "04_cad" / "model-manifest.json", "CAD manifest", issues)
    cae = read_object(root / "05_cae" / "moldflow-study.json", "Moldflow manifest", issues)
    cad_status = audit_cad(root, manifest, cad, issues) if cad else "planned"
    cad_revision = str(cad.get("model_revision", "none"))
    cae_status = audit_cae(root, manifest, cae, cad_revision, issues) if cae else "planned"
    cases = cae.get("cases", []) if isinstance(cae, dict) else []
    case_ids = {str(item.get("case_id", "")).strip() for item in cases if isinstance(item, dict)}

    sources = read_csv(root / "02_sources" / "references.csv")
    source_ids = {value(row, "source_id") for row in sources if value(row, "status") in {"verified", "claim-bound", "used"}}
    decisions = read_csv(root / "03_engineering" / "decisions.csv")
    decision_ids = {value(row, "decision_id") for row in decisions if value(row, "status") == "approved"}
    assumptions = read_csv(root / "00_requirements" / "assumptions.csv")
    assumption_ids = {value(row, "assumption_id") for row in assumptions if value(row, "status") == "approved"}
    cad_artifact_id = str(cad.get("artifact_id", "")).strip()

    for index, row in enumerate(confirmed_parameters, start=2):
        param_id = value(row, "param_id")
        origin = value(row, "origin_type")
        source_ref = value(row, "source_ref")
        target = ""
        valid = True
        if origin == "SRC":
            target = referenced_id(source_ref, "SRC"); valid = bool(target and target in source_ids)
        elif origin == "DEC":
            target = referenced_id(source_ref, "DEC"); valid = bool(target and target in decision_ids)
        elif origin == "ASM":
            target = value(row, "assumption_id"); valid = bool(target and target in assumption_ids)
        elif origin == "CALC":
            target = referenced_id(source_ref, "CALC"); valid = bool(target and target in calculation_ids)
        elif origin == "CAD":
            valid = cad_status in EXECUTED and bool(cad_artifact_id and cad_artifact_id in source_ref)
        elif origin == "SIM":
            valid = cae_status in EXECUTED and any(case_id and case_id in source_ref for case_id in case_ids)
        if not valid:
            issues.append(issue("G3-ORIGINXREF", "blocker", f"Parameter origin reference does not resolve: {origin} {source_ref}", param_id, f"03_engineering/parameters.csv:{index}"))

    for index, calc in enumerate(confirmed_calculations):
        formula_source = str(calc.get("formula_source", ""))
        source_target = referenced_id(formula_source, "SRC")
        decision_target = referenced_id(formula_source, "DEC")
        if source_target and source_target not in source_ids:
            issues.append(issue("G3-FORMULAXREF", "blocker", f"Formula source does not resolve: {source_target}", str(calc.get("id", "")), f"03_engineering/calculations.json:calculations[{index}]"))
        elif decision_target and decision_target not in decision_ids:
            issues.append(issue("G3-FORMULAXREF", "blocker", f"Formula decision does not resolve: {decision_target}", str(calc.get("id", "")), f"03_engineering/calculations.json:calculations[{index}]"))
        elif not source_target and not decision_target:
            issues.append(issue("G3-FORMULAXREF", "blocker", "Formula source must cite an existing SRC-* or DEC-* record", str(calc.get("id", "")), f"03_engineering/calculations.json:calculations[{index}]"))

    drawings = read_csv(root / "04_cad" / "drawings.csv")
    active_drawings = [row for row in drawings if value(row, "status") in {"prepared", "verified"}]
    drawing_map = unique_rows(active_drawings, "drawing_id", "04_cad/drawings.csv", "DRW001", issues)
    if not {"part", "assembly"}.issubset({value(row, "drawing_type") for row in active_drawings}):
        issues.append(issue("DRW002", "blocker", "Prepared drawing set must include part and assembly drawings", location="04_cad/drawings.csv"))
    for index, row in enumerate(active_drawings, start=2):
        drawing_id = value(row, "drawing_id")
        for field in ("title", "file", "model_revision", "requirement_ids", "revision"):
            if not value(row, field):
                issues.append(issue("DRW003", "blocker", f"Drawing lacks {field}", drawing_id, f"04_cad/drawings.csv:{index}"))
        candidate = safe_project_file(root, value(row, "file"))
        if candidate is None or not candidate.is_file() or candidate.stat().st_size == 0:
            issues.append(issue("DRW004", "blocker", "Drawing file is missing, empty, unsafe, or linked", drawing_id, f"04_cad/drawings.csv:{index}"))
        if cad_revision not in {"none", "unknown", ""} and value(row, "model_revision") != cad_revision:
            issues.append(issue("DRW005", "blocker", "Drawing revision differs from CAD model revision", drawing_id, f"04_cad/drawings.csv:{index}"))

    bom = read_csv(root / "04_cad" / "bom.csv")
    active_bom = [row for row in bom if value(row, "status") in {"prepared", "verified"}]
    unique_rows(active_bom, "item_id", "04_cad/bom.csv", "BOM001", issues)
    if len(active_bom) < 5:
        issues.append(issue("BOM002", "blocker", "BOM must contain at least five prepared/verified items", location="04_cad/bom.csv"))
    for index, row in enumerate(active_bom, start=2):
        item_id = value(row, "item_id")
        for field in ("item_no", "part_name", "quantity", "material", "standard_or_drawing_id", "model_revision", "revision"):
            if not value(row, field):
                issues.append(issue("BOM003", "blocker", f"BOM item lacks {field}", item_id, f"04_cad/bom.csv:{index}"))

    placements = read_csv(root / "01_outline" / "evidence-placement.csv")
    placement_map = unique_rows(placements, "object_id", "01_outline/evidence-placement.csv", "G3-PLACEID", issues)
    if len(placement_map) < 5:
        issues.append(issue("G3-PLACE", "blocker", "Evidence placement matrix must contain at least five objects", location="01_outline/evidence-placement.csv"))
    for index, row in enumerate(placements, start=2):
        object_id = value(row, "object_id")
        for field in ("object_type", "title_or_caption", "section_id", "first_mention_claim_id", "insertion_position", "purpose", "source_or_artifact_id", "status", "revision"):
            if not value(row, field):
                issues.append(issue("G3-PLACEFIELD", "blocker", f"Placement lacks {field}", object_id, f"01_outline/evidence-placement.csv:{index}"))
        if value(row, "status") not in {"planned", "placed", "verified"}:
            issues.append(issue("G3-PLACESTATUS", "blocker", "Unknown placement status", object_id, f"01_outline/evidence-placement.csv:{index}"))

    for index, row in enumerate(requirements, start=2):
        if value(row, "status") not in {"approved", "verified"}:
            continue
        references_by_type = (
            ("calc_ids", calculation_ids), ("drawing_ids", set(drawing_map)), ("case_ids", case_ids),
        )
        linked_count = 0
        for field, existing in references_by_type:
            refs = list_cell(value(row, field)); linked_count += len(refs)
            for reference in refs:
                if reference not in existing:
                    issues.append(issue("REQXREF", "blocker", f"Requirement references missing {field}: {reference}", value(row, "req_id"), f"00_requirements/requirements.csv:{index}"))
        if value(row, "category") not in {"literature", "manuscript", "administrative"} and linked_count == 0:
            issues.append(issue("REQCOVER", "blocker", "Engineering requirement has no calculation, drawing, or case evidence ID", value(row, "req_id"), f"00_requirements/requirements.csv:{index}"))

    return {"parameters": parameters, "calculations": calculations, "cad": cad, "cae": cae, "drawings": drawings, "bom": bom, "placements": placements}
