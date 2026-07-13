from __future__ import annotations

import argparse
import ast
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from common import atomic_write_json, blocking, issue, project_dir, read_csv, read_json, sort_issues, utc_now


Dim = tuple[float, float, float, float]  # mass, length, time, temperature
ZERO: Dim = (0.0, 0.0, 0.0, 0.0)
MASS: Dim = (1.0, 0.0, 0.0, 0.0)
LENGTH: Dim = (0.0, 1.0, 0.0, 0.0)
TIME: Dim = (0.0, 0.0, 1.0, 0.0)
TEMP: Dim = (0.0, 0.0, 0.0, 1.0)
MAX_AST_NODES = 100
MAX_EXPRESSION_LENGTH = 1000
MAX_EXPONENT = 12.0


def dims_add(a: Dim, b: Dim) -> Dim:
    return tuple(x + y for x, y in zip(a, b))  # type: ignore[return-value]


def dims_sub(a: Dim, b: Dim) -> Dim:
    return tuple(x - y for x, y in zip(a, b))  # type: ignore[return-value]


def dims_mul(a: Dim, factor: float) -> Dim:
    return tuple(x * factor for x in a)  # type: ignore[return-value]


def dims_equal(a: Dim, b: Dim) -> bool:
    return all(abs(x - y) < 1e-9 for x, y in zip(a, b))


@dataclass(frozen=True)
class UnitDef:
    factor: float
    dims: Dim
    offset: float = 0.0
    absolute: bool = False


@dataclass(frozen=True)
class Quantity:
    value: float
    dims: Dim = ZERO
    absolute: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.value):
            raise ValueError("non-finite numeric value is not allowed")
        if any(not math.isfinite(item) for item in self.dims):
            raise ValueError("non-finite dimension is not allowed")

    def _compatible(self, other: "Quantity") -> None:
        if not dims_equal(self.dims, other.dims):
            raise ValueError(f"dimension mismatch {self.dims} vs {other.dims}")

    def __add__(self, other: "Quantity") -> "Quantity":
        other = as_quantity(other)
        self._compatible(other)
        if self.absolute and other.absolute:
            raise ValueError("two absolute temperatures cannot be added")
        return Quantity(self.value + other.value, self.dims, self.absolute or other.absolute)

    __radd__ = __add__

    def __sub__(self, other: "Quantity") -> "Quantity":
        other = as_quantity(other)
        self._compatible(other)
        if self.absolute and other.absolute:
            return Quantity(self.value - other.value, self.dims, False)
        if self.absolute and not other.absolute:
            return Quantity(self.value - other.value, self.dims, True)
        if not self.absolute and other.absolute:
            raise ValueError("a temperature delta cannot subtract an absolute temperature")
        return Quantity(self.value - other.value, self.dims)

    def __rsub__(self, other: "Quantity") -> "Quantity":
        return as_quantity(other).__sub__(self)

    def __mul__(self, other: "Quantity") -> "Quantity":
        other = as_quantity(other)
        if self.absolute or other.absolute:
            raise ValueError("absolute temperature cannot be multiplied or divided")
        return Quantity(self.value * other.value, dims_add(self.dims, other.dims))

    __rmul__ = __mul__

    def __truediv__(self, other: "Quantity") -> "Quantity":
        other = as_quantity(other)
        if self.absolute or other.absolute:
            raise ValueError("absolute temperature cannot be multiplied or divided")
        if other.value == 0:
            raise ZeroDivisionError("division by zero")
        return Quantity(self.value / other.value, dims_sub(self.dims, other.dims))

    def __rtruediv__(self, other: "Quantity") -> "Quantity":
        return as_quantity(other).__truediv__(self)

    def __pow__(self, exponent: "Quantity | float") -> "Quantity":
        exponent_q = as_quantity(exponent)
        if exponent_q.absolute or not dims_equal(exponent_q.dims, ZERO):
            raise ValueError("exponent must be dimensionless")
        if self.absolute:
            raise ValueError("absolute temperature cannot be exponentiated")
        if abs(exponent_q.value) > MAX_EXPONENT:
            raise ValueError(f"exponent magnitude exceeds {MAX_EXPONENT:g}")
        try:
            result = self.value ** exponent_q.value
        except (OverflowError, ZeroDivisionError, ValueError) as exc:
            raise ValueError(f"invalid exponentiation: {exc}") from exc
        if isinstance(result, complex) or not math.isfinite(float(result)):
            raise ValueError("exponentiation produced a non-real or non-finite result")
        return Quantity(float(result), dims_mul(self.dims, exponent_q.value))

    def __neg__(self) -> "Quantity":
        return Quantity(-self.value, self.dims, self.absolute)

    def __pos__(self) -> "Quantity":
        return self

    def __abs__(self) -> "Quantity":
        return Quantity(abs(self.value), self.dims, self.absolute)


