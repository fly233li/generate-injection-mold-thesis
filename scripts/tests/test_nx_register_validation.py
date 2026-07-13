from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from common import atomic_write_json, read_json
from init_project import initialize
from nx_register_validation import joined_project_relative, register


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class NxRegisterValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = initialize("NX validation", self.base, "nx-validation", "from-zero", "nx", "none")
        self.nx_root = self.base / "NX"
        for relative, content in (
            ("NXBIN/ugraf.exe", b"signed ugraf fixture"),
            ("NXBIN/run_journal.exe", b"signed runner fixture"),
            ("UGII/ugiicmd.bat", b"@echo off"),
            ("UGII/manifest/platform/configuration.xsd", b"<schema/>")
        ):
            path = self.nx_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.signature = {"status": "Valid", "subject": "CN=Siemens fixture", "thumbprint": "00"}
        patcher = mock.patch("nx_register_validation.authenticode_info", return_value=self.signature)
        patcher.start()
        self.addCleanup(patcher.stop)
        manifest = read_json(self.project / "project.json")
        manifest["software"]["nx_root"] = str(self.nx_root)
        atomic_write_json(self.project / "project.json", manifest)
        probe = {
            "schema_version": "2.2",
            "probe_mode": "filesystem_metadata_only",
            "nx": {"selected_root": str(self.nx_root), "runtime_attempts": []},
            "moldflow": {"detected": False},
        }
        atomic_write_json(self.project / "software-probe.json", probe)

    def make_evidence(self, scope: str = "runtime", run_id: str = "NX-TEST") -> tuple[Path, Path]:
        run = self.project / "04_cad/nx/runtime/staging" / run_id
        run.mkdir(parents=True)
        result_path = run / ("nxopen-probe-result.json" if scope == "runtime" else "capability/capability-result.json")
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if scope == "runtime":
            result = {
                "journal": "nxopen-probe-journal.py",
                "nxopen_imported": True,
                "session_acquired": True,
                "nx_full_version": "2406.1700",
                "namespace_imports": {
                    "NXOpen.Features": "ok",
                    "NXOpen.Drawings": "ok",
                    "NXOpen.Drafting": "ok",
                },
                "limitations": ["diagnostic only"],
            }
            output_paths = [result_path]
        else:
            part = run / "capability/nx-capability-probe.prt"
            pdf = run / "capability/nx-capability-probe.pdf"
            part.write_bytes(b"SPLMSSTR fixture")
            pdf.write_bytes(b"%PDF-1.7 test")
            result = {
                "journal": "nx-capability-probe-journal.py",
                "success": True,
                "part_created": True,
                "block_feature_created": True,
                "drawing_sheet_created": True,
                "base_view_created": True,
                "part_saved": True,
                "pdf_exported": True,
                "reopen_succeeded": True,
                "body_count_after_modeling": 1,
                "drawing_view_count": 1,
                "body_count_after_reopen": 1,
                "drawing_sheet_count_after_reopen": 1,
                "drawing_view_count_after_reopen": 1,
                "part_file": "capability/nx-capability-probe.prt",
                "pdf_file": "capability/nx-capability-probe.pdf",
                "part_size_bytes": part.stat().st_size,
                "pdf_size_bytes": pdf.stat().st_size,
                "nx_full_version": "2406.1700",
                "limitations": ["diagnostic only"],
            }
            output_paths = [result_path, part, pdf]
        atomic_write_json(result_path, result)
        expected = []
        for path in output_paths:
            expected.append(
                {
                    "path": path.relative_to(self.project).as_posix(),
                    "exists": True,
                    "size": path.stat().st_size,
                    "sha256": digest(path),
                }
            )
        report_path = run / "nx-stage-run-report.json"
        journal_name = "nxopen-probe-journal.py" if scope == "runtime" else "nx-capability-probe-journal.py"
        journal = self.project / "04_cad/nx/journals" / journal_name
        components = {}
        for name, relative, signed in (
            ("ugraf", "NXBIN/ugraf.exe", True),
            ("run_journal", "NXBIN/run_journal.exe", True),
            ("command_environment", "UGII/ugiicmd.bat", False),
            ("manifest_schema", "UGII/manifest/platform/configuration.xsd", False),
        ):
            path = self.nx_root / relative
            record = {"path": str(path), "size": path.stat().st_size, "sha256": digest(path)}
            if signed:
                record["authenticode"] = self.signature
            components[name] = record
        stdout = run / "stdout.log"
        stderr = run / "stderr.log"
        wrapper = run / "launch.cmd"
        stdout.write_text('{"diagnostic":"ok"}\n', encoding="ascii")
        stderr.write_bytes(b"")
        mapped_journal = "N:\\" + journal.relative_to(self.project).as_posix().replace("/", "\\")
        wrapper.write_text(
            "\r\n".join(
                (
                    '@echo off',
                    'set "UGII_ROOT_DIR="',
                    f'call "{self.nx_root / "UGII/ugiicmd.bat"}" "{self.nx_root}"',
                    f'"{self.nx_root / "NXBIN/run_journal.exe"}" "{mapped_journal}"',
                )
            )
            + "\r\n",
            encoding="ascii",
        )

        def log_record(path: Path) -> dict[str, object]:
            return {
                "path": path.relative_to(self.project).as_posix(),
                "exists": True,
                "size": path.stat().st_size,
                "sha256": digest(path),
            }

        atomic_write_json(
            report_path,
            {
                "schema_version": "1.1",
                "success": True,
                "exit_code": 0,
                "timed_out": False,
                "mapping_removed": True,
                "project": str(self.project),
                "nx_root": str(self.nx_root),
                "run_id": run_id,
                "finished_at": "2026-07-13T00:00:00+00:00",
                "bootstrap": str(self.nx_root / "UGII/ugiicmd.bat"),
                "runner": str(self.nx_root / "NXBIN/run_journal.exe"),
                "journal": journal.relative_to(self.project).as_posix(),
                "journal_sha256": digest(journal),
                "journal_args": [],
                "components": components,
                "staging": {
                    "mode": "subst_project_root",
                    "drive_letter": "N",
                    "physical_target": str(self.project),
                    "run_directory": f"04_cad/nx/runtime/staging/{run_id}",
                    "persist_environment": False,
                    "sets_ugii_root_dir": False,
                },
                "expected_files": expected,
                "system_logs": [],
                "logs_detail": {
                    "stdout": log_record(stdout),
                    "stderr": log_record(stderr),
                    "wrapper": log_record(wrapper),
                },
            },
        )
        return report_path, result_path

    def test_registers_runtime_without_promoting_cad_manifest_and_is_idempotent(self) -> None:
        report, result = self.make_evidence()
        before = (self.project / "04_cad/model-manifest.json").read_bytes()
        output = register(str(self.project), str(report), str(result), "runtime")
        self.assertTrue(output["registered"])
        self.assertFalse(output["cad_artifact_promoted"])
        self.assertEqual(before, (self.project / "04_cad/model-manifest.json").read_bytes())
        probe = read_json(self.project / "software-probe.json")
        self.assertEqual(probe["nx"]["runtime_status"], "verified_runtime")
        probe["nx"]["runtime_validation"] = {
            "status": "newer_validation",
            "report": "04_cad/nx/runtime/staging/NEWER/nx-stage-run-report.json",
        }
        atomic_write_json(self.project / "software-probe.json", probe)
        again = register(str(self.project), str(report), str(result), "runtime")
        self.assertFalse(again["registered"])
        self.assertEqual(len(read_json(self.project / "software-probe.json")["nx"]["runtime_attempts"]), 1)

    def test_capability_requires_hashed_part_and_pdf(self) -> None:
        report, result = self.make_evidence("capability")
        output = register(str(self.project), str(report), str(result), "capability")
        self.assertEqual(output["validation"]["status"], "verified_modeling_drafting_pdf")
        (result.parent / "nx-capability-probe.pdf").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            register(str(self.project), str(report), str(result), "capability")

    def test_failed_or_cross_project_report_is_rejected(self) -> None:
        report, result = self.make_evidence()
        data = read_json(report)
        data["project"] = str(self.base / "other")
        atomic_write_json(report, data)
        with self.assertRaisesRegex(ValueError, "different project|does not match"):
            register(str(self.project), str(report), str(result), "runtime")

    def test_rooted_without_drive_result_paths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            joined_project_relative("04_cad/nx/runtime/staging/RUN", r"\outside.prt", "part_file")
        with self.assertRaises(ValueError):
            joined_project_relative("/outside", "result.json", "result")

    def test_noncanonical_journal_is_rejected_even_when_report_hash_matches(self) -> None:
        report, result = self.make_evidence()
        journal = self.project / "04_cad/nx/journals/nxopen-probe-journal.py"
        journal.write_text("# modified diagnostic\n", encoding="utf-8")
        data = read_json(report)
        data["journal_sha256"] = digest(journal)
        atomic_write_json(report, data)
        with self.assertRaisesRegex(ValueError, "canonical skill journal"):
            register(str(self.project), str(report), str(result), "runtime")

    def test_lower_scope_attempt_does_not_downgrade_current_capability(self) -> None:
        cap_report, cap_result = self.make_evidence("capability", "NX-CAP-HIGH")
        register(str(self.project), str(cap_report), str(cap_result), "capability")
        runtime_report, runtime_result = self.make_evidence("runtime", "NX-RUNTIME-LOW")
        output = register(str(self.project), str(runtime_report), str(runtime_result), "runtime")
        self.assertFalse(output["current_status_updated"])
        probe = read_json(self.project / "software-probe.json")
        self.assertEqual(probe["nx"]["runtime_status"], "verified_modeling_drafting_pdf")
        self.assertEqual(len(probe["nx"]["runtime_attempts"]), 2)


if __name__ == "__main__":
    unittest.main()
