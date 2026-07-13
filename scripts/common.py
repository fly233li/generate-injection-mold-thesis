from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GATES = ("G1", "G2", "G3", "G4")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def project_dir(path: str | os.PathLike[str]) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_file() and candidate.name == "project.json":
        candidate = candidate.parent
    if not (candidate / "project.json").is_file():
        raise FileNotFoundError(f"Not a thesis project: {candidate}")
    return candidate


def _reject_nonfinite(token: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {token}")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle, parse_constant=_reject_nonfinite)


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try: os.unlink(temp_name)
        except FileNotFoundError: pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try: os.unlink(temp_name)
        except FileNotFoundError: pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    output: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, str] = {}
            for key, item in raw.items():
                if key is None:
                    row["__extra_columns__"] = "" if item is None else json.dumps(item, ensure_ascii=False)
                else:
                    row[str(key)] = "" if item is None else str(item)
            output.append(row)
    return output


def issue(rule: str, severity: str, message: str, entity: str = "", location: str = "", remediation: str = "") -> dict[str, str]:
    return {"rule": rule, "severity": severity, "entity": entity, "location": location, "message": message, "remediation": remediation}


def sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rank = {"blocker": 0, "error": 1, "warning": 2, "info": 3}
    return sorted(issues, key=lambda item: (rank.get(item.get("severity", "info"), 9), item.get("rule", ""), item.get("entity", ""), item.get("location", "")))


def blocking(issues: list[dict[str, Any]]) -> bool:
    return any(item.get("severity") in {"blocker", "error"} for item in issues)
