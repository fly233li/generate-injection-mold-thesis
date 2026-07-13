from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from common import issue, read_json


def value(row: dict[str, Any], key: str) -> str:
    item = row.get(key, "")
    return "" if item is None else str(item).strip()


def safe_project_file(root: Path, relative: str) -> Path | None:
    if not relative.strip():
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_symlink():
        return None
    return candidate


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def list_cell(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except json.JSONDecodeError:
            pass
    return [item.strip() for item in re.split(r"[;,，；|]", raw) if item.strip()]


def valid_revision(raw: Any) -> bool:
    try:
        return int(str(raw).strip()) >= 1
    except (TypeError, ValueError):
        return False


def positive_finite(raw: Any) -> bool:
    try:
        number = float(raw)
        return math.isfinite(number) and number > 0
    except (TypeError, ValueError):
        return False


def unique_rows(rows: list[dict[str, str]], id_field: str, location: str, rule: str, issues: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=2):
        record_id = value(row, id_field)
        if not record_id:
            issues.append(issue(rule, "blocker", f"Missing {id_field}", location=f"{location}:{index}"))
        elif record_id in output:
            issues.append(issue(rule, "blocker", f"Duplicate active ID: {record_id}", record_id, f"{location}:{index}"))
        else:
            output[record_id] = row
    return output


def read_object(path: Path, label: str, issues: list[dict[str, str]]) -> dict[str, Any]:
    try:
        data = read_json(path)
        if not isinstance(data, dict):
            raise ValueError("root must be a JSON object")
        return data
    except Exception as exc:
        issues.append(issue("JSON001", "blocker", f"Cannot read {label}: {exc}", location=str(path)))
        return {}


def validate_hash_entry(root: Path, entry: Any, label: str, location: str, issues: list[dict[str, str]]) -> Path | None:
    if not isinstance(entry, dict):
        issues.append(issue("ART001", "blocker", f"{label} file entry must contain path and sha256", location=location))
        return None
    relative = value(entry, "path")
    candidate = safe_project_file(root, relative)
    if candidate is None or not candidate.is_file() or candidate.stat().st_size == 0:
        issues.append(issue("ART002", "blocker", f"Missing, empty, unsafe, or linked {label} file: {relative}", location=location))
        return None
    expected = value(entry, "sha256").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        issues.append(issue("ART003", "blocker", f"{label} file lacks a valid SHA-256: {relative}", location=location))
    elif sha256_file(candidate) != expected:
        issues.append(issue("ART004", "blocker", f"{label} file hash mismatch: {relative}", location=location))
    return candidate