def as_quantity(value: Quantity | float | int) -> Quantity:
    return value if isinstance(value, Quantity) else Quantity(float(value))


FORCE = dims_add(MASS, dims_sub(LENGTH, dims_mul(TIME, 2)))
PRESSURE = dims_sub(FORCE, dims_mul(LENGTH, 2))
ENERGY = dims_add(FORCE, LENGTH)
POWER = dims_sub(ENERGY, TIME)


def unit_table() -> dict[str, UnitDef]:
    table: dict[str, UnitDef] = {}

    def add(keys: tuple[str, ...], factor: float, dims: Dim, offset: float = 0.0, absolute: bool = False) -> None:
        for key in keys:
            table[key] = UnitDef(factor, dims, offset, absolute)

    add(("", "1", "dimensionless"), 1.0, ZERO)
    add(("%", "percent"), 0.01, ZERO)
    add(("rad",), 1.0, ZERO)
    add(("deg", "degree", "°"), math.pi / 180.0, ZERO)
    add(("m",), 1.0, LENGTH); add(("cm",), 1e-2, LENGTH); add(("mm",), 1e-3, LENGTH)
    add(("m2", "m^2"), 1.0, dims_mul(LENGTH, 2)); add(("cm2", "cm^2"), 1e-4, dims_mul(LENGTH, 2)); add(("mm2", "mm^2"), 1e-6, dims_mul(LENGTH, 2))
    add(("m3", "m^3"), 1.0, dims_mul(LENGTH, 3)); add(("cm3", "cm^3", "mL"), 1e-6, dims_mul(LENGTH, 3)); add(("mm3", "mm^3"), 1e-9, dims_mul(LENGTH, 3)); add(("L", "liter", "litre"), 1e-3, dims_mul(LENGTH, 3))
    add(("kg",), 1.0, MASS); add(("g",), 1e-3, MASS)
    add(("s",), 1.0, TIME); add(("min",), 60.0, TIME); add(("h", "hr"), 3600.0, TIME)
    add(("N",), 1.0, FORCE); add(("kN",), 1e3, FORCE)
    add(("Pa",), 1.0, PRESSURE); add(("kPa",), 1e3, PRESSURE); add(("MPa", "N/mm2", "N/mm^2"), 1e6, PRESSURE); add(("bar",), 1e5, PRESSURE)
    add(("J",), 1.0, ENERGY); add(("kJ",), 1e3, ENERGY); add(("W",), 1.0, POWER); add(("kW",), 1e3, POWER)
    add(("K", "delta_degC"), 1.0, TEMP); add(("degC",), 1.0, TEMP, 273.15, True)
    add(("m/s",), 1.0, dims_sub(LENGTH, TIME)); add(("mm/s",), 1e-3, dims_sub(LENGTH, TIME))
    add(("m3/s", "m^3/s"), 1.0, dims_sub(dims_mul(LENGTH, 3), TIME)); add(("m3/min", "m^3/min"), 1.0 / 60.0, dims_sub(dims_mul(LENGTH, 3), TIME)); add(("L/min",), 1e-3 / 60.0, dims_sub(dims_mul(LENGTH, 3), TIME)); add(("cm3/s", "cm^3/s"), 1e-6, dims_sub(dims_mul(LENGTH, 3), TIME))
    add(("kg/m3", "kg/m^3"), 1.0, dims_sub(MASS, dims_mul(LENGTH, 3))); add(("g/cm3", "g/cm^3"), 1e3, dims_sub(MASS, dims_mul(LENGTH, 3)))
    add(("J/(kg*K)",), 1.0, dims_sub(dims_sub(ENERGY, MASS), TEMP)); add(("kJ/(kg*K)",), 1e3, dims_sub(dims_sub(ENERGY, MASS), TEMP)); add(("W/(m*K)",), 1.0, dims_sub(dims_sub(POWER, LENGTH), TEMP)); add(("W/(m2*K)", "W/(m^2*K)"), 1.0, dims_sub(dims_sub(POWER, dims_mul(LENGTH, 2)), TEMP)); add(("Pa*s",), 1.0, dims_add(PRESSURE, TIME)); add(("rpm",), 1.0 / 60.0, dims_mul(TIME, -1))
    return table


