from __future__ import annotations

import csv
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import register_record as register_module
from common import read_csv
from init_project import initialize
from register_record import KINDS, load_record, register


class RegisterRecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = initialize(
            "登记测试",
            Path(self.temp.name),
            "register-project",
            "from-zero",
            "nx",
            "moldflow",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def assumption(revision: int = 1, status: str = "proposed", value: int = 200000) -> dict[str, object]:
        return {
            "assumption_id": "ASM-001",
            "statement": "暂定年产量",
            "value": value,
            "unit": "件/a",
            "criticality": "K3",
            "basis_source_id": "SRC-001",
            "uncertainty_or_range": "±10%",
            "status": status,
            "approval_gate": "G1",
            "affected_items": ["PAR-CAVITY_COUNT"],
            "validation_method": "用户确认",
            "revision": revision,
            "supersedes": "" if revision == 1 else f"ASM-001@{revision - 1}",
        }

    def valid_records(self) -> dict[str, dict[str, object]]:
        return {
            "requirement": {
                "req_id": "REQ-001",
                "category": "deliverable",
                "requirement": "提交模具总装图",
                "origin": "user",
                "priority": "must",
                "acceptance": "存在经校核的总装图 PDF",
                "chapter_id": "4",
                "calc_ids": ["CALC-001"],
                "drawing_ids": ["DWG-001"],
                "case_ids": [],
                "verification": "G3 audit",
                "status": "approved",
                "revision": 1,
                "supersedes": "",
            },
            "assumption": self.assumption(),
            "parameter": {
                "param_id": "wall_thickness",
                "name": "名义壁厚",
                "symbol": "t",
                "value": 2.5,
                "unit": "mm",
                "quantity": "length",
                "origin_type": "DEC",
                "source_ref": "DEC-001",
                "status": "proposed",
                "assumption_id": "",
                "nx_expression": "wall_thickness",
                "used_in": "",
                "revision": 1,
            },
            "decision": {
                "decision_id": "DEC-001",
                "category": "material",
                "question": "塑件材料选择",
                "alternatives": ["ABS", "PC/ABS"],
                "selected_option": "",
                "rationale": "",
                "evidence_ids": [],
                "impact": "影响成型温度和收缩率",
                "status": "proposed",
                "revision": 1,
            },
            "source": {
                "source_id": "SRC-001",
                "source_type": "journal",
                "title": "注塑模具浇注系统研究",
                "authors_or_org": "张三",
                "year": 2024,
                "journal_or_publisher": "模具工业",
                "volume": "50",
                "issue": "1",
                "pages_or_article_no": "1-8",
                "doi": "",
                "cnki_url_or_record_id": "CNKI:SUN:TEST.0.2024-01-001",
                "official_url": "",
                "access_date": "2026-07-12",
                "access_level": "abstract",
                "exact_locator": "摘要",
                "claim_ids": [],
                "status": "verified",
                "rejection_reason": "",
                "citation_key": "zhang2024",
                "used_in": "",
                "revision": 1,
            },
            "claim": {
                "claim_id": "CLM-001",
                "claim_text": "点浇口有利于自动脱料",
                "claim_type": "fact",
                "source_ids": ["SRC-001"],
                "exact_locator": "摘要",
                "section_id": "3.2",
                "status": "verified",
                "revision": 1,
            },
            "placement": {
                "object_id": "FIG-001",
                "object_type": "figure",
                "title_or_caption": "塑件三维模型",
                "section_id": "2.1",
                "first_mention_claim_id": "CLM-001",
                "insertion_position": "2.1 节首段后",
                "purpose": "说明塑件总体结构",
                "source_or_artifact_id": "ART-CAD-001",
                "file": "06_manuscript/figures/part.png",
                "word_bookmark_or_field": "bm_FIG_001",
                "status": "planned",
                "revision": 1,
            },
            "drawing": {
                "drawing_id": "DWG-001",
                "title": "模具总装图",
                "drawing_type": "assembly",
                "file": "04_cad/drawings/DWG-001.pdf",
                "model_revision": "R1",
                "requirement_ids": ["REQ-001"],
                "status": "planned",
                "checked_by": "",
                "revision": 1,
                "notes": "待 NX 出图",
            },
            "bom": {
                "item_id": "BOM-001",
                "item_no": "1",
                "part_name": "定模板",
                "quantity": 1,
                "material": "45钢",
                "standard_or_drawing_id": "DWG-002",
                "model_revision": "R1",
                "status": "proposed",
                "revision": 1,
                "notes": "",
            },
            "change": {
                "change_id": "CHG-001",
                "changed_at": "2026-07-12T10:00:00+00:00",
                "actor": "user",
                "reason": "修改年产量",
                "affected_ids": ["ASM-001", "PAR-CAVITY_COUNT"],
                "reopened_gate": "G1",
                "status": "approved",
                "revision": 1,
            },
        }

    def test_all_fixed_kinds_create_with_exact_template_headers(self) -> None:
        records = self.valid_records()
        self.assertEqual(set(records), set(KINDS))
        for kind, record in records.items():
            with self.subTest(kind=kind):
                result = register(self.project, kind, record)
                self.assertEqual(result["action"], "created")
                schema = KINDS[kind]
                path = self.project / schema.relative
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(tuple(reader.fieldnames or ()), schema.fields)
                    rows = list(reader)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][schema.id_field], str(record[schema.id_field]))

    def test_required_id_enum_and_revision_validation(self) -> None:
        record = self.assumption()
        del record["statement"]
        with self.assertRaisesRegex(ValueError, "Missing required record fields: statement"):
            register(self.project, "assumption", record)

        record = self.assumption()
        record["assumption_id"] = "asm 1"
        with self.assertRaisesRegex(ValueError, "Invalid assumption_id format"):
            register(self.project, "assumption", record)

        record = self.assumption()
        record["status"] = "done"
        with self.assertRaisesRegex(ValueError, "Invalid status"):
            register(self.project, "assumption", record)

        for revision in (0, -1, "1.5", "01", True):
            with self.subTest(revision=revision):
                record = self.assumption()
                record["revision"] = revision
                with self.assertRaisesRegex(ValueError, "revision must be a positive integer"):
                    register(self.project, "assumption", record)

    def test_schema_alignment_for_gate_statuses_and_required_links(self) -> None:
        requirement = self.valid_records()["requirement"]
        self.assertEqual(register(self.project, "requirement", requirement)["action"], "created")

        fresh = self.temp.name + "-required"
        with tempfile.TemporaryDirectory(dir=Path(self.temp.name).parent) as other:
            project = initialize("必填测试", Path(other), "required-project", "from-zero", "nx", "moldflow")
            for field in ("chapter_id", "verification"):
                with self.subTest(field=field):
                    invalid = dict(requirement)
                    invalid["req_id"] = f"REQ-{field.upper()}"
                    invalid[field] = ""
                    with self.assertRaisesRegex(ValueError, field):
                        register(project, "requirement", invalid)

        drawing = self.valid_records()["drawing"]
        drawing["status"] = "prepared"
        self.assertEqual(register(self.project, "drawing", drawing)["action"], "created")
        bom = self.valid_records()["bom"]
        bom["status"] = "prepared"
        self.assertEqual(register(self.project, "bom", bom)["action"], "created")

    def test_parameter_ids_are_formula_identifiers_and_reserved_names_are_rejected(self) -> None:
        record = self.valid_records()["parameter"]
        self.assertEqual(register(self.project, "parameter", record)["id"], "wall_thickness")

        with tempfile.TemporaryDirectory(dir=Path(self.temp.name).parent) as other:
            project = initialize("参数测试", Path(other), "parameter-project", "from-zero", "nx", "moldflow")
            for invalid_id in ("P-001", "pi", "sqrt", "abs", "sin", "cos", "tan", "min", "max", "for", "True"):
                with self.subTest(param_id=invalid_id):
                    invalid = dict(record)
                    invalid["param_id"] = invalid_id
                    expected = "Reserved parameter identifier" if invalid_id != "P-001" else "Invalid param_id format"
                    with self.assertRaisesRegex(ValueError, expected):
                        register(project, "parameter", invalid)

    def test_external_claims_require_sources_but_internal_claims_do_not(self) -> None:
        external = self.valid_records()["claim"]
        external["claim_type"] = "external"
        external["source_ids"] = []
        with self.assertRaisesRegex(ValueError, "source_ids"):
            register(self.project, "claim", external)
        external["source_ids"] = ["SRC-001"]
        external["exact_locator"] = ""
        with self.assertRaisesRegex(ValueError, "exact_locator"):
            register(self.project, "claim", external)

        internal = dict(external)
        internal["claim_type"] = "design_decision"
        internal["source_ids"] = []
        internal["exact_locator"] = ""
        self.assertEqual(register(self.project, "claim", internal)["action"], "created")

    def test_placement_requires_first_mention_and_dynamic_field(self) -> None:
        record = self.valid_records()["placement"]
        for field in ("first_mention_claim_id", "word_bookmark_or_field"):
            with self.subTest(field=field):
                invalid = dict(record)
                invalid[field] = ""
                with self.assertRaisesRegex(ValueError, field):
                    register(self.project, "placement", invalid)
        record["file"] = ""
        self.assertEqual(register(self.project, "placement", record)["action"], "created")

    def test_unknown_fields_and_corrupt_header_are_rejected(self) -> None:
        record = self.assumption()
        record["bogus"] = 1
        with self.assertRaisesRegex(ValueError, "Unknown record fields"):
            register(self.project, "assumption", record)

        ledger = self.project / "00_requirements" / "assumptions.csv"
        ledger.write_text("assumption_id,revision\n", encoding="utf-8-sig")
        with self.assertRaisesRegex(ValueError, "Invalid ledger header"):
            register(self.project, "assumption", self.assumption())

    def test_cas_replacement_archives_every_old_revision(self) -> None:
        register(self.project, "assumption", self.assumption(1, "proposed", 200000))
        result = register(
            self.project,
            "assumption",
            self.assumption(2, "approved", 220000),
            "1",
        )
        self.assertEqual(result["action"], "replaced")
        self.assertEqual(result["revision"], "2")
        self.assertEqual(result["history_ledger"], "00_requirements/assumptions.history.csv")

        register(
            self.project,
            "assumption",
            self.assumption(5, "approved", 250000),
            "2",
        )
        current = read_csv(self.project / "00_requirements" / "assumptions.csv")
        history = read_csv(self.project / "00_requirements" / "assumptions.history.csv")
        self.assertEqual([(row["revision"], row["value"]) for row in current], [("5", "250000")])
        self.assertEqual(
            [(row["revision"], row["value"]) for row in history],
            [("1", "200000"), ("2", "220000")],
        )

    def test_duplicate_mismatch_and_nonincreasing_revision_do_not_mutate(self) -> None:
        original = self.assumption()
        register(self.project, "assumption", original)
        with self.assertRaises(FileExistsError):
            register(self.project, "assumption", original)
        with self.assertRaisesRegex(RuntimeError, "Revision mismatch"):
            register(self.project, "assumption", self.assumption(2), "9")
        with self.assertRaisesRegex(ValueError, "must be greater"):
            register(self.project, "assumption", self.assumption(1), "1")

        ledger = self.project / "00_requirements" / "assumptions.csv"
        self.assertEqual(read_csv(ledger)[0]["revision"], "1")
        self.assertFalse((ledger.parent / "assumptions.history.csv").exists())

    def test_true_cas_under_concurrent_updates(self) -> None:
        register(self.project, "assumption", self.assumption())
        barrier = threading.Barrier(3)
        successes: list[int] = []
        failures: list[Exception] = []

        def worker(value: int) -> None:
            barrier.wait()
            try:
                register(self.project, "assumption", self.assumption(2, "approved", value), "1")
                successes.append(value)
            except Exception as exc:  # exact losing exception is checked below
                failures.append(exc)

        threads = [threading.Thread(target=worker, args=(value,)) for value in (210000, 230000)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=5)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], RuntimeError)
        current = read_csv(self.project / "00_requirements" / "assumptions.csv")
        history = read_csv(self.project / "00_requirements" / "assumptions.history.csv")
        self.assertEqual(current[0]["revision"], "2")
        self.assertEqual(current[0]["value"], str(successes[0]))
        self.assertEqual([(row["revision"], row["value"]) for row in history], [("1", "200000")])

    def test_crash_between_history_and_current_is_recoverable_without_history_loss(self) -> None:
        register(self.project, "assumption", self.assumption())
        ledger = self.project / "00_requirements" / "assumptions.csv"
        real_atomic_write = register_module.atomic_write_text

        def fail_current(path: Path, text: str, encoding: str = "utf-8") -> None:
            if path == ledger:
                raise OSError("simulated failure after history commit")
            real_atomic_write(path, text, encoding)

        with patch.object(register_module, "atomic_write_text", side_effect=fail_current):
            with self.assertRaisesRegex(OSError, "simulated failure"):
                register(self.project, "assumption", self.assumption(2, "approved", 220000), "1")

        self.assertEqual(read_csv(ledger)[0]["revision"], "1")
        history_path = ledger.parent / "assumptions.history.csv"
        self.assertEqual(read_csv(history_path)[0]["revision"], "1")

        register(self.project, "assumption", self.assumption(2, "approved", 220000), "1")
        self.assertEqual(read_csv(ledger)[0]["revision"], "2")
        self.assertEqual(len(read_csv(history_path)), 1)

    def test_load_record_requires_exactly_one_json_object(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            load_record(None, None)
        with self.assertRaisesRegex(ValueError, "JSON object"):
            load_record(None, json.dumps([1, 2, 3]))
        self.assertEqual(load_record(None, '{"revision":1}'), {"revision": 1})


if __name__ == "__main__":
    unittest.main()


