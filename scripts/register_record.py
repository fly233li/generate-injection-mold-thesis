from __future__ import annotations

import argparse
import csv
import io
import json
import keyword
import math
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping

from common import atomic_write_text, project_dir


@dataclass(frozen=True)
class KindSchema:
    relative: str
    id_field: str
    id_pattern: str
    fields: tuple[str, ...]
    required: frozenset[str]
    enums: Mapping[str, frozenset[str]]


_COMMON_STATUSES = frozenset(
    {"draft", "proposed", "approved", "confirmed", "verified", "placed", "applied", "used", "claim-bound", "planned", "prepared_unexecuted", "executed", "stale", "rejected", "superseded"}
)


KINDS: dict[str, KindSchema] = {
    "requirement": KindSchema(
        "00_requirements/requirements.csv",
        "req_id",
        r"REQ-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("req_id", "category", "requirement", "origin", "priority", "acceptance", "chapter_id", "calc_ids", "drawing_ids", "case_ids", "verification", "status", "revision", "supersedes"),
        frozenset({"req_id", "category", "requirement", "origin", "priority", "acceptance", "chapter_id", "verification", "status", "revision"}),
        {
            "priority": frozenset({"must", "should", "could", "wont", "high", "medium", "low", "P0", "P1", "P2", "P3"}),
            "status": frozenset({"draft", "proposed", "approved", "confirmed", "verified", "stale", "rejected", "superseded"}),
        },
    ),
    "assumption": KindSchema(
        "00_requirements/assumptions.csv",
        "assumption_id",
        r"ASM-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("assumption_id", "statement", "value", "unit", "criticality", "basis_source_id", "uncertainty_or_range", "status", "approval_gate", "affected_items", "validation_method", "revision", "supersedes"),
        frozenset({"assumption_id", "statement", "criticality", "status", "approval_gate", "revision"}),
        {
            "criticality": frozenset({"K1", "K2", "K3"}),
            "status": frozenset({"proposed", "approved", "rejected", "superseded", "stale"}),
            "approval_gate": frozenset({"G1", "G2", "G3", "G4"}),
        },
    ),
    "parameter": KindSchema(
        "03_engineering/parameters.csv",
        "param_id",
        r"[A-Za-z_][A-Za-z0-9_]*",
        ("param_id", "name", "symbol", "value", "unit", "quantity", "origin_type", "source_ref", "status", "assumption_id", "nx_expression", "used_in", "revision"),
        frozenset({"param_id", "name", "value", "unit", "quantity", "origin_type", "source_ref", "status", "revision"}),
        {
            "origin_type": frozenset({"USR", "SRC", "DEC", "ASM", "CALC", "CAD", "SIM", "OBS"}),
            "status": frozenset({"proposed", "confirmed", "verified", "stale", "rejected", "superseded"}),
        },
    ),
    "decision": KindSchema(
        "03_engineering/decisions.csv",
        "decision_id",
        r"DEC-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("decision_id", "category", "question", "alternatives", "selected_option", "rationale", "evidence_ids", "impact", "status", "revision"),
        frozenset({"decision_id", "category", "question", "alternatives", "status", "revision"}),
        {"status": frozenset({"proposed", "approved", "rejected", "superseded", "stale"})},
    ),
    "source": KindSchema(
        "02_sources/references.csv",
        "source_id",
        r"SRC-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("source_id", "source_type", "title", "authors_or_org", "year", "journal_or_publisher", "volume", "issue", "pages_or_article_no", "doi", "cnki_url_or_record_id", "official_url", "access_date", "access_level", "exact_locator", "claim_ids", "status", "rejection_reason", "citation_key", "used_in", "revision"),
        frozenset({"source_id", "source_type", "title", "authors_or_org", "year", "access_level", "status", "revision"}),
        {
            "source_type": frozenset({"journal", "conference", "thesis", "book", "standard", "patent", "official_document", "manufacturer_data", "software_documentation", "primary_web", "dataset"}),
            "access_level": frozenset({"unknown", "metadata", "abstract", "fulltext", "official_fulltext"}),
            "status": frozenset({"candidate", "verified", "claim-bound", "used", "stale", "rejected", "superseded"}),
        },
    ),
    "claim": KindSchema(
        "02_sources/claims.csv",
        "claim_id",
        r"CLM-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("claim_id", "claim_text", "claim_type", "source_ids", "exact_locator", "section_id", "status", "revision"),
        frozenset({"claim_id", "claim_text", "claim_type", "section_id", "status", "revision"}),
        {
            "claim_type": frozenset({"external", "fact", "formula", "material_property", "standard_requirement", "design_decision", "cad_measurement", "simulation_result", "literature_synthesis"}),
            "status": frozenset({"proposed", "verified", "used", "stale", "rejected", "superseded"}),
        },
    ),
    "placement": KindSchema(
        "01_outline/evidence-placement.csv",
        "object_id",
        r"(?:FIG|TAB|EQ|ART|CALC|DWG|BOM|SRC)-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("object_id", "object_type", "title_or_caption", "section_id", "first_mention_claim_id", "insertion_position", "purpose", "source_or_artifact_id", "file", "word_bookmark_or_field", "status", "revision"),
        frozenset({"object_id", "object_type", "title_or_caption", "section_id", "first_mention_claim_id", "insertion_position", "purpose", "source_or_artifact_id", "word_bookmark_or_field", "status", "revision"}),
        {
            "object_type": frozenset({"figure", "table", "equation", "drawing", "bom", "calculation", "citation", "cad_artifact", "cae_artifact", "appendix"}),
            "status": frozenset({"planned", "placed", "verified", "stale", "rejected", "superseded"}),
        },
    ),
    "drawing": KindSchema(
        "04_cad/drawings.csv",
        "drawing_id",
        r"DWG-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("drawing_id", "title", "drawing_type", "file", "model_revision", "requirement_ids", "status", "checked_by", "revision", "notes"),
        frozenset({"drawing_id", "title", "drawing_type", "file", "model_revision", "requirement_ids", "status", "revision"}),
        {
            "drawing_type": frozenset({"part", "assembly", "mold_assembly", "plastic_part", "core", "cavity", "slider", "ejector", "cooling", "runner", "bom", "process"}),
            "status": frozenset({"planned", "prepared", "prepared_unexecuted", "executed", "verified", "stale", "rejected", "superseded"}),
        },
    ),
    "bom": KindSchema(
        "04_cad/bom.csv",
        "item_id",
        r"(?:BOM|ITEM)-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("item_id", "item_no", "part_name", "quantity", "material", "standard_or_drawing_id", "model_revision", "status", "revision", "notes"),
        frozenset({"item_id", "item_no", "part_name", "quantity", "material", "standard_or_drawing_id", "model_revision", "status", "revision"}),
        {"status": frozenset({"proposed", "prepared", "confirmed", "verified", "stale", "rejected", "superseded"})},
    ),
    "change": KindSchema(
        "00_requirements/changes.csv",
        "change_id",
        r"(?:CHG|CHANGE)-[A-Z0-9](?:[A-Z0-9_-]{0,62}[A-Z0-9])?",
        ("change_id", "changed_at", "actor", "reason", "affected_ids", "reopened_gate", "status", "revision"),
        frozenset({"change_id", "changed_at", "actor", "reason", "affected_ids", "reopened_gate", "status", "revision"}),
        {
            "reopened_gate": frozenset({"G1", "G2", "G3", "G4"}),
            "status": frozenset({"proposed", "approved", "applied", "verified", "rejected", "superseded"}),
        },
    ),
}


