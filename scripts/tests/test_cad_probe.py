from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

import cad_probe
from cad_probe import normalize_nx_root, probe, update_project
from init_project import initialize


class CadProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_nx(self, name: str = "中文 NX 2406") -> Path:
        root = self.root / name
        for relative in (
            "NXBIN/ugraf.exe", "NXBIN/run_journal.exe", "NXBIN/python/NXOpen.pyd",
            "NXBIN/managed/NXOpen.dll", "NXBIN/managed/NXOpen.UF.dll", "UGII/ugii_env_ug.dat",
            "UGII/ugiicmd.bat", "UGII/manifest/platform/configuration.xsd",
            "NXBIN/python/NXOpen_Features.pyd", "NXBIN/python/NXOpen_Drawings.pyd",
        ):
            path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"fixture")
        (root / "MOLDWIZARD").mkdir(); return root

    def test_explicit_chinese_root_is_detected_but_unverified(self) -> None:
        root = self.make_nx()
        result = probe([str(root)], [], config_path=str(self.root / "missing.json"), include_standard=False)
        nx = result["nx"]
        self.assertTrue(nx["detected"]); self.assertEqual(nx["selected_root"], str(root.resolve()))
        self.assertEqual(nx["detection_source"], "explicit_root")
        self.assertEqual(nx["backend"], "candidate_unverified"); self.assertEqual(nx["license_status"], "unknown")
        self.assertEqual(nx["runtime_status"], "not_run"); self.assertEqual(nx["preferred_backend"], "nxopen_python_run_journal")
        self.assertIn("mold_wizard_assets", nx["capability_files_detected"])
        self.assertTrue(nx["command_environment_candidate"].endswith("ugiicmd.bat"))
        self.assertTrue(nx["manifest_schema_candidate"].endswith("configuration.xsd"))

    def test_missing_manifest_schema_blocks_automation_complete(self) -> None:
        root = self.make_nx("missing-schema")
        (root / "UGII" / "manifest" / "platform" / "configuration.xsd").unlink()
        result = probe([str(root)], [], config_path=str(self.root / "none.json"), include_standard=False)
        nx = result["nx"]
        self.assertEqual(nx["preferred_backend"], "candidate_unverified")
        self.assertFalse(nx["installations"][0]["automation_layout_complete"])

    def test_nxbin_and_executable_normalize_to_root(self) -> None:
        root = self.make_nx("portable")
        self.assertEqual(normalize_nx_root(root / "NXBIN"), root.resolve())
        self.assertEqual(normalize_nx_root(root / "NXBIN" / "ugraf.exe"), root.resolve())

    def test_missing_or_invalid_explicit_root_is_rejected(self) -> None:
        with self.assertRaises(FileNotFoundError):
            probe([str(self.root / "missing")], [], config_path=str(self.root / "none.json"), include_standard=False)
        invalid = self.root / "invalid"; invalid.mkdir()
        with self.assertRaisesRegex(ValueError, "ugraf"):
            probe([str(invalid)], [], config_path=str(self.root / "none.json"), include_standard=False)

    def test_config_root_is_used_and_explicit_root_has_priority(self) -> None:
        configured = self.make_nx("configured"); explicit = self.make_nx("explicit")
        config = self.root / "software.json"; config.write_text(json.dumps({"nx_roots": [str(configured)]}), encoding="utf-8")
        result = probe([str(explicit)], [], str(config), include_standard=False)
        self.assertEqual(result["nx"]["selected_root"], str(explicit.resolve()))

    def test_license_environment_never_promotes_static_probe(self) -> None:
        root = self.make_nx("license")
        with mock.patch.dict(os.environ, {"SPLM_LICENSE_SERVER": "28000@example", "UGS_LICENSE_SERVER": "file.lic"}, clear=False):
            result = probe([str(root)], [], config_path=str(self.root / "none.json"), include_standard=False)
        self.assertEqual(result["nx"]["license_status"], "unknown")

    def test_probe_does_not_execute_programs(self) -> None:
        root = self.make_nx("no-exec")
        with mock.patch("os.system", side_effect=AssertionError("must not execute")), mock.patch("os.startfile", side_effect=AssertionError("must not start"), create=True):
            result = probe([str(root)], [], config_path=str(self.root / "none.json"), include_standard=False)
        self.assertTrue(result["nx"]["detected"])

    def test_project_manifest_records_candidate_paths(self) -> None:
        nx_root = self.make_nx("project-nx")
        project = initialize("探测测试", self.root, "project", "from-zero", "nx", "moldflow")
        result = probe([str(nx_root)], [], config_path=str(self.root / "none.json"), include_standard=False)
        update_project(project, result)
        manifest = json.loads((project / "project.json").read_text(encoding="utf-8"))
        software = manifest["software"]
        self.assertEqual(software["nx_root"], str(nx_root.resolve()))
        self.assertTrue(software["nx_executable"].endswith("ugraf.exe"))
        self.assertTrue(software["nx_run_journal"].endswith("run_journal.exe"))
        self.assertTrue(software["nx_command_environment"].endswith("ugiicmd.bat"))
        self.assertTrue(software["nx_manifest_schema"].endswith("configuration.xsd"))
        self.assertEqual(software["nx_backend"], "candidate_unverified")
        self.assertEqual(software["nx_license"], "unknown")

    def test_static_reprobe_preserves_only_current_schema_11_runtime_evidence(self) -> None:
        nx_root = self.make_nx("runtime-evidence")
        project = initialize("Runtime evidence", self.root, "runtime-project", "from-zero", "nx", "none")
        first = probe([str(nx_root)], [], config_path=str(self.root / "none.json"), include_standard=False)
        update_project(project, first)
        output = project / "04_cad/nx/runtime/staging/NX-CURRENT/result.json"
        output.parent.mkdir(parents=True)
        output.write_text('{"ok":true}\n', encoding="utf-8")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        components = {}
        for name, relative in (
            ("ugraf", "NXBIN/ugraf.exe"),
            ("run_journal", "NXBIN/run_journal.exe"),
            ("command_environment", "UGII/ugiicmd.bat"),
            ("manifest_schema", "UGII/manifest/platform/configuration.xsd"),
        ):
            path = nx_root / relative
            components[name] = {"path": str(path), "size": path.stat().st_size, "sha256": digest(path)}
        journal = project / "04_cad/nx/journals/nxopen-probe-journal.py"
        report = output.parent / "nx-stage-run-report.json"
        report.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "success": True,
                    "mapping_removed": True,
                    "journal": journal.relative_to(project).as_posix(),
                    "journal_sha256": digest(journal),
                    "components": components,
                    "expected_files": [
                        {
                            "path": output.relative_to(project).as_posix(),
                            "exists": True,
                            "size": output.stat().st_size,
                            "sha256": digest(output),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        stored = json.loads((project / "software-probe.json").read_text(encoding="utf-8"))
        stored["nx"].update(
            {
                "runtime_status": "verified_runtime",
                "license_status": "available_for_tested_scope",
                "backend": "nxopen_python_run_journal",
                "runtime_validation": {
                    "report": report.relative_to(project).as_posix(),
                    "report_sha256": digest(report),
                },
            }
        )
        (project / "software-probe.json").write_text(json.dumps(stored), encoding="utf-8")
        update_project(project, probe([str(nx_root)], [], str(self.root / "none.json"), include_standard=False))
        current = json.loads((project / "software-probe.json").read_text(encoding="utf-8"))
        self.assertEqual(current["nx"]["runtime_status"], "verified_runtime")

        (nx_root / "NXBIN/run_journal.exe").write_bytes(b"changed")
        update_project(project, probe([str(nx_root)], [], str(self.root / "none.json"), include_standard=False))
        stale = json.loads((project / "software-probe.json").read_text(encoding="utf-8"))
        self.assertEqual(stale["nx"]["runtime_status"], "not_run")
        self.assertIn("run_journal", stale["nx"]["runtime_evidence_stale"])

    def test_project_probe_update_rolls_back_both_json_files_on_write_failure(self) -> None:
        nx_root = self.make_nx("rollback")
        project = initialize("Probe rollback", self.root, "probe-rollback", "from-zero", "nx", "none")
        result = probe([str(nx_root)], [], str(self.root / "none.json"), include_standard=False)
        update_project(project, result)
        before_probe = (project / "software-probe.json").read_bytes()
        before_manifest = (project / "project.json").read_bytes()
        original = cad_probe.atomic_write_json
        calls = 0

        def fail_second(path, data):
            nonlocal calls
            calls += 1
            if calls == 1:
                return original(path, data)
            raise OSError("simulated manifest write failure")

        with mock.patch("cad_probe.atomic_write_json", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "simulated"):
                update_project(project, result)
        self.assertEqual((project / "software-probe.json").read_bytes(), before_probe)
        self.assertEqual((project / "project.json").read_bytes(), before_manifest)


if __name__ == "__main__":
    unittest.main()
