from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from audit_g1_g2 import audit_g1, audit_g2
from audit_g3 import audit_g3
from audit_g4 import audit_g4
from audit_helpers import read_object, valid_revision
from common import atomic_write_json, atomic_write_text, blocking, issue, project_dir, sort_issues, utc_now


GATE_LEVEL = {None: 4, "G1": 1, "G2": 2, "G3": 3, "G4": 4}


def run_audit(project: str | Path, gate: str | None = None, write_report: bool = False) -> dict[str, object]:
    root = project_dir(project)
    level = GATE_LEVEL.get(gate)
    if level is None:
        raise ValueError(f"Unknown gate: {gate}")
    issues: list[dict[str, str]] = []
    manifest = read_object(root / "project.json", "project manifest", issues)

    if not str(manifest.get("title", "")).strip():
        issues.append(issue("PRJ002", "blocker", "Project title is missing", location="project.json"))
    if manifest.get("classification") not in {"REAL-PART", "EDU-CONCEPT"}:
        issues.append(issue("PRJ003", "blocker", "Project classification must be REAL-PART or EDU-CONCEPT", location="project.json"))
    policies = manifest.get("policies", {})
    if manifest.get("classification") == "EDU-CONCEPT" and (not isinstance(policies, dict) or not policies.get("teaching_use_only")):
        issues.append(issue("PRJ004", "blocker", "EDU-CONCEPT project lacks the teaching-use restriction", location="project.json"))
    if not valid_revision(manifest.get("project_revision")):
        issues.append(issue("PRJ005", "blocker", "Project revision must be a positive integer", location="project.json"))
    if not isinstance(manifest.get("design_basis_version"), int) or manifest.get("design_basis_version", -1) < 0:
        issues.append(issue("PRJ006", "blocker", "Design-basis version must be a non-negative integer", location="project.json"))

    requirements: list[dict[str, str]] = []
    context: dict[str, Any] = {}
    if level >= 1:
        requirements, assumptions = audit_g1(root, manifest, issues)
        context["requirements"] = requirements
        context["assumptions"] = assumptions
    if level >= 2:
        context["decisions"] = audit_g2(root, issues)
    if level >= 3:
        context.update(audit_g3(root, manifest, requirements, issues))
    if level >= 4:
        audit_g4(root, manifest, context, issues)

    issues = sort_issues(issues)
    summary = {severity: sum(1 for item in issues if item["severity"] == severity) for severity in ("blocker", "error", "warning", "info")}
    result: dict[str, object] = {
        "schema_version": "2.0",
        "generated_at": utc_now(),
        "gate": gate or "G4",
        "passed": not blocking(issues),
        "summary": summary,
        "issues": issues,
    }
    if write_report:
        audit_dir = root / "07_audit"
        atomic_write_json(audit_dir / "issues.json", result)
        lines = [
            "# 项目审计报告", "", f"- Gate：{result['gate']}",
            f"- 通过：{'是' if result['passed'] else '否'}", f"- 阻断项：{summary['blocker']}",
            f"- 错误：{summary['error']}", f"- 警告：{summary['warning']}", "", "## 问题", "",
        ]
        for item in issues:
            lines.append(f"- **{item['severity']} {item['rule']}** `{item['entity']}` {item['message']} ({item['location']})")
        if not issues:
            lines.append("- 未发现问题。")
        atomic_write_text(audit_dir / "audit-report.md", "\n".join(lines) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staged project integrity audits")
    parser.add_argument("--project", required=True)
    parser.add_argument("--gate", choices=("G1", "G2", "G3", "G4"))
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--no-write-report", action="store_true")
    args = parser.parse_args()
    try:
        root = project_dir(args.project)
        if args.json_path:
            output = Path(args.json_path).expanduser().resolve()
            try:
                output.relative_to(root)
            except ValueError:
                pass
            else:
                raise ValueError("--json output may not overwrite files inside the audited project")
        result = run_audit(root, args.gate, not args.no_write_report)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json_path:
        atomic_write_json(Path(args.json_path).expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
