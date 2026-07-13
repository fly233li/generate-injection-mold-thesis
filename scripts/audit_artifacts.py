from __future__ import annotations

from pathlib import Path
from typing import Any

from audit_helpers import positive_finite, read_object, safe_project_file, validate_hash_entry
from common import issue


EXECUTED = {"executed", "verified"}


def audit_manifest_files(root: Path, manifest: dict[str, Any], label: str, issues: list[dict[str, str]]) -> list[Path]:
    field = "files" if label == "CAD" else "result_files"
    entries = manifest.get(field, [])
    if not isinstance(entries, list) or not entries:
        issues.append(issue("G3-EVIDENCE", "blocker", f"{label} is marked executed without output files", location=f"{label} manifest"))
        return []
    output: list[Path] = []
    for index, entry in enumerate(entries):
        candidate = validate_hash_entry(root, entry, label, f"{label} manifest:{field}[{index}]", issues)
        if candidate:
            output.append(candidate)
    return output


def audit_cad(root: Path, project_manifest: dict[str, Any], data: dict[str, Any], issues: list[dict[str, str]]) -> str:
    status = str(data.get("status", "planned")).strip()
    location = "04_cad/model-manifest.json"
    if status in {"planned", "rejected", "stale"}:
        issues.append(issue("G3-CADSTATUS", "blocker", f"CAD package status cannot pass G3: {status}", location=location))
        return status
    if status == "prepared_unexecuted":
        plan = read_object(root / "04_cad" / "nx" / "model-plan.json", "NX model plan", issues)
        if plan.get("status") != "prepared_unexecuted" or not plan.get("features") or not plan.get("parameter_expression_map"):
            issues.append(issue("G3-CADPLAN", "blocker", "Prepared-unexecuted NX package lacks a prepared feature/expression plan", location="04_cad/nx/model-plan.json"))
        issues.append(issue("G3-UNEXECUTED", "warning", "NX is prepared but unexecuted; no CAD-derived result may be claimed", location=location))
        return status
    if status not in EXECUTED:
        issues.append(issue("G3-CADSTATUS", "blocker", f"Unknown CAD status: {status}", location=location))
        return status
    if str(data.get("tool", "")).lower() not in {"nx", "ug", "siemens nx"}:
        issues.append(issue("CAD001", "blocker", "Executed CAD package is not identified as Siemens NX/UG", location=location))
    if str(data.get("tool_version", "")).strip().lower() in {"", "unknown"}:
        issues.append(issue("CAD002", "blocker", "Executed CAD package lacks tool version", location=location))
    if str(data.get("license_status", "")).lower() not in {"available", "active", "verified"}:
        issues.append(issue("CAD003", "blocker", "Executed CAD package lacks verified license availability", location=location))
    if str(data.get("model_revision", "")).lower() in {"", "none", "unknown"}:
        issues.append(issue("CAD004", "blocker", "Executed CAD package lacks model revision", location=location))
    paths = audit_manifest_files(root, data, "CAD", issues)
    suffixes = {path.suffix.lower() for path in paths}
    if ".prt" not in suffixes:
        issues.append(issue("CAD005", "blocker", "Executed NX package lacks a native .prt file", location=location))
    if not suffixes.intersection({".step", ".stp", ".x_t", ".x_b"}):
        issues.append(issue("CAD006", "blocker", "Executed NX package lacks a neutral geometry export", location=location))
    execution = data.get("execution", {})
    if not isinstance(execution, dict) or execution.get("exit_code") != 0 or not execution.get("completed_at") or execution.get("opened_verified") is not True:
        issues.append(issue("CAD007", "blocker", "NX execution record is incomplete or not opened-verified", location=location))
    log = safe_project_file(root, str(data.get("execution_log", "")))
    if log is None or not log.is_file() or log.stat().st_size == 0:
        issues.append(issue("CAD008", "blocker", "NX execution log is missing or empty", location=location))
    measurements = data.get("measurements", {})
    for key in ("volume_mm3", "projected_area_mm2", "mass_g"):
        if not isinstance(measurements, dict) or not positive_finite(measurements.get(key)):
            issues.append(issue("CAD009", "blocker", f"Executed NX package lacks positive measurement: {key}", location=location))
    software = project_manifest.get("software", {})
    if isinstance(software, dict) and software.get("nx_backend") == "unavailable":
        issues.append(issue("CAD010", "blocker", "Project software probe says NX backend is unavailable", location="project.json"))
    return status