UNITS = unit_table()


def normalize_unit(unit: str) -> str:
    value = (unit or "").strip().replace("²", "2").replace("³", "3").replace("·", "*")
    value = value.replace("℃", "degC").replace("°C", "degC")
    return re.sub(r"\s+", "", value)


def quantity_from(value: str | float | int, unit: str, quantity: str | None = None) -> Quantity:
    key = normalize_unit(unit)
    if key not in UNITS:
        raise ValueError(f"unsupported unit: {unit}")
    definition = UNITS[key]
    numeric = float(str(value).strip())
    if not math.isfinite(numeric):
        raise ValueError("non-finite numeric value is not allowed")
    absolute = definition.absolute or (key == "K" and quantity == "temperature")
    offset = definition.offset if definition.absolute else 0.0
    return Quantity(numeric * definition.factor + offset, definition.dims, absolute)


QUANTITY_DIMS: dict[str, Dim] = {
    "dimensionless": ZERO, "ratio": ZERO, "angle": ZERO, "length": LENGTH,
    "area": dims_mul(LENGTH, 2), "volume": dims_mul(LENGTH, 3), "mass": MASS,
    "time": TIME, "temperature": TEMP, "temperature_difference": TEMP,
    "force": FORCE, "pressure": PRESSURE, "energy": ENERGY, "power": POWER,
    "velocity": dims_sub(LENGTH, TIME), "volume_flow": dims_sub(dims_mul(LENGTH, 3), TIME),
    "density": dims_sub(MASS, dims_mul(LENGTH, 3)),
}


def same_dimension(values: list[Quantity]) -> None:
    if not values:
        raise ValueError("function requires at least one argument")
    for item in values[1:]:
        values[0]._compatible(item)


def fn_trig(name: str) -> Callable[[Quantity], Quantity]:
    function = getattr(math, name)
    def wrapped(value: Quantity) -> Quantity:
        value = as_quantity(value)
        if value.absolute or not dims_equal(value.dims, ZERO):
            raise ValueError(f"{name} requires a dimensionless angle")
        return Quantity(function(value.value))
    return wrapped


def fn_min(*values: Quantity) -> Quantity:
    items = [as_quantity(item) for item in values]; same_dimension(items)
    if any(item.absolute != items[0].absolute for item in items):
        raise ValueError("temperature kinds differ")
    return min(items, key=lambda item: item.value)


def fn_max(*values: Quantity) -> Quantity:
    items = [as_quantity(item) for item in values]; same_dimension(items)
    if any(item.absolute != items[0].absolute for item in items):
        raise ValueError("temperature kinds differ")
    return max(items, key=lambda item: item.value)


FUNCTIONS: dict[str, Callable[..., Quantity]] = {
    "sqrt": lambda value: as_quantity(value) ** 0.5,
    "abs": lambda value: abs(as_quantity(value)),
    "sin": fn_trig("sin"), "cos": fn_trig("cos"), "tan": fn_trig("tan"),
    "min": fn_min, "max": fn_max,
}


def parse_expression(expression: str) -> ast.Expression:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError("expression is too long")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise ValueError("expression is too complex")
    return tree


