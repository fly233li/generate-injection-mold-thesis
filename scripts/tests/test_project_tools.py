from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from audit_project import run_audit
from common import atomic_write_json, read_json
from init_project import initialize
from project_state import approve, effective_project_state, effective_status, migrate_snapshots, reopen, snapshot


class ProjectToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_project(self, slug: str = "test-project") -> Path:
        return initialize("壁挂式路由器外壳注塑模具设计", self.root, slug, "from-zero", "nx", "moldflow")

    def evidence(self, project: Path, gate: str, text: str | None = None) -> Path:
        path = project / "approvals" / f"{gate.lower()}-approval.md"
        path.write_text(text or f"用户确认 {gate} 评审包。\n", encoding="utf-8")
        return path

    def approve_all(self, project: Path) -> dict:
        with patch("project_state.run_audit", return_value={"passed": True, "issues": []}):
            manifest = {}
            for gate in ("G1", "G2", "G3", "G4"):
                manifest = approve(project, gate, f"approve {gate}", "tester", self.evidence(project, gate))
        return manifest

    def test_chinese_title_initialization(self) -> None:
        project = self.make_project("chinese-project")
        manifest = read_json(project / "project.json")
        self.assertEqual(manifest["title"], "壁挂式路由器外壳注塑模具设计")
        self.assertEqual(manifest["classification"], "EDU-CONCEPT")
        self.assertTrue((project / "00_requirements" / "design-basis.json").is_file())
        self.assertTrue((project / "04_cad" / "drawings.csv").is_file())

    def test_duplicate_initialization_does_not_overwrite(self) -> None:
        self.make_project("same-project")
        with self.assertRaises(FileExistsError):
            initialize("另一个题目", self.root, "same-project", "from-zero", "nx", "moldflow")

    def test_initial_g1_is_blocked_until_design_basis_exists(self) -> None:
        project = self.make_project("audit-project")
        result = run_audit(project, "G1")
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["severity"] in {"blocker", "error"} for item in result["issues"]))

    def test_gate_cannot_skip_prior_gate(self) -> None:
        project = self.make_project("skip-project")
        with self.assertRaisesRegex(RuntimeError, "prior gate G1"):
            approve(project, "G2", "skip", "user", self.evidence(project, "G2"))

    def test_status_reports_pending_and_effective_top_state(self) -> None:
        project = self.make_project("status-project")
        manifest = read_json(project / "project.json")
        statuses = effective_status(project, manifest)
        self.assertTrue(all(record["effective_status"] == "pending" for record in statuses.values()))
        self.assertEqual(
            effective_project_state(project, manifest),
            {"status": "intake", "maturity_level": "L0", "release_level": "draft"},
        )

    def test_approval_requires_nonempty_evidence_inside_approvals(self) -> None:
        project = self.make_project("evidence-project")
        outside = self.root / "outside.md"
        outside.write_text("confirmed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inside the project's approvals"):
            approve(project, "G1", "confirm", "user", outside)
        empty = project / "approvals" / "empty.md"
        empty.touch()
        with self.assertRaisesRegex(ValueError, "non-empty"):
            approve(project, "G1", "confirm", "user", empty)
        with self.assertRaisesRegex(ValueError, "cannot be used"):
            approve(project, "G1", "confirm", "user", project / "approvals" / "README.md")

    def test_approval_records_hashed_evidence_and_canonical_snapshot(self) -> None:
        project = self.make_project("approval-project")
        evidence = self.evidence(project, "G1")
        with patch("project_state.run_audit", return_value={"passed": True, "issues": []}):
            manifest = approve(project, "G1", "用户确认设计基线", "user", evidence)
        record = manifest["gates"]["G1"]
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["evidence"]["path"], "approvals/g1-approval.md")
        self.assertRegex(record["evidence"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(record["snapshot"]["sha256"], record["snapshot_hash"])
        self.assertEqual(record["snapshot"]["schema_version"], 3)
        self.assertTrue(all(set(entry) == {"path", "length", "sha256"} for entry in record["snapshot"]["entries"]))
        self.assertEqual(record["snapshot"]["entries"][0]["path"], "@project.json:controlled")
        self.assertEqual(manifest["status"], "evidence_plan")
        self.assertEqual(manifest["maturity_level"], "L2")
        history = (project / "approvals" / "history.jsonl").read_text(encoding="utf-8").splitlines()
        event = json.loads(history[-1])
        self.assertEqual(event["action"], "approve")
        self.assertEqual(event["evidence"]["sha256"], record["evidence"]["sha256"])

    def test_approval_is_not_committed_if_audit_changes_review_package(self) -> None:
        project = self.make_project("race-project")
        outline = project / "01_outline" / "outline.md"

        def mutating_audit(*_args, **_kwargs):
            outline.write_text(outline.read_text(encoding="utf-8") + "\nchanged during audit\n", encoding="utf-8")
            return {"passed": True, "issues": []}

        with patch("project_state.run_audit", side_effect=mutating_audit):
            with self.assertRaisesRegex(RuntimeError, "changed during audit"):
                approve(project, "G1", "confirm", "user", self.evidence(project, "G1"))
        manifest = read_json(project / "project.json")
        self.assertEqual(manifest["gates"]["G1"]["status"], "pending")
        self.assertFalse((project / ".project-state.lock").exists())

    def test_changed_referenced_artifact_stales_gate_and_all_later_approvals(self) -> None:
        project = self.make_project("artifact-stale-project")
        artifact = project / "04_cad" / "exports" / "plastic_part.step"
        artifact.write_bytes(b"STEP revision 1")
        cad_manifest = read_json(project / "04_cad" / "model-manifest.json")
        cad_manifest["files"] = [{"role": "neutral_part", "path": "04_cad/exports/plastic_part.step"}]
        atomic_write_json(project / "04_cad" / "model-manifest.json", cad_manifest)
        self.approve_all(project)

        artifact.write_bytes(b"STEP revision 2")
        manifest = read_json(project / "project.json")
        statuses = effective_status(project, manifest)
        self.assertEqual(statuses["G1"]["effective_status"], "approved")
        self.assertEqual(statuses["G2"]["effective_status"], "approved")
        self.assertEqual(statuses["G3"]["effective_status"], "stale")
        self.assertEqual(statuses["G4"]["effective_status"], "stale")
        self.assertIn("a prior gate", " ".join(statuses["G4"]["stale_reasons"]))
        self.assertEqual(
            effective_project_state(project, manifest),
            {"status": "engineering", "maturity_level": "L2", "release_level": "draft"},
        )

    def test_changed_project_design_field_stales_all_approved_gates(self) -> None:
        project = self.make_project("project-field-stale")
        self.approve_all(project)
        manifest = read_json(project / "project.json")
        manifest["design_basis_version"] = 2
        atomic_write_json(project / "project.json", manifest)
        statuses = effective_status(project, manifest)
        self.assertTrue(all(statuses[gate]["effective_status"] == "stale" for gate in ("G1", "G2", "G3", "G4")))
        self.assertEqual(effective_project_state(project, manifest)["maturity_level"], "L0")

    def test_changed_software_config_does_not_stale_design_approvals(self) -> None:
        project = self.make_project("software-field-operational")
        self.approve_all(project)
        manifest = read_json(project / "project.json")
        manifest["software"]["nx_root"] = r"E:\UG2406\NX"
        manifest["software"]["software_revision"] = 2
        atomic_write_json(project / "project.json", manifest)
        statuses = effective_status(project, manifest)
        self.assertTrue(all(statuses[gate]["effective_status"] == "approved" for gate in ("G1", "G2", "G3", "G4")))

    def test_changed_requested_cad_or_cae_stales_design_approvals(self) -> None:
        project = self.make_project("software-request-design-field")
        self.approve_all(project)
        manifest = read_json(project / "project.json")
        manifest["software"]["cad_requested"] = "other-cad"
        atomic_write_json(project / "project.json", manifest)
        statuses = effective_status(project, manifest)
        self.assertTrue(all(statuses[gate]["effective_status"] == "stale" for gate in ("G1", "G2", "G3", "G4")))

    def test_unsupported_snapshot_schema_zero_fails_closed(self) -> None:
        project = self.make_project("snapshot-schema-zero")
        with self.assertRaisesRegex(ValueError, "Unsupported snapshot schema"):
            snapshot(project, "G1", schema_version=0)
        with self.assertRaisesRegex(ValueError, "Unsupported snapshot schema"):
            snapshot(project, "G1", schema_version=True)

    def test_legacy_snapshot_migration_is_traced_and_preserves_approval(self) -> None:
        project = self.make_project("legacy-snapshot-migration")
        manifest = self.approve_all(project)
        previous_hashes = {}
        for gate in ("G1", "G2", "G3", "G4"):
            legacy = snapshot(project, gate, manifest_override=manifest, include_software=True)
            legacy.pop("schema_version", None)
            manifest["gates"][gate]["snapshot"] = legacy
            manifest["gates"][gate]["snapshot_hash"] = legacy["sha256"]
            previous_hashes[gate] = legacy["sha256"]
        atomic_write_json(project / "project.json", manifest)
        self.assertTrue(all(item["effective_status"] == "approved" for item in effective_status(project, manifest).values()))

        migrated = migrate_snapshots(project, "separate operational software state", "tester")
        for gate in ("G1", "G2", "G3", "G4"):
            record = migrated["gates"][gate]
            self.assertEqual(record["snapshot"]["schema_version"], 3)
            self.assertEqual(record["snapshot_migrations"][-1]["previous_snapshot_sha256"], previous_hashes[gate])
        self.assertTrue(all(item["effective_status"] == "approved" for item in effective_status(project, migrated).values()))
        history = [json.loads(line) for line in (project / "approvals" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(history[-1]["action"], "migrate_snapshots")

        repeated = migrate_snapshots(project, "idempotence check", "tester")
        for gate in ("G1", "G2", "G3", "G4"):
            self.assertEqual(len(repeated["gates"][gate]["snapshot_migrations"]), 1)

    def test_schema_two_snapshot_migrates_to_three_without_software_runtime_staleness(self) -> None:
        project = self.make_project("schema-two-migration")
        manifest = self.approve_all(project)
        for gate in ("G1", "G2", "G3", "G4"):
            old = snapshot(project, gate, manifest_override=manifest, schema_version=2)
            manifest["gates"][gate]["snapshot"] = old
            manifest["gates"][gate]["snapshot_hash"] = old["sha256"]
        atomic_write_json(project / "project.json", manifest)
        manifest["software"]["nx_root"] = r"E:\UG2406\NX"
        atomic_write_json(project / "project.json", manifest)
        self.assertTrue(all(item["effective_status"] == "approved" for item in effective_status(project, manifest).values()))
        migrated = migrate_snapshots(project, "schema two to three", "tester")
        self.assertTrue(all(item["effective_status"] == "approved" for item in effective_status(project, migrated).values()))
        self.assertTrue(
            all(
                migrated["gates"][gate]["snapshot"]["schema_version"] == 3
                for gate in ("G1", "G2", "G3", "G4")
            )
        )

    def test_changed_or_missing_approval_evidence_stales_and_cascades(self) -> None:
        project = self.make_project("approval-stale-project")
        self.approve_all(project)
        (project / "approvals" / "g2-approval.md").write_text("modified", encoding="utf-8")
        statuses = effective_status(project, read_json(project / "project.json"))
        self.assertEqual(statuses["G1"]["effective_status"], "approved")
        self.assertEqual(statuses["G2"]["effective_status"], "stale")
        self.assertEqual(statuses["G3"]["effective_status"], "stale")
        self.assertEqual(statuses["G4"]["effective_status"], "stale")

    def test_prepared_unexecuted_manifests_never_inflate_maturity(self) -> None:
        project = self.make_project("prepared-project")
        cad = read_json(project / "04_cad" / "model-manifest.json")
        cad["status"] = "prepared_unexecuted"
        cad["license_status"] = "available"
        cad["files"] = [{"path": "04_cad/exports/plastic_part.step"}]
        cad["execution"].update({"exit_code": 0, "opened_verified": True})
        atomic_write_json(project / "04_cad" / "model-manifest.json", cad)
        cae = read_json(project / "05_cae" / "moldflow-study.json")
        cae["status"] = "prepared_unexecuted"
        cae["license_status"] = "available"
        cae["result_files"] = [{"path": "05_cae/results/fill.csv"}]
        cae["solver_log"] = "05_cae/results/solver.log"
        cae["execution"].update({"exit_code": 0, "success": True})
        atomic_write_json(project / "05_cae" / "moldflow-study.json", cae)
        manifest = self.approve_all(project)
        self.assertEqual(manifest["maturity_level"], "L2")
        self.assertEqual(manifest["release_level"], "teaching-concept")

    def test_maturity_l4_requires_actual_cad_and_cae_execution(self) -> None:
        project = self.make_project("executed-project")
        cad_file = project / "04_cad" / "exports" / "plastic_part.step"
        cad_file.write_bytes(b"verified CAD")
        cad = read_json(project / "04_cad" / "model-manifest.json")
        cad.update({"status": "verified", "license_status": "available"})
        cad["files"] = [{"path": "04_cad/exports/plastic_part.step"}]
        cad["execution"].update({"exit_code": 0, "opened_verified": True})
        atomic_write_json(project / "04_cad" / "model-manifest.json", cad)
        result_file = project / "05_cae" / "results" / "fill.csv"
        result_file.write_text("fill_time_s,1.2\n", encoding="utf-8")
        solver_log = project / "05_cae" / "results" / "solver.log"
        solver_log.write_text("success\n", encoding="utf-8")
        cae = read_json(project / "05_cae" / "moldflow-study.json")
        cae.update({"status": "verified", "license_status": "available"})
        cae["result_files"] = [{"path": "05_cae/results/fill.csv"}]
        cae["solver_log"] = "05_cae/results/solver.log"
        cae["execution"].update({"exit_code": 0, "success": True})
        atomic_write_json(project / "05_cae" / "moldflow-study.json", cae)
        manifest = self.approve_all(project)
        self.assertEqual(manifest["maturity_level"], "L4")
        self.assertEqual(manifest["release_level"], "verified-course-design")

    def test_reopen_rolls_back_state_and_keeps_append_only_history(self) -> None:
        project = self.make_project("reopen-project")
        self.approve_all(project)
        manifest = reopen(project, "G2", "material changed", "reviewer")
        self.assertEqual(manifest["status"], "evidence_plan")
        self.assertEqual(manifest["maturity_level"], "L2")
        self.assertEqual(manifest["release_level"], "draft")
        self.assertEqual(manifest["gates"]["G1"]["status"], "approved")
        self.assertTrue(all(manifest["gates"][gate]["status"] == "pending" for gate in ("G2", "G3", "G4")))
        history = [json.loads(line) for line in (project / "approvals" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(history), 5)
        self.assertEqual(history[-1]["action"], "reopen")
        self.assertEqual(history[-1]["gate"], "G2")


if __name__ == "__main__":
    unittest.main()
