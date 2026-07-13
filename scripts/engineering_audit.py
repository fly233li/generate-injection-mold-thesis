from __future__ import annotations

import json
import sys

import _engineering_audit_impl as _impl
from _engineering_audit_impl import *
from common import blocking, issue, read_csv, sort_issues


_quantity_from_impl = _impl.quantity_from
_run_impl = _impl.run_engineering_audit
_RESERVED_PARAMETER_IDS = {"pi", "sqrt", "abs", "sin", "cos", "tan", "min", "max"}


def quantity_from(value, unit, quantity=None):
    normalized = _impl.normalize_unit(unit)
    if normalized == "delta_K":
        normalized = "K"
        quantity = "temperature_difference"
    result = _quantity_from_impl(value, normalized, quantity)
    if normalized == "K" and quantity != "temperature_difference" and not result.absolute:
        result = _impl.Quantity(result.value, result.dims, True)
    if result.absolute and result.value < 0:
        raise ValueError("absolute temperature cannot be below 0 K")
    return result


def run_engineering_audit(project):
    result = _run_impl(project)
    issues = list(result["issues"])
    for index, row in enumerate(read_csv(_impl.project_dir(project) / "03_engineering" / "parameters.csv"), start=2):
        parameter_id = (row.get("param_id") or "").strip()
        if parameter_id in _RESERVED_PARAMETER_IDS:
            issues.append(issue("ENG009", "blocker", "Parameter ID is reserved by the expression engine", parameter_id, f"03_engineering/parameters.csv:{index}"))
    issues = sort_issues(issues)
    result["issues"] = issues
    result["summary"] = {level: sum(1 for item in issues if item["severity"] == level) for level in ("blocker", "error", "warning", "info")}
    result["passed"] = not blocking(issues)
    result["schema_version"] = "2.0"
    return result


_impl.quantity_from = quantity_from
_impl.run_engineering_audit = run_engineering_audit


def main() -> int:
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