def audit_cae(root: Path, project_manifest: dict[str, Any], data: dict[str, Any], cad_revision: str, issues: list[dict[str, str]]) -> str:
    status = str(data.get("status", "planned")).strip()
    location = "05_cae/moldflow-study.json"
    if status in {"planned", "rejected", "stale"}:
        issues.append(issue("G3-CAESTATUS", "blocker", f"Moldflow package status cannot pass G3: {status}", location=location))
        return status
    cases = data.get("cases", [])
    if status == "prepared_unexecuted":
        mesh = data.get("mesh", {})
        incomplete = (
            str(data.get("material_grade", "")).lower() in {"", "unselected"}
            or not isinstance(mesh, dict)
            or str(mesh.get("type", "")).lower() in {"", "to_be_selected"}
            or not isinstance(cases, list)
            or not cases
        )
        if incomplete:
            issues.append(issue("G3-CAEPLAN", "blocker", "Prepared-unexecuted Moldflow package lacks material, mesh plan, or cases", location=location))
        issues.append(issue("G3-UNEXECUTED", "warning", "Moldflow is prepared but unexecuted; no simulation result may be claimed", location=location))
        return status
    if status not in EXECUTED:
        issues.append(issue("G3-CAESTATUS", "blocker", f"Unknown Moldflow status: {status}", location=location))
        return status
    if str(data.get("backend", "")).lower() != "moldflow":
        issues.append(issue("CAE001", "blocker", "Executed CAE package is not identified as Moldflow", location=location))
    for field in ("tool_version", "material_grade", "material_card_id", "geometry_revision"):
        if str(data.get(field, "")).strip().lower() in {"", "unknown", "unselected", "none"}:
            issues.append(issue("CAE002", "blocker", f"Executed Moldflow package lacks {field}", location=location))
    if str(data.get("license_status", "")).lower() not in {"available", "active", "verified"}:
        issues.append(issue("CAE003", "blocker", "Executed Moldflow package lacks verified license availability", location=location))
    if cad_revision not in {"", "none", "unknown"} and data.get("geometry_revision") != cad_revision:
        issues.append(issue("CAE004", "blocker", "Moldflow geometry revision differs from CAD model revision", location=location))
    mesh = data.get("mesh", {})
    mesh_ok = isinstance(mesh, dict) and positive_finite(mesh.get("target_size_mm")) and positive_finite(mesh.get("element_count")) and bool(mesh.get("quality_metrics"))
    if not mesh_ok:
        issues.append(issue("CAE005", "blocker", "Executed Moldflow package lacks valid mesh metrics", location=location))
    if not isinstance(cases, list) or not cases:
        issues.append(issue("CAE006", "blocker", "Executed Moldflow package has no cases", location=location))
    else:
        for index, case in enumerate(cases):
            valid = isinstance(case, dict) and case.get("case_id") and case.get("status") in {"completed", "verified"} and case.get("analysis_sequence") and case.get("result_ids")
            if not valid:
                issues.append(issue("CAE007", "blocker", "Moldflow case is incomplete or unexecuted", location=f"{location}:cases[{index}]"))
    paths = audit_manifest_files(root, data, "Moldflow", issues)
    if not {path.suffix.lower() for path in paths}.intersection({".sdy", ".mpi", ".udm"}):
        issues.append(issue("CAE008", "blocker", "Executed Moldflow package lacks a native study file", location=location))
    execution = data.get("execution", {})
    if not isinstance(execution, dict) or execution.get("exit_code") != 0 or execution.get("success") is not True or not execution.get("completed_at"):
        issues.append(issue("CAE009", "blocker", "Moldflow execution record does not prove a successful solve", location=location))
    log = safe_project_file(root, str(data.get("solver_log", "")))
    if log is None or not log.is_file() or log.stat().st_size == 0:
        issues.append(issue("CAE010", "blocker", "Moldflow solver log is missing or empty", location=location))
    software = project_manifest.get("software", {})
    if isinstance(software, dict) and software.get("moldflow_backend") == "unavailable":
        issues.append(issue("CAE011", "blocker", "Project software probe says Moldflow backend is unavailable", location="project.json"))
    return status