def evaluate_expression(expression: str, variables: dict[str, Quantity]) -> Quantity:
    tree = parse_expression(expression)
    def evaluate(node: ast.AST) -> Quantity:
        if isinstance(node, ast.Expression): return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool): return Quantity(float(node.value))
        if isinstance(node, ast.Name):
            if node.id == "pi": return Quantity(math.pi)
            if node.id not in variables: raise ValueError(f"unknown or unconfirmed parameter: {node.id}")
            return variables[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand); return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): return left + right
            if isinstance(node.op, ast.Sub): return left - right
            if isinstance(node.op, ast.Mult): return left * right
            if isinstance(node.op, ast.Div): return left / right
            if isinstance(node.op, ast.Pow): return left ** right
            raise ValueError(f"operator not allowed: {type(node.op).__name__}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in FUNCTIONS or node.keywords:
                raise ValueError(f"function not allowed: {node.func.id}")
            return FUNCTIONS[node.func.id](*(evaluate(arg) for arg in node.args))
        raise ValueError(f"syntax not allowed: {type(node).__name__}")
    return evaluate(tree)


def expression_names(expression: str) -> set[str]:
    names = {node.id for node in ast.walk(parse_expression(expression)) if isinstance(node, ast.Name)}
    return names - set(FUNCTIONS) - {"pi"}


def positive_revision(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9][0-9]*", value.strip()))


def run_engineering_audit(project: str | Path) -> dict[str, object]:
    root = project_dir(project)
    issues: list[dict[str, str]] = []
    assumptions = {row.get("assumption_id", ""): row for row in read_csv(root / "00_requirements" / "assumptions.csv") if row.get("assumption_id")}
    rows = read_csv(root / "03_engineering" / "parameters.csv")
    confirmed_variables: dict[str, Quantity] = {}
    parameter_status: dict[str, str] = {}
    confirmed_keys: dict[str, list[tuple[str, Quantity]]] = {}
    seen: set[str] = set()

    for index, row in enumerate(rows, start=2):
        param_id = row.get("param_id", "").strip(); location = f"03_engineering/parameters.csv:{index}"
        if not param_id:
            issues.append(issue("ENG001", "error", "Parameter ID is missing", location=location)); continue
        if param_id in seen:
            issues.append(issue("ENG002", "blocker", "Duplicate parameter ID", param_id, location)); continue
        seen.add(param_id)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", param_id):
            issues.append(issue("ENG003", "error", "Parameter ID is not a valid formula identifier", param_id, location))
        status = row.get("status", "").strip(); parameter_status[param_id] = status
        if status not in {"proposed", "confirmed", "superseded", "rejected", "stale"}:
            issues.append(issue("ENG004", "error", f"Unknown parameter status: {status}", param_id, location))
        if status in {"superseded", "rejected", "stale"}: continue
        if row.get("value", "").strip() == "":
            issues.append(issue("ENG005", "blocker" if status == "confirmed" else "warning", "Parameter value is missing", param_id, location)); continue
        quantity_name = row.get("quantity", "").strip()
        try:
            value = quantity_from(row["value"], row.get("unit", ""), quantity_name)
        except Exception as exc:
            issues.append(issue("UNIT001", "blocker", str(exc), param_id, location)); continue
        if quantity_name and quantity_name in QUANTITY_DIMS and not dims_equal(value.dims, QUANTITY_DIMS[quantity_name]):
            issues.append(issue("UNIT002", "blocker", f"Declared quantity '{quantity_name}' conflicts with unit '{row.get('unit', '')}'", param_id, location))
        elif quantity_name and quantity_name not in QUANTITY_DIMS:
            issues.append(issue("UNIT003", "warning", f"Unknown quantity category: {quantity_name}", param_id, location))
        if quantity_name == "temperature" and not value.absolute:
            issues.append(issue("UNIT004", "blocker", "Absolute temperature must use degC or K with quantity=temperature", param_id, location))
        if quantity_name == "temperature_difference" and value.absolute:
            issues.append(issue("UNIT005", "blocker", "Temperature difference must use K or delta_degC", param_id, location))
        if status == "confirmed":
            confirmed_variables[param_id] = value
            origin = row.get("origin_type", "").strip()
            if origin not in {"USR", "SRC", "DEC", "ASM", "CALC", "CAD", "SIM", "OBS"}:
                issues.append(issue("SRC001", "blocker", f"Invalid or missing origin type: {origin}", param_id, location))
            if not row.get("source_ref", "").strip():
                issues.append(issue("SRC002", "blocker", "Confirmed parameter has no source/decision/calculation reference", param_id, location))
            if not positive_revision(row.get("revision", "")):
                issues.append(issue("ENG007", "blocker", "Confirmed parameter has no positive integer revision", param_id, location))
            if not row.get("used_in", "").strip():
                issues.append(issue("ENG008", "error", "Confirmed parameter has no downstream location", param_id, location))
            if origin == "ASM":
                assumption = assumptions.get(row.get("assumption_id", "").strip())
                if not assumption or assumption.get("status", "").strip() != "approved":
                    issues.append(issue("ASM001", "blocker", "Assumption-backed parameter is not linked to an approved assumption", param_id, location))
            for label, key in (("name", row.get("name", "").strip().casefold()), ("symbol", row.get("symbol", "").strip().casefold())):
                if key: confirmed_keys.setdefault(f"{label}:{key}", []).append((param_id, value))

    for key, values in confirmed_keys.items():
        if len(values) < 2: continue
        first_id, first = values[0]
        for other_id, other in values[1:]:
            tolerance = max(1e-12, 1e-6 * max(abs(first.value), abs(other.value), 1.0))
            if not dims_equal(first.dims, other.dims) or first.absolute != other.absolute or abs(first.value - other.value) > tolerance:
                issues.append(issue("ENG006", "blocker", f"Conflicting confirmed values share {key}", f"{first_id},{other_id}", "03_engineering/parameters.csv"))

    try:
        calculations = read_json(root / "03_engineering" / "calculations.json").get("calculations", [])
        if not isinstance(calculations, list): raise ValueError("'calculations' must be a list")
    except Exception as exc:
        issues.append(issue("CALC001", "blocker", f"Cannot read calculations: {exc}", location="03_engineering/calculations.json")); calculations = []

    calc_ids: set[str] = set()
    allowed_statuses = {"planned", "proposed", "confirmed", "verified", "stale", "rejected", "superseded"}
    for index, calc in enumerate(calculations):
        location = f"03_engineering/calculations.json:calculations[{index}]"
        if not isinstance(calc, dict):
            issues.append(issue("CALC002", "error", "Calculation record must be an object", location=location)); continue
        calc_id = str(calc.get("id", "")).strip()
        if not calc_id:
            issues.append(issue("CALC002", "error", "Calculation ID is missing", location=location)); continue
        if calc_id in calc_ids:
            issues.append(issue("CALC003", "blocker", "Duplicate calculation ID", calc_id, location)); continue
        calc_ids.add(calc_id)
        status = str(calc.get("status", "planned")).strip()
        if status not in allowed_statuses:
            issues.append(issue("CALC008", "error", f"Unknown calculation status: {status}", calc_id, location)); continue
        if status not in {"confirmed", "verified"}: continue
        expression = str(calc.get("expression", "")).strip()
        if not expression:
            issues.append(issue("CALC004", "blocker", "Confirmed calculation has no expression", calc_id, location)); continue
        if not str(calc.get("formula_source", "")).strip():
            issues.append(issue("CALC005", "blocker", "Confirmed calculation has no formula source and locator", calc_id, location))
        if not str(calc.get("used_in", "")).strip():
            issues.append(issue("CALC009", "blocker", "Confirmed calculation has no downstream use location", calc_id, location))
        try:
            names = expression_names(expression)
            unconfirmed = sorted(name for name in names if parameter_status.get(name) != "confirmed")
            if unconfirmed: raise ValueError("missing or unconfirmed parameters: " + ", ".join(unconfirmed))
            evaluated = evaluate_expression(expression, confirmed_variables)
            declared = quantity_from(calc.get("result_value", ""), str(calc.get("result_unit", "")), str(calc.get("result_quantity", "") or ""))
            if not dims_equal(evaluated.dims, declared.dims) or evaluated.absolute != declared.absolute:
                raise ValueError(f"result dimension {evaluated.dims} does not match declared unit {calc.get('result_unit', '')}")
            tolerance = float(calc.get("tolerance", 0.005))
            if not math.isfinite(tolerance) or tolerance < 0 or tolerance > 0.1:
                raise ValueError("tolerance must be finite and between 0 and 0.1")
            relative = abs(evaluated.value - declared.value) / max(abs(evaluated.value), abs(declared.value), 1e-12)
            if not math.isfinite(relative): raise ValueError("comparison produced a non-finite error")
            if relative > tolerance:
                issues.append(issue("CALC006", "blocker", f"Declared result differs from recomputation by {relative:.3%}", calc_id, location, f"Recomputed SI value: {evaluated.value:g}"))
        except Exception as exc:
            issues.append(issue("CALC007", "blocker", str(exc), calc_id, location))

    issues = sort_issues(issues)
    summary = {level: sum(1 for item in issues if item["severity"] == level) for level in ("blocker", "error", "warning", "info")}
    return {"schema_version": "2.0", "generated_at": utc_now(), "passed": not blocking(issues), "summary": summary, "issues": issues}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit units, origins, assumptions, and calculations")
    parser.add_argument("--project", required=True); parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()
    try: result = run_engineering_audit(args.project)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
    if args.json_path: atomic_write_json(Path(args.json_path).expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
