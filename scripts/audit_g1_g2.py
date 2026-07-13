from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from audit_helpers import list_cell, positive_finite, read_object, unique_rows, valid_revision, value
from common import issue, read_csv


REQUIRED_DECISIONS = {
    "material", "cavity_count", "parting_surface", "gate", "venting",
    "side_action", "ejection", "cooling", "mold_base", "injection_machine",
}


def audit_design_basis(root: Path, manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    data = read_object(root / "00_requirements" / "design-basis.json", "design basis", issues)
    if not data:
        return
    location = "00_requirements/design-basis.json"
    if data.get("status") != "confirmed":
        issues.append(issue("G1-DBSTATUS", "blocker", "Design basis is not confirmed", location=location))
    if data.get("classification") != manifest.get("classification"):
        issues.append(issue("G1-DBCLASS", "blocker", "Design basis classification differs from project manifest", location=location))
    for field in ("design_basis_id", "part_boundary", "function", "use_environment", "wall_strategy", "draft_direction", "feature_strategy", "production_basis"):
        if not str(data.get(field, "")).strip():
            issues.append(issue("G1-DBFIELD", "blocker", f"Design basis field is empty: {field}", location=location))
    if not valid_revision(data.get("revision")):
        issues.append(issue("G1-DBREV", "blocker", "Design basis revision must be a positive integer", location=location))
    if not isinstance(data.get("assembly_interfaces"), list) or not data.get("assembly_interfaces"):
        issues.append(issue("G1-DBINTERFACE", "blocker", "At least one assembly interface or an explicit none rationale is required", location=location))

    concepts = data.get("concept_options", [])
    if not isinstance(concepts, list) or not 2 <= len(concepts) <= 3:
        issues.append(issue("G1-CONCEPTS", "blocker", "Design basis must compare 2-3 part concepts", location=location))
        concepts = []
    concept_ids: set[str] = set()
    for index, concept in enumerate(concepts):
        item_location = f"{location}:concept_options[{index}]"
        if not isinstance(concept, dict):
            issues.append(issue("G1-CONCEPT", "blocker", "Concept must be an object", location=item_location))
            continue
        concept_id = str(concept.get("concept_id", "")).strip()
        if not concept_id or concept_id in concept_ids:
            issues.append(issue("G1-CONCEPT", "blocker", "Concept ID is missing or duplicated", location=item_location))
        concept_ids.add(concept_id)
        for field in ("name", "description", "advantages", "risks", "decision"):
            if concept.get(field) in (None, "", []):
                issues.append(issue("G1-CONCEPT", "blocker", f"Concept lacks {field}", concept_id, item_location))
    if str(data.get("selected_concept_id", "")).strip() not in concept_ids:
        issues.append(issue("G1-SELECT", "blocker", "Selected concept does not reference a listed concept", location=location))
    envelope = data.get("envelope_mm", {})
    for axis in ("length", "width", "height"):
        if not isinstance(envelope, dict) or not positive_finite(envelope.get(axis)):
            issues.append(issue("G1-ENVELOPE", "blocker", f"Envelope {axis} must be a positive finite value", location=location))
    for field, minimum in (("material_candidates", 2), ("quality_targets", 1), ("safety_constraints", 1), ("deliverables", 5)):
        items = data.get(field, [])
        if not isinstance(items, list) or len(items) < minimum:
            issues.append(issue("G1-DBLIST", "blocker", f"{field} requires at least {minimum} item(s)", location=location))
    if manifest.get("classification") == "EDU-CONCEPT" and "教学" not in str(data.get("teaching_notice", "")):
        issues.append(issue("G1-NOTICE", "blocker", "EDU-CONCEPT design basis lacks a teaching-use notice", location=location))


def audit_g1(root: Path, manifest: dict[str, Any], issues: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    audit_design_basis(root, manifest, issues)
    outline_path = root / "01_outline" / "outline.md"
    outline = outline_path.read_text(encoding="utf-8-sig") if outline_path.is_file() else ""
    if len(outline.strip()) < 1000 or len(re.findall(r"^#{2,4}\s+", outline, re.M)) < 12:
        issues.append(issue("G1-OUTLINE", "blocker", "Three-level outline is missing or structurally incomplete", location="01_outline/outline.md"))
    required_sections = (
        (r"引言", "引言"), (r"塑件.*材料|材料.*工艺", "塑件与材料工艺"),
        (r"浇注|浇口", "浇注系统"), (r"成型零件", "成型零件"),
        (r"脱模|推出", "脱模推出"), (r"冷却|温度调节", "冷却系统"),
        (r"结论", "结论"), (r"参考文献", "参考文献"), (r"致谢", "致谢"),
    )
    for pattern, label in required_sections:
        if not re.search(pattern, outline):
            issues.append(issue("G1-OUTLINESEC", "blocker", f"Outline lacks required section: {label}", location="01_outline/outline.md"))

    requirements = read_csv(root / "00_requirements" / "requirements.csv")
    active = [row for row in requirements if value(row, "status") in {"approved", "verified"}]
    requirement_map = unique_rows(active, "req_id", "00_requirements/requirements.csv", "G1-REQID", issues)
    if len(requirement_map) < 3:
        issues.append(issue("G1-REQ", "blocker", "At least three approved course-design requirements are required", location="00_requirements/requirements.csv"))
    for index, row in enumerate(active, start=2):
        req_id = value(row, "req_id")
        for field in ("category", "requirement", "origin", "priority", "acceptance", "chapter_id", "verification"):
            if not value(row, field):
                issues.append(issue("G1-REQMAP", "blocker", f"Requirement lacks {field}", req_id, f"00_requirements/requirements.csv:{index}"))
        if not valid_revision(value(row, "revision")):
            issues.append(issue("G1-REQREV", "blocker", "Requirement revision is invalid", req_id, f"00_requirements/requirements.csv:{index}"))

    assumptions = read_csv(root / "00_requirements" / "assumptions.csv")
    active_assumptions = [row for row in assumptions if value(row, "status") not in {"superseded", "rejected"}]
    unique_rows(active_assumptions, "assumption_id", "00_requirements/assumptions.csv", "G1-ASMID", issues)
    k3 = [row for row in assumptions if value(row, "criticality") == "K3"]
    if manifest.get("mode") == "from-zero" and not k3:
        issues.append(issue("G1-ASMREQ", "blocker", "A title-only project must record at least one K3 assumption", location="00_requirements/assumptions.csv"))
    for index, row in enumerate(k3, start=2):
        if value(row, "status") not in {"approved", "rejected", "superseded"}:
            issues.append(issue("G1-ASM", "blocker", "Critical K3 assumption has not been decided", value(row, "assumption_id"), f"00_requirements/assumptions.csv:{index}"))
    if manifest.get("classification") == "REAL-PART":
        inputs = manifest.get("inputs", {})
        bad = not isinstance(inputs, dict) or inputs.get("part_drawing") in {"missing", "pending_registration"} or inputs.get("part_model") in {"missing", "pending_registration"}
        if bad:
            issues.append(issue("G1-REALINPUT", "blocker", "REAL-PART project lacks registered part drawing/model evidence", location="project.json"))
    return requirements, assumptions


def audit_g2(root: Path, issues: list[dict[str, str]]) -> list[dict[str, str]]:
    decisions = read_csv(root / "03_engineering" / "decisions.csv")
    approved = [row for row in decisions if value(row, "status") == "approved"]
    unique_rows(approved, "decision_id", "03_engineering/decisions.csv", "G2-DECID", issues)
    selected_categories = {value(row, "category") for row in approved if value(row, "selected_option")}
    missing = sorted(REQUIRED_DECISIONS - selected_categories)
    if missing:
        issues.append(issue("G2-DEC", "blocker", "Required approved scheme decisions are missing: " + ", ".join(missing), location="03_engineering/decisions.csv"))
    for index, row in enumerate(approved, start=2):
        decision_id = value(row, "decision_id")
        alternatives = list_cell(value(row, "alternatives"))
        if len(set(alternatives)) < 2:
            issues.append(issue("G2-COMPARE", "blocker", "Approved decision must compare at least two alternatives", decision_id, f"03_engineering/decisions.csv:{index}"))
        for field in ("question", "selected_option", "rationale", "evidence_ids", "impact"):
            if not value(row, field):
                issues.append(issue("G2-COMPARE", "blocker", f"Approved decision lacks {field}", decision_id, f"03_engineering/decisions.csv:{index}"))
        if not valid_revision(value(row, "revision")):
            issues.append(issue("G2-REV", "blocker", "Decision revision is invalid", decision_id, f"03_engineering/decisions.csv:{index}"))

    schemes = read_object(root / "03_engineering" / "schemes.json", "scheme comparison", issues)
    scheme_rows = schemes.get("schemes", []) if schemes else []
    criteria = schemes.get("criteria", []) if schemes else []
    if schemes.get("status") != "approved" or not isinstance(scheme_rows, list) or len(scheme_rows) < 2 or not isinstance(criteria, list) or len(criteria) < 5:
        issues.append(issue("G2-SCHEMES", "blocker", "Scheme matrix must be approved and compare at least two schemes over five criteria", location="03_engineering/schemes.json"))
        scheme_rows = scheme_rows if isinstance(scheme_rows, list) else []
    scheme_ids = {str(item.get("scheme_id", "")).strip() for item in scheme_rows if isinstance(item, dict)}
    if not schemes.get("selected_scheme_id") or schemes.get("selected_scheme_id") not in scheme_ids:
        issues.append(issue("G2-SCHEMESEL", "blocker", "Selected scheme does not reference the scheme matrix", location="03_engineering/schemes.json"))
    for index, item in enumerate(scheme_rows):
        if not isinstance(item, dict) or not item.get("scheme_id") or not item.get("configuration") or not item.get("scores") or not item.get("rationale"):
            issues.append(issue("G2-SCHEMEROW", "blocker", "Scheme record is incomplete", location=f"03_engineering/schemes.json:schemes[{index}]"))
    return decisions
