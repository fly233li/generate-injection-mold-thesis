from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import sys
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from init_project import initialize
from nx_stage_run import command_wrapper, execute, load_runtime_profile, safe_relative, unmap_drive


class NxStageRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        signature = {"status": "Valid", "subject": "CN=Siemens fixture", "thumbprint": "00"}
        patcher = mock.patch("nx_stage_run.authenticode_info", return_value=signature)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_nx(self, name: str = "NX") -> Path:
        root = self.root / name
        for relative in (
            "NXBIN/ugraf.exe",
            "NXBIN/run_journal.exe",
            "NXBIN/python/NXOpen.pyd",
            "NXBIN/managed/NXOpen.dll",
            "NXBIN/managed/NXOpen.UF.dll",
            "UGII/ugii_env_ug.dat",
            "UGII/ugiicmd.bat",
            "UGII/manifest/platform/configuration.xsd",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        return root

    def make_project(self) -> Path:
        return initialize("NX暂存测试", self.root, "nx-stage-project", "from-zero", "nx", "none")

    def args(self, project: Path, nx_root: Path, **changes):
        values = {
            "project": str(project),
            "journal": "04_cad/nx/journals/nxopen-probe-journal.py",
            "nx_root": str(nx_root),
            "timeout_seconds": None,
            "drive_letter": None,
            "run_id": "NX-DRY-RUN",
            "journal_arg": [],
            "expected": [],
            "expected_run_file": ["nxopen-probe-result.json"],
            "dry_run": True,
        }
        values.update(changes)
        return SimpleNamespace(**values)

    def test_dry_run_plans_project_local_subst_without_writing_run_dir(self) -> None:
        project = self.make_project()
        nx_root = self.make_nx()
        report, code = execute(self.args(project, nx_root))
        self.assertEqual(code, 0)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["staging"]["mode"], "subst_project_root")
        self.assertEqual(report["staging"]["physical_target"], str(project.resolve()))
        self.assertEqual(report["schema_version"], "1.1")
        self.assertEqual(report["components"]["run_journal"]["authenticode"]["status"], "Valid")
        self.assertFalse((project / "04_cad/nx/runtime/staging/NX-DRY-RUN").exists())

    def test_non_ascii_nx_root_is_rejected(self) -> None:
        project = self.make_project()
        nx_root = self.make_nx("中文NX")
        with self.assertRaisesRegex(ValueError, "NX root.*ASCII"):
            load_runtime_profile(project, str(nx_root))

    def test_path_traversal_and_unsafe_journal_argument_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            safe_relative("../outside.prt", "expected output")
        with self.assertRaises(ValueError):
            safe_relative(r"\outside.prt", "expected output")
        with self.assertRaises(ValueError):
            safe_relative("/outside.prt", "expected output")
        project = self.make_project()
        nx_root = self.make_nx()
        with self.assertRaisesRegex(ValueError, "unsafe"):
            execute(self.args(project, nx_root, journal_arg=["name=bad&command"]))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            execute(self.args(project, nx_root, journal_arg=['name=bad"quote']))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            execute(self.args(project, nx_root, journal_arg=["name=bad(group)"]))

    def test_run_requires_at_least_one_expected_file(self) -> None:
        project = self.make_project()
        nx_root = self.make_nx()
        with self.assertRaisesRegex(ValueError, "At least one"):
            execute(self.args(project, nx_root, expected_run_file=[]))

    def test_wrapper_uses_official_command_environment_and_clears_ugii_root(self) -> None:
        nx_root = self.make_nx()
        profile = {
            "nx_root": nx_root,
            "bootstrap": nx_root / "UGII/ugiicmd.bat",
            "runner": nx_root / "NXBIN/run_journal.exe",
        }
        wrapper = command_wrapper(
            profile,
            "N",
            Path("04_cad/nx/journals/nxopen-probe-journal.py"),
            Path("04_cad/nx/runtime/staging/NX-TEST"),
            [],
        )
        self.assertIn('set "UGII_ROOT_DIR="', wrapper)
        self.assertIn('call "' + str(profile["bootstrap"]) + '" "' + str(nx_root) + '"', wrapper)
        self.assertNotIn("UGII_ROOT_DIR=" + str(nx_root), wrapper)

    def test_unmap_refuses_to_delete_a_mapping_owned_by_another_target(self) -> None:
        with mock.patch("nx_stage_run.drive_target", return_value=Path(r"C:\other-project")), mock.patch(
            "nx_stage_run.subprocess.run"
        ) as run:
            self.assertFalse(unmap_drive("N", Path(r"C:\expected-project")))
            run.assert_not_called()

    def test_execute_attempts_owner_aware_cleanup_when_mapping_verification_fails(self) -> None:
        project = self.make_project()
        nx_root = self.make_nx()
        args = self.args(project, nx_root, run_id="NX-MAP-FAIL", dry_run=False)
        with mock.patch("nx_stage_run.map_drive", side_effect=RuntimeError("verification failed")), mock.patch(
            "nx_stage_run.unmap_drive", return_value=True
        ) as cleanup:
            report, code = execute(args)
        self.assertEqual(code, 1)
        self.assertTrue(report["mapping_removed"])
        cleanup.assert_called_once_with("N", project.resolve())


if __name__ == "__main__":
    unittest.main()
