from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any

from audit_artifacts import EXECUTED
from audit_helpers import list_cell, read_object, safe_project_file, sha256_file, unique_rows, validate_hash_entry, valid_revision, value
from common import issue, read_csv


BASE_RELEASE_ROLES = {"final_docx", "final_pdf", "calculation_book", "drawing_set", "bom", "source_ledger"}


def audit_manuscript(root: Path, cad: dict[str, Any], cae: dict[str, Any], issues: list[dict[str, str]]) -> tuple[str, set[str]]:
    path = root / "06_manuscript" / "manuscript.md"
    manuscript = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    if len(manuscript.strip()) < 8000:
        issues.append(issue("G4-MANUSCRIPT", "blocker", "Manuscript is missing or substantially incomplete (<8000 characters)", location="06_manuscript/manuscript.md"))
    # ``ref`` is the canonical source used by the Word builder for a numbered
    # bibliography cross-reference.  It is intentionally distinct from
    # ``cite`` (source registration) and must survive until DOCX rendering.
    allowed = re.compile(r"\{\{(?:cite|ref|xref|fig|tab|eq):[A-Za-z0-9_-]+\}\}")
    remaining = allowed.sub("", manuscript)
    placeholder = re.search(r"\{\{[^}]+\}\}|\bTODO\b|待补|待填写|\bXX(?:大学|学院|专业|姓名|学号)?\b", remaining, re.I)
    if placeholder:
        issues.append(issue("G4-PLACEHOLDER", "blocker", f"Unresolved placeholder in manuscript: {placeholder.group(0)}", location="06_manuscript/manuscript.md"))
    for pattern, label in ((r"中文摘要|摘\s*要", "中文摘要"), (r"\bAbstract\b", "英文摘要"), (r"引言", "引言"), (r"结论", "结论"), (r"参考文献", "参考文献"), (r"致谢", "致谢")):
        if not re.search(pattern, manuscript, re.I):
            issues.append(issue("G4-SECTION", "blocker", f"Manuscript lacks {label}", location="06_manuscript/manuscript.md"))
    if str(cad.get("status", "")) not in EXECUTED and re.search(r"(?:NX|UG).{0,12}(?:测得|测量|计算得到).{0,20}(?:体积|质量|投影面积)", manuscript, re.I):
        issues.append(issue("G4-CADCLAIM", "blocker", "Manuscript claims CAD-measured values without executed NX evidence", location="06_manuscript/manuscript.md"))
    if str(cae.get("status", "")) not in EXECUTED and re.search(r"Moldflow.{0,16}(?:结果表明|分析表明|仿真得到|优化后)", manuscript, re.I):
        issues.append(issue("G4-SIMCLAIM", "blocker", "Manuscript claims Moldflow results without an executed study", location="06_manuscript/manuscript.md"))
    cited = set(re.findall(r"\{\{cite:([A-Za-z0-9_-]+)\}\}", manuscript))
    return manuscript, cited