_PROCESS_LOCK = threading.Lock()
_PARAMETER_RESERVED_NAMES = frozenset({"pi", "sqrt", "abs", "sin", "cos", "tan", "min", "max"})
_EXTERNAL_CLAIM_TYPES = frozenset(
    {"external", "fact", "formula", "material_property", "standard_requirement", "literature_synthesis"}
)


def load_record(record_path: str | None, data: str | None) -> dict[str, object]:
    if bool(record_path) == bool(data):
        raise ValueError("Provide exactly one of --record or --data")
    if record_path:
        payload = json.loads(Path(record_path).expanduser().read_text(encoding="utf-8-sig"))
    else:
        payload = json.loads(data or "")
    if not isinstance(payload, dict):
        raise ValueError("Record must be a JSON object")
    return payload


def serialize(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _has_value(value: object, serialized: str) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, tuple, dict, set)) and len(value) == 0:
        return False
    return bool(serialized.strip())


def _parse_revision(value: object, label: str = "revision") -> int:
    text = serialize(value).strip()
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError(f"{label} must be a positive integer")
    return int(text)


def _read_ledger(path: Path, schema: KindSchema, *, history: bool = False) -> list[dict[str, str]]:
    if not path.is_file():
        if history:
            return []
        raise FileNotFoundError(f"Ledger does not exist: {schema.relative}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        actual = tuple(reader.fieldnames or ())
        if actual != schema.fields:
            raise ValueError(
                f"Invalid ledger header for {path.name}; expected {','.join(schema.fields)}"
            )
        rows: list[dict[str, str]] = []
        for line_no, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"Malformed CSV row in {path.name}:{line_no}")
            rows.append({field: row.get(field, "") or "" for field in schema.fields})
    return rows


