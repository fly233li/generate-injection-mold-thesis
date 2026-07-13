from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from audit_project import run_audit
from audit_g4 import audit_manuscript
from engineering_audit import run_engineering_audit
from init_project import initialize


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        fields = next(csv.reader(handle))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def file_entry(path: Path, root: Path, role: str) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "status": "verified",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class ReleaseGateV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = initialize("测试插座外壳注塑模具设计", self.root, "gate-v2", "from-zero", "nx", "moldflow")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fill_g1(self) -> None:
        design_basis = {
            "schema_version": "2.0", "design_basis_id": "DB-001", "revision": 1,
            "status": "confirmed", "classification": "EDU-CONCEPT",
            "part_boundary": "五孔插座上盖，不含金属导电件", "function": "绝缘、防护并定位插孔",
            "use_environment": "室内常温干燥环境", "assembly_interfaces": ["与底壳四个卡扣装配"],
            "concept_options": [
                {"concept_id": "CON-001", "name": "平板筋壳", "description": "均匀壁厚带加强筋", "advantages": ["简单"], "risks": ["翘曲"], "decision": "selected"},
                {"concept_id": "CON-002", "name": "阶梯壳", "description": "局部阶梯和装饰面", "advantages": ["外观"], "risks": ["侧抽芯"], "decision": "rejected"},
            ],
            "selected_concept_id": "CON-001", "envelope_mm": {"length": 118, "width": 62, "height": 16},
            "wall_strategy": "主体2.2 mm，过渡圆角", "draft_direction": "沿高度正向开模",
            "feature_strategy": "筋厚0.55倍壁厚，孔边圆角，无侧向倒扣",
            "material_candidates": ["阻燃PC", "阻燃PC/ABS"], "production_basis": "教学假定中批量生产",
            "quality_targets": ["外观面无明显缩痕", "装配界面尺寸一致"],
            "safety_constraints": ["绝缘阻燃要求需由真实标准复核"],
            "deliverables": ["塑件模型", "模具装配", "零件图", "BOM", "计算书", "论文DOCX/PDF"],
            "teaching_notice": "教学设计用途；未经验证不得用于生产", "confirmed_at": "2026-07-12T12:00:00+00:00",
        }
        (self.project / "00_requirements" / "design-basis.json").write_text(json.dumps(design_basis, ensure_ascii=False), encoding="utf-8")
        requirements = []
        links = (("REQ-001", "part_design", "CALC-MASS", "DWG-PART", ""), ("REQ-002", "mold_design", "CALC-CLAMP", "DWG-ASM", ""), ("REQ-003", "cae", "CALC-COOL", "", "CASE-001"))
        for req_id, category, calc_id, drawing_id, case_id in links:
            requirements.append({
                "req_id": req_id, "category": category, "requirement": f"完成{category}验证", "origin": "USR",
                "priority": "must", "acceptance": "由对应计算/图纸/算例复核", "chapter_id": "3.1",
                "calc_ids": calc_id, "drawing_ids": drawing_id, "case_ids": case_id,
                "verification": "检查ID与成果一致", "status": "approved", "revision": "1",
            })
        write_csv(self.project / "00_requirements" / "requirements.csv", requirements)
        write_csv(self.project / "00_requirements" / "assumptions.csv", [{
            "assumption_id": "ASM-001", "statement": "教学产量假设", "value": "100000", "unit": "件/年",
            "criticality": "K3", "basis_source_id": "", "uncertainty_or_range": "50000-150000",
            "status": "approved", "approval_gate": "G1", "affected_items": "型腔数和模架",
            "validation_method": "G2敏感性比较", "revision": "1", "supersedes": "",
        }])

    def fill_g2(self) -> None:
        categories = ("material", "cavity_count", "parting_surface", "gate", "venting", "side_action", "ejection", "cooling", "mold_base", "injection_machine")
        rows = []
        for index, category in enumerate(categories, start=1):
            rows.append({
                "decision_id": f"DEC-{category.upper()}", "category": category, "question": f"选择{category}",
                "alternatives": json.dumps(["方案A", "方案B"], ensure_ascii=False), "selected_option": "方案A",
                "rationale": "综合成型可行性、可靠性、成本和课程工作量选择", "evidence_ids": "REQ-001;ASM-001",
                "impact": "影响参数、图纸和后续校核", "status": "approved", "revision": "1",
            })
        write_csv(self.project / "03_engineering" / "decisions.csv", rows)
        schemes = {
            "schema_version": "2.0", "status": "approved", "criteria": ["成型", "可靠", "成本", "制造", "工作量"],
            "schemes": [
                {"scheme_id": "SCH-001", "configuration": {"cavities": "1x2"}, "scores": {"总分": 85}, "rationale": "平衡"},
                {"scheme_id": "SCH-002", "configuration": {"cavities": "1x1"}, "scores": {"总分": 70}, "rationale": "产能低"},
            ],
            "selected_scheme_id": "SCH-001", "revision": 1,
        }
        (self.project / "03_engineering" / "schemes.json").write_text(json.dumps(schemes, ensure_ascii=False), encoding="utf-8")

    def fill_g3_prepared(self) -> None:
        parameter_rows = []
        for index in range(1, 9):
            parameter_rows.append({
                "param_id": f"P{index}", "name": f"教学参数{index}", "symbol": f"p{index}", "value": "1",
                "unit": "1", "quantity": "dimensionless", "origin_type": "USR", "source_ref": "REQ-001",
                "status": "confirmed", "assumption_id": "", "nx_expression": f"p{index}", "used_in": "3.1", "revision": "1",
            })
        write_csv(self.project / "03_engineering" / "parameters.csv", parameter_rows)
        categories = ("part_mass", "cavity_count", "injection_capacity", "clamp_force", "cooling", "ejection")
        calculations = []
        for index, category in enumerate(categories, start=1):
            calc_id = {"part_mass": "CALC-MASS", "clamp_force": "CALC-CLAMP", "cooling": "CALC-COOL"}.get(category, f"CALC-{index}")
            calculations.append({
                "id": calc_id, "category": category, "name": category, "expression": f"P{index}",
                "result_value": 1, "result_unit": "1", "formula_source": "DEC-MATERIAL",
                "applicability": "教学方案比较", "input_ids": [f"P{index}"], "substitution": f"P{index}=1",
                "acceptance": "结果有限且与方案一致", "margin": "不适用，已记录", "independent_check": "人工复算=1",
                "tolerance": 0.001, "status": "confirmed", "used_in": "3.2", "revision": 1,
            })
        (self.project / "03_engineering" / "calculations.json").write_text(json.dumps({"schema_version": "2.0", "calculations": calculations}, ensure_ascii=False), encoding="utf-8")
        cad = json.loads((self.project / "04_cad" / "model-manifest.json").read_text(encoding="utf-8"))
        cad["status"] = "prepared_unexecuted"
        (self.project / "04_cad" / "model-manifest.json").write_text(json.dumps(cad, ensure_ascii=False), encoding="utf-8")
        plan = json.loads((self.project / "04_cad" / "nx" / "model-plan.json").read_text(encoding="utf-8"))
        plan.update({"status": "prepared_unexecuted", "features": ["拉伸主体", "筋", "孔"], "parameter_expression_map": {"P1": "p1"}})
        (self.project / "04_cad" / "nx" / "model-plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        cae = json.loads((self.project / "05_cae" / "moldflow-study.json").read_text(encoding="utf-8"))
        cae.update({"status": "prepared_unexecuted", "material_grade": "候选阻燃PC（待材料卡核验）", "material_card_id": "planned", "mesh": {"type": "3D", "target_size_mm": 2.5, "element_count": None, "quality_metrics": {}}, "cases": [{"case_id": "CASE-001", "status": "planned", "analysis_sequence": ["Fill"], "result_ids": ["fill_time"]}]})
        (self.project / "05_cae" / "moldflow-study.json").write_text(json.dumps(cae, ensure_ascii=False), encoding="utf-8")
        drawing_dir = self.project / "04_cad" / "drawings"; drawing_dir.mkdir(parents=True, exist_ok=True)
        (drawing_dir / "part.pdf").write_bytes(b"concept part drawing")
        (drawing_dir / "assembly.pdf").write_bytes(b"concept assembly drawing")
        write_csv(self.project / "04_cad" / "drawings.csv", [
            {"drawing_id": "DWG-PART", "title": "塑件图", "drawing_type": "part", "file": "04_cad/drawings/part.pdf", "model_revision": "provisional-r1", "requirement_ids": "REQ-001", "status": "prepared", "checked_by": "agent", "revision": "1"},
            {"drawing_id": "DWG-ASM", "title": "模具装配图", "drawing_type": "assembly", "file": "04_cad/drawings/assembly.pdf", "model_revision": "provisional-r1", "requirement_ids": "REQ-002", "status": "prepared", "checked_by": "agent", "revision": "1"},
        ])
        write_csv(self.project / "04_cad" / "bom.csv", [
            {"item_id": f"BOM-{index:03d}", "item_no": str(index), "part_name": f"零件{index}", "quantity": "1", "material": "待方案确认", "standard_or_drawing_id": "DWG-ASM", "model_revision": "provisional-r1", "status": "prepared", "revision": "1"}
            for index in range(1, 6)
        ])
        write_csv(self.project / "01_outline" / "evidence-placement.csv", [
            {"object_id": f"FIG-{index:03d}", "object_type": "figure", "title_or_caption": f"证据图{index}", "section_id": "3.1", "first_mention_claim_id": f"CLM-{index:03d}", "insertion_position": "首段后", "purpose": "说明方案", "source_or_artifact_id": "ART-CAD-001", "file": "", "word_bookmark_or_field": f"fig_{index}", "status": "planned", "revision": "1"}
            for index in range(1, 6)
        ])

    def test_title_with_quotes_backslash_and_token_round_trips(self) -> None:
        title = '含"引号"与\\路径{{CAD}}注塑模具设计'
        project = initialize(title, self.root, "quoted-title", "from-zero", "nx", "moldflow")
        manifest = json.loads((project / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["title"], title)
        self.assertIn(title, (project / "00_requirements" / "brief.md").read_text(encoding="utf-8"))

    def test_supplied_part_mode_is_real_but_pending_registration(self) -> None:
        project = initialize("已提供塑件", self.root, "supplied", "supplied-part", "nx", "moldflow")
        manifest = json.loads((project / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["classification"], "REAL-PART")
        self.assertEqual(manifest["inputs"]["part_model"], "pending_registration")
        self.assertFalse(run_audit(project, "G1")["passed"])

    def test_empty_template_is_blocked_but_complete_g1_passes(self) -> None:
        blocked = run_audit(self.project, "G1")
        self.assertFalse(blocked["passed"])
        self.assertTrue(any(item["rule"].startswith("G1-DB") for item in blocked["issues"]))
        self.fill_g1()
        passed = run_audit(self.project, "G1")
        self.assertTrue(passed["passed"], passed["issues"])

    def test_complete_prepared_unexecuted_g3_passes_without_result_claims(self) -> None:
        self.fill_g1(); self.fill_g2(); self.fill_g3_prepared()
        result = run_audit(self.project, "G3")
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(sum(item["rule"] == "G3-UNEXECUTED" for item in result["issues"]), 2)

    def test_rejected_artifacts_cannot_pass_g3(self) -> None:
        self.fill_g1(); self.fill_g2(); self.fill_g3_prepared()
        for relative in ("04_cad/model-manifest.json", "05_cae/moldflow-study.json"):
            path = self.project / relative; data = json.loads(path.read_text(encoding="utf-8")); data["status"] = "rejected"; path.write_text(json.dumps(data), encoding="utf-8")
        result = run_audit(self.project, "G3")
        rules = {item["rule"] for item in result["issues"]}
        self.assertFalse(result["passed"]); self.assertIn("G3-CADSTATUS", rules); self.assertIn("G3-CAESTATUS", rules)

    def test_nan_and_proposed_dependency_are_blocked(self) -> None:
        write_csv(self.project / "03_engineering" / "parameters.csv", [{"param_id": "P1", "name": "参数", "symbol": "p", "value": "1", "unit": "1", "quantity": "dimensionless", "origin_type": "USR", "source_ref": "REQ-001", "status": "proposed", "revision": "1"}])
        data = {"schema_version": "2.0", "calculations": [{"id": "CALC-1", "name": "bad", "expression": "P1", "result_value": "NaN", "result_unit": "1", "formula_source": "SRC-1 p.1", "tolerance": "NaN", "status": "confirmed", "used_in": "3.1"}]}
        (self.project / "03_engineering" / "calculations.json").write_text(json.dumps(data), encoding="utf-8")
        result = run_engineering_audit(self.project)
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["rule"] == "CALC007" for item in result["issues"]))

    def test_fake_final_docx_and_pdf_are_blocked(self) -> None:
        self.fill_g1(); self.fill_g2(); self.fill_g3_prepared()
        manuscript = "# 摘要\n说明。\n# Abstract\nAbstract.\n# 1 引言\n" + "正文" * 4200 + "\n# 结论\n结论。\n# 参考文献\n{{cite:SRC-001}}\n# 致谢\n感谢。"
        (self.project / "06_manuscript" / "manuscript.md").write_text(manuscript, encoding="utf-8")
        out = self.project / "deliverables" / "files"; out.mkdir(parents=True, exist_ok=True)
        fake_docx = out / "paper.docx"; fake_docx.write_bytes(b"not ooxml" * 2000)
        fake_pdf = out / "paper.pdf"; fake_pdf.write_bytes(b"not pdf" * 2000)
        ledger = self.project / "02_sources" / "references.csv"
        release_files = [file_entry(fake_docx, self.project, "final_docx"), file_entry(fake_pdf, self.project, "final_pdf")]
        for role, path in (("calculation_book", self.project / "03_engineering" / "calculations.json"), ("drawing_set", self.project / "04_cad" / "drawings.csv"), ("bom", self.project / "04_cad" / "bom.csv"), ("source_ledger", ledger)):
            release_files.append(file_entry(path, self.project, role))
        release = {"schema_version": "2.0", "project_revision": 1, "design_basis_version": 0, "generated_at": "2026-07-12T12:00:00+00:00", "files": release_files, "unexecuted_items": ["NX", "Moldflow"], "limitations": ["教学用途"], "status": "ready"}
        (self.project / "deliverables" / "release-manifest.json").write_text(json.dumps(release, ensure_ascii=False), encoding="utf-8")
        result = run_audit(self.project, "G4")
        rules = {item["rule"] for item in result["issues"]}
        self.assertFalse(result["passed"]); self.assertIn("DOCX000", rules); self.assertIn("PDF001", rules); self.assertIn("REF004", rules)
        self.assertNotIn("G4-PLACEHOLDER", rules)

    def test_word_reference_token_is_not_an_unresolved_placeholder(self) -> None:
        manuscript = (
            "# 中文摘要\n摘要。\n# Abstract\nAbstract.\n# 1 引言\n"
            + "正文" * 4200
            + "\n正文引文{{ref:SRC-001}}。\n# 结论\n结论。\n"
            + "# 参考文献\n{{cite:SRC-001}}\n# 致谢\n感谢。\n"
        )
        path = self.project / "06_manuscript" / "manuscript.md"
        path.write_text(manuscript, encoding="utf-8")
        issues: list[dict[str, str]] = []
        audit_manuscript(self.project, {}, {}, issues)
        self.assertFalse(
            any(item["rule"] == "G4-PLACEHOLDER" for item in issues),
            issues,
        )


if __name__ == "__main__":
    unittest.main()