def audit_sources(root: Path, cited: set[str], issues: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    references = read_csv(root / "02_sources" / "references.csv")
    used = [row for row in references if value(row, "status") in {"claim-bound", "used"}]
    source_map = unique_rows(used, "source_id", "02_sources/references.csv", "REF000", issues)
    if len(source_map) < 5:
        issues.append(issue("REF004", "blocker", "Final thesis requires at least five verified, claim-bound sources", location="02_sources/references.csv"))
    for index, row in enumerate(used, start=2):
        source_id = value(row, "source_id")
        for field in ("source_type", "title", "authors_or_org", "year", "access_date", "access_level", "exact_locator", "claim_ids", "citation_key", "used_in", "revision"):
            if not value(row, field):
                issues.append(issue("REF005", "blocker", f"Used source lacks {field}", source_id, f"02_sources/references.csv:{index}"))
        if not any(value(row, field) for field in ("doi", "cnki_url_or_record_id", "official_url")):
            issues.append(issue("REF006", "blocker", "Used source lacks DOI, CNKI record, or official URL", source_id, f"02_sources/references.csv:{index}"))
        if not valid_revision(value(row, "revision")):
            issues.append(issue("REF009", "blocker", "Source revision is invalid", source_id, f"02_sources/references.csv:{index}"))
    if len(cited) < 5:
        issues.append(issue("REF007", "blocker", "Manuscript must contain at least five bound citation tokens", location="06_manuscript/manuscript.md"))
    for source_id in sorted(cited):
        if source_id not in source_map:
            issues.append(issue("REF001", "blocker", "Cited source is absent or not claim-bound", source_id, "06_manuscript/manuscript.md"))

    claims = read_csv(root / "02_sources" / "claims.csv")
    active_claims = [row for row in claims if value(row, "status") in {"verified", "used"}]
    claim_map = unique_rows(active_claims, "claim_id", "02_sources/claims.csv", "CLM001", issues)
    if len(claim_map) < 5:
        issues.append(issue("CLM002", "blocker", "Final thesis requires at least five verified claim ledger entries", location="02_sources/claims.csv"))
    for index, row in enumerate(active_claims, start=2):
        claim_id = value(row, "claim_id")
        for field in ("claim_text", "claim_type", "section_id", "revision"):
            if not value(row, field):
                issues.append(issue("CLM003", "blocker", f"Claim lacks {field}", claim_id, f"02_sources/claims.csv:{index}"))
        if value(row, "claim_type") == "external":
            source_ids = list_cell(value(row, "source_ids"))
            if not source_ids or not value(row, "exact_locator"):
                issues.append(issue("CLM004", "blocker", "External claim lacks source or exact locator", claim_id, f"02_sources/claims.csv:{index}"))
            for source_id in source_ids:
                if source_id not in source_map:
                    issues.append(issue("CLM005", "blocker", f"External claim references missing source: {source_id}", claim_id, f"02_sources/claims.csv:{index}"))
    for row in used:
        for claim_id in list_cell(value(row, "claim_ids")):
            if claim_id not in claim_map:
                issues.append(issue("REF008", "blocker", f"Source references missing verified claim: {claim_id}", value(row, "source_id"), "02_sources/references.csv"))
    return claim_map


def audit_placements(root: Path, claim_map: dict[str, dict[str, str]], issues: list[dict[str, str]]) -> None:
    placements = read_csv(root / "01_outline" / "evidence-placement.csv")
    for index, row in enumerate(placements, start=2):
        object_id = value(row, "object_id")
        if value(row, "status") != "verified":
            issues.append(issue("PLC001", "blocker", "Evidence object is not verified", object_id, f"01_outline/evidence-placement.csv:{index}"))
        if not value(row, "word_bookmark_or_field"):
            issues.append(issue("PLC003", "blocker", "Evidence object lacks Word bookmark/field mapping", object_id, f"01_outline/evidence-placement.csv:{index}"))
        claim_id = value(row, "first_mention_claim_id")
        if claim_id not in claim_map:
            issues.append(issue("PLC004", "blocker", "Evidence object first mention does not resolve to a verified claim", object_id, f"01_outline/evidence-placement.csv:{index}"))
        filename = value(row, "file")
        if filename:
            candidate = safe_project_file(root, filename)
            if candidate is None or not candidate.is_file() or candidate.stat().st_size == 0:
                issues.append(issue("PLC002", "blocker", f"Placed artifact file is missing, empty, unsafe, or linked: {filename}", object_id, f"01_outline/evidence-placement.csv:{index}"))


def audit_release(root: Path, manifest: dict[str, Any], cad: dict[str, Any], cae: dict[str, Any], issues: list[dict[str, str]]) -> tuple[list[Path], list[Path]]:
    release = read_object(root / "deliverables" / "release-manifest.json", "release manifest", issues)
    location = "deliverables/release-manifest.json"
    if release.get("status") not in {"ready", "released"}:
        issues.append(issue("REL001", "blocker", "Release manifest status is not ready/released", location=location))
    if release.get("project_revision") != manifest.get("project_revision") or release.get("design_basis_version") != manifest.get("design_basis_version"):
        issues.append(issue("REL002", "blocker", "Release manifest revision differs from project/design basis", location=location))
    if not release.get("generated_at") or not release.get("limitations"):
        issues.append(issue("REL003", "blocker", "Release manifest lacks generation time or limitations", location=location))
    files = release.get("files", [])
    if not isinstance(files, list):
        files = []
        issues.append(issue("REL004", "blocker", "Release files must be a list", location=location))
    role_paths: dict[str, list[Path]] = {}
    for index, entry in enumerate(files):
        candidate = validate_hash_entry(root, entry, "release", f"{location}:files[{index}]", issues)
        if candidate and isinstance(entry, dict):
            role_paths.setdefault(value(entry, "role"), []).append(candidate)
        if not isinstance(entry, dict) or value(entry, "status") not in {"final", "verified"} or not value(entry, "role"):
            issues.append(issue("REL005", "blocker", "Release file lacks role or final/verified status", location=f"{location}:files[{index}]"))
    required_roles = set(BASE_RELEASE_ROLES)
    if str(cad.get("status", "")) in EXECUTED:
        required_roles.update({"nx_native", "nx_neutral"})
    if str(cae.get("status", "")) in EXECUTED:
        required_roles.update({"moldflow_study", "moldflow_log"})
    missing_roles = sorted(role for role in required_roles if not role_paths.get(role))
    if missing_roles:
        issues.append(issue("REL006", "blocker", "Release manifest lacks required roles: " + ", ".join(missing_roles), location=location))
    docx_files = role_paths.get("final_docx", [])
    pdf_files = role_paths.get("final_pdf", [])
    if len(docx_files) != 1:
        issues.append(issue("G4-DOCX", "blocker", "Release manifest must identify exactly one final DOCX", location=location))
    if len(pdf_files) != 1:
        issues.append(issue("G4-PDF", "blocker", "Release manifest must identify exactly one final PDF", location=location))
    return docx_files, pdf_files


def audit_documents(root: Path, docx_files: list[Path], pdf_files: list[Path], issues: list[dict[str, str]]) -> None:
    for docx in docx_files:
        try:
            if docx.stat().st_size < 10_000:
                raise ValueError("DOCX is implausibly small")
            with zipfile.ZipFile(docx) as archive:
                required = {"[Content_Types].xml", "word/document.xml", "word/styles.xml"}
                if not required.issubset(archive.namelist()):
                    raise ValueError("missing core OOXML parts")
            from docx_audit import audit_docx
            result = audit_docx(docx, strict=True)
            issues.extend(result["issues"])  # type: ignore[arg-type]
        except Exception as exc:
            issues.append(issue("DOCX000", "blocker", f"DOCX audit failed: {exc}", location=str(docx.relative_to(root))))
    for pdf in pdf_files:
        if pdf.stat().st_size < 10_000 or pdf.read_bytes()[:5] != b"%PDF-":
            issues.append(issue("PDF001", "blocker", "Final PDF is too small or lacks a PDF header", location=str(pdf.relative_to(root))))
    review = read_object(root / "07_audit" / "pdf-visual-review.json", "PDF visual review", issues)
    checks = review.get("checks", {})
    if review.get("status") != "passed" or not review.get("reviewed_at") or not review.get("reviewer") or not isinstance(checks, dict) or not checks or not all(checks.values()):
        issues.append(issue("PDF002", "blocker", "PDF visual review is incomplete", location="07_audit/pdf-visual-review.json"))
    if pdf_files:
        reviewed_file = safe_project_file(root, str(review.get("reviewed_file", "")))
        if review.get("reviewed_sha256") != sha256_file(pdf_files[0]) or reviewed_file != pdf_files[0]:
            issues.append(issue("PDF003", "blocker", "PDF visual review does not match the released PDF", location="07_audit/pdf-visual-review.json"))


def audit_g4(root: Path, manifest: dict[str, Any], context: dict[str, Any], issues: list[dict[str, str]]) -> None:
    cad = context.get("cad", {}) if isinstance(context.get("cad", {}), dict) else {}
    cae = context.get("cae", {}) if isinstance(context.get("cae", {}), dict) else {}
    _manuscript, cited = audit_manuscript(root, cad, cae, issues)
    claim_map = audit_sources(root, cited, issues)
    audit_placements(root, claim_map, issues)
    docx_files, pdf_files = audit_release(root, manifest, cad, cae, issues)
    audit_documents(root, docx_files, pdf_files, issues)