def _serialize_rows(fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _write_rows(path: Path, schema: KindSchema, rows: list[dict[str, str]], *, sort_current: bool) -> None:
    output = list(rows)
    if sort_current:
        output.sort(key=lambda row: row[schema.id_field])
    atomic_write_text(path, _serialize_rows(schema.fields, output), encoding="utf-8-sig")


def _validate_record(schema: KindSchema, record: dict[str, object]) -> tuple[dict[str, str], int]:
    unknown = sorted(set(record) - set(schema.fields))
    if unknown:
        raise ValueError("Unknown record fields: " + ", ".join(unknown))

    output = {field: serialize(record.get(field, "")) for field in schema.fields}
    missing = sorted(
        field
        for field in schema.required
        if not _has_value(record.get(field), output[field])
    )
    if missing:
        raise ValueError("Missing required record fields: " + ", ".join(missing))

    record_id = output[schema.id_field].strip()
    if not re.fullmatch(schema.id_pattern, record_id):
        raise ValueError(f"Invalid {schema.id_field} format: {record_id}")
    output[schema.id_field] = record_id

    revision = _parse_revision(output["revision"])
    output["revision"] = str(revision)

    for field, allowed in schema.enums.items():
        value = output[field].strip()
        if value and value not in allowed:
            raise ValueError(
                f"Invalid {field}: {value}; allowed values: {', '.join(sorted(allowed))}"
            )
        output[field] = value

    if schema.id_field == "param_id":
        if keyword.iskeyword(record_id) or record_id in _PARAMETER_RESERVED_NAMES:
            raise ValueError(f"Reserved parameter identifier: {record_id}")
        try:
            number = float(output["value"])
        except ValueError as exc:
            raise ValueError("Parameter value must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError("Parameter value must be finite")
        if output["status"] in {"confirmed", "verified"} and not output["used_in"].strip():
            raise ValueError("Confirmed or verified parameter requires used_in")

    if schema.id_field == "decision_id" and output["status"] == "approved":
        missing_approved = [field for field in ("selected_option", "rationale", "evidence_ids") if not output[field].strip()]
        if missing_approved:
            raise ValueError("Approved decision requires: " + ", ".join(missing_approved))

    if schema.id_field == "claim_id" and output["claim_type"] in _EXTERNAL_CLAIM_TYPES:
        missing_external = [
            field
            for field in ("source_ids", "exact_locator")
            if not _has_value(record.get(field), output[field])
        ]
        if missing_external:
            raise ValueError("External claim requires: " + ", ".join(missing_external))

    if schema.id_field == "source_id":
        year = output["year"].strip()
        if not re.fullmatch(r"[12][0-9]{3}", year):
            raise ValueError("Source year must be a four-digit year")
        if output["status"] in {"claim-bound", "used"}:
            required = [field for field in ("exact_locator", "claim_ids") if not output[field].strip()]
            if output["status"] == "used" and not output["used_in"].strip():
                required.append("used_in")
            if required:
                raise ValueError(f"{output['status']} source requires: " + ", ".join(required))
        if output["status"] == "rejected" and not output["rejection_reason"].strip():
            raise ValueError("Rejected source requires rejection_reason")

    if schema.id_field == "item_id":
        quantity = output["quantity"].strip()
        if not re.fullmatch(r"[1-9][0-9]*", quantity):
            raise ValueError("BOM quantity must be a positive integer")
        output["quantity"] = str(int(quantity))

    return output, revision


def _validate_existing(rows: list[dict[str, str]], schema: KindSchema, *, history: bool) -> None:
    seen: set[str] = set()
    seen_versions: set[tuple[str, int]] = set()
    for row in rows:
        record_id = row[schema.id_field].strip()
        if not re.fullmatch(schema.id_pattern, record_id):
            raise ValueError(f"Invalid existing {schema.id_field}: {record_id}")
        revision = _parse_revision(row["revision"], f"revision for {record_id}")
        if history:
            key = (record_id, revision)
            if key in seen_versions:
                raise ValueError(f"Duplicate history revision: {record_id} revision {revision}")
            seen_versions.add(key)
        elif record_id in seen:
            raise ValueError(f"Duplicate active record: {record_id}")
        seen.add(record_id)


def _history_path(path: Path) -> Path:
    return path.with_name(f"{path.stem}.history.csv")


def _try_os_lock(handle: io.BufferedRandom) -> bool:
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        return False


def _unlock_os(handle: io.BufferedRandom) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _exclusive_project_lock(root: Path, timeout: float) -> Iterator[None]:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("lock timeout must be a positive finite number")
    acquired_process = _PROCESS_LOCK.acquire(timeout=timeout)
    if not acquired_process:
        raise TimeoutError("Timed out waiting for the project record lock")
    handle: io.BufferedRandom | None = None
    locked = False
    try:
        lock_path = root / ".register_record.lock"
        handle = lock_path.open("a+b")
        if lock_path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + timeout
        while not (locked := _try_os_lock(handle)):
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for the project record lock")
            time.sleep(0.025)
        yield
    finally:
        if locked and handle is not None:
            _unlock_os(handle)
        if handle is not None:
            handle.close()
        _PROCESS_LOCK.release()


def register(
    project: str | Path,
    kind: str,
    record: dict[str, object],
    replace_if_revision: str | None = None,
    *,
    lock_timeout: float = 5.0,
) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"Unknown record kind: {kind}")
    root = project_dir(project)
    schema = KINDS[kind]
    path = root / schema.relative
    output, new_revision = _validate_record(schema, record)
    record_id = output[schema.id_field]

    expected_revision: int | None = None
    if replace_if_revision is not None:
        expected_revision = _parse_revision(replace_if_revision, "--replace-if-revision")

    with _exclusive_project_lock(root, lock_timeout):
        rows = _read_ledger(path, schema)
        _validate_existing(rows, schema, history=False)
        existing_index = next(
            (index for index, row in enumerate(rows) if row[schema.id_field].strip() == record_id),
            None,
        )

        if existing_index is None:
            if expected_revision is not None:
                raise ValueError("--replace-if-revision was supplied but the record does not exist")
            rows.append(output)
            _write_rows(path, schema, rows, sort_current=True)
            action = "created"
            history_relative = ""
        else:
            if expected_revision is None:
                raise FileExistsError(f"Record already exists: {record_id}")
            current = rows[existing_index]
            current_revision = _parse_revision(current["revision"], f"current revision for {record_id}")
            if current_revision != expected_revision:
                raise RuntimeError(
                    f"Revision mismatch for {record_id}: expected {expected_revision}, found {current_revision}"
                )
            if new_revision <= current_revision:
                raise ValueError(
                    f"New revision for {record_id} must be greater than {current_revision}; found {new_revision}"
                )

            history_path = _history_path(path)
            history = _read_ledger(history_path, schema, history=True)
            _validate_existing(history, schema, history=True)
            history_match = next(
                (
                    old
                    for old in history
                    if old[schema.id_field].strip() == record_id
                    and _parse_revision(old["revision"]) == current_revision
                ),
                None,
            )
            if history_match is None:
                history.append(dict(current))
                _write_rows(history_path, schema, history, sort_current=False)
            elif history_match != current:
                raise RuntimeError(
                    f"History conflict for {record_id} revision {current_revision}; refusing to lose prior data"
                )

            rows[existing_index] = output
            _write_rows(path, schema, rows, sort_current=True)
            action = "replaced"
            history_relative = history_path.relative_to(root).as_posix()

    result = {
        "action": action,
        "kind": kind,
        "id": record_id,
        "revision": str(new_revision),
        "ledger": schema.relative,
    }
    if history_relative:
        result["history_ledger"] = history_relative
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or compare-and-swap one strictly validated project ledger record"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--kind", required=True, choices=sorted(KINDS))
    parser.add_argument("--record", help="UTF-8 JSON file containing one record")
    parser.add_argument("--data", help="Inline JSON object")
    parser.add_argument(
        "--replace-if-revision",
        help="Replace only when the current positive-integer revision exactly matches",
    )
    parser.add_argument("--lock-timeout", type=float, default=5.0)
    args = parser.parse_args()
    try:
        payload = load_record(args.record, args.data)
        result = register(
            args.project,
            args.kind,
            payload,
            args.replace_if_revision,
            lock_timeout=args.lock_timeout,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




