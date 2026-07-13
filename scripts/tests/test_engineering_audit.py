from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from engineering_audit import evaluate_expression, quantity_from, run_engineering_audit
from init_project import initialize


PARAM_FIELDS = ["param_id", "name", "symbol", "value", "unit", "quantity", "origin_type", "source_ref", "status", "assumption_id", "nx_expression", "used_in", "revision"]


class EngineeringAuditTests(unittest.TestCase):
    def make_project(self) -> Path:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return initialize("测试外壳注塑模具设计", Path(temp.name), "test-project", "from-zero", "nx", "moldflow")

    def write_parameters(self, project: Path, rows: list[dict[str, str]]) -> None:
        path = project / "03_engineering" / "parameters.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=PARAM_FIELDS)
            writer.writeheader(); writer.writerows(rows)

    def base_rows(self) -> list[dict[str, str]]:
        common = {field: "" for field in PARAM_FIELDS}
        return [
            dict(common, param_id="AREA", name="投影面积", symbol="A", value="100", unit="mm2", quantity="area", origin_type="SRC", source_ref="SRC-AREA", status="confirmed", used_in="3.2", revision="1"),
            dict(common, param_id="PRESSURE", name="型腔压力", symbol="p", value="50", unit="MPa", quantity="pressure", origin_type="SRC", source_ref="SRC-P", status="confirmed", used_in="3.2", revision="1"),
        ]

    def test_mpa_times_mm2_equals_newton(self) -> None:
        project = self.make_project(); self.write_parameters(project, self.base_rows())
        data = {"schema_version": "2.0", "calculations": [{"id": "CALC_FORCE", "name": "锁模作用力", "expression": "AREA * PRESSURE", "result_value": 5000, "result_unit": "N", "formula_source": "SRC-FORMULA p.10", "tolerance": 1e-9, "status": "confirmed", "used_in": "3.2"}]}
        (project / "03_engineering" / "calculations.json").write_text(json.dumps(data), encoding="utf-8")
        result = run_engineering_audit(project)
        self.assertTrue(result["passed"], result["issues"])

    def test_mass_and_volume_addition_is_blocked(self) -> None:
        project = self.make_project(); rows = self.base_rows(); template = {field: "" for field in PARAM_FIELDS}
        rows.extend([
            dict(template, param_id="SHOT_MASS", name="注射质量", value="30", unit="g", quantity="mass", origin_type="SRC", source_ref="SRC-M", status="confirmed", revision="1"),
            dict(template, param_id="SHOT_VOLUME", name="额定注射体积", value="153", unit="cm3", quantity="volume", origin_type="SRC", source_ref="SRC-V", status="confirmed", revision="1"),
        ])
        self.write_parameters(project, rows)
        data = {"schema_version": "2.0", "calculations": [{"id": "CALC_BAD", "name": "错误比较", "expression": "SHOT_MASS + SHOT_VOLUME", "result_value": 183, "result_unit": "g", "formula_source": "SRC-X p.1", "status": "confirmed"}]}
        (project / "03_engineering" / "calculations.json").write_text(json.dumps(data), encoding="utf-8")
        result = run_engineering_audit(project)
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["rule"] == "CALC007" and "dimension mismatch" in item["message"] for item in result["issues"]))

    def test_absolute_temperature_multiplication_is_blocked(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute temperature"):
            evaluate_expression("T * 2", {"T": quantity_from(250, "degC")})

    def test_absolute_temperature_plus_delta_is_allowed(self) -> None:
        result = evaluate_expression("T + DT", {"T": quantity_from(60, "degC"), "DT": quantity_from(10, "delta_degC")})
        self.assertTrue(result.absolute)
        self.assertAlmostEqual(result.value, 343.15, places=8)

    def test_kelvin_kind_and_absolute_zero_are_checked(self) -> None:
        self.assertTrue(quantity_from(300, "K").absolute)
        self.assertFalse(quantity_from(10, "K", "temperature_difference").absolute)
        self.assertFalse(quantity_from(10, "delta_K").absolute)
        with self.assertRaisesRegex(ValueError, "below 0 K"):
            quantity_from(-500, "degC")

    def test_expression_injection_and_extreme_exponent_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_expression("__import__('os').system('echo bad')", {})
        with self.assertRaisesRegex(ValueError, "exponent magnitude"):
            evaluate_expression("2 ** 1000", {})

    def test_liter_per_minute_conversion(self) -> None:
        self.assertAlmostEqual(quantity_from(6, "L/min").value, 1e-4, places=12)


if __name__ == "__main__":
    unittest.main()
