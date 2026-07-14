from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moldflow_probe import TOOLS, find_cli_bins
from moldflow_run import metadata_ready


class MoldflowToolTests(unittest.TestCase):
    def test_find_cli_bin_requires_complete_toolset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            incomplete = root / "incomplete" / "bin"; incomplete.mkdir(parents=True)
            (incomplete / "runstudy.exe").write_bytes(b"x")
            complete = root / "Moldflow Insight 2024" / "bin"; complete.mkdir(parents=True)
            for tool in TOOLS:
                (complete / tool).write_bytes(b"x")
            self.assertEqual(find_cli_bins([str(root)]), [complete.resolve()])

    def test_metadata_ready_rejects_placeholder_values(self) -> None:
        data = {
            "tool_version": "unknown", "material_grade": "unselected", "material_card_id": "unknown",
            "geometry_revision": "none", "mesh": {}, "cases": [],
        }
        missing = metadata_ready(data, "CASE-BASELINE")
        self.assertIn("tool_version", missing)
        self.assertIn("cases[CASE-BASELINE]", missing)

    def test_metadata_ready_accepts_registered_case(self) -> None:
        data = {
            "tool_version": "2024", "material_grade": "PP", "material_card_id": "123",
            "geometry_revision": "M01", "mesh": {"type": "dual_domain", "target_size_mm": 1, "element_count": 100, "quality_metrics": {"aspect": 1}},
            "cases": [{"case_id": "CASE-BASELINE"}],
        }
        self.assertEqual(metadata_ready(data, "CASE-BASELINE"), [])


if __name__ == "__main__":
    unittest.main()
