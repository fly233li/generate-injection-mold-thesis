from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from audit_project import run_audit
from common import GATES, atomic_write_json, atomic_write_text, project_dir, read_json, utc_now


# Files whose content defines each review package.  A gate snapshot contains the
# files for that gate and every preceding gate.  Referenced artifacts are added
# below, so changing a native model, drawing, result, or final document also
# invalidates the appropriate approval.
GATE_FILES: dict[str, tuple[str, ...]] = {
    "G1": (
        "00_requirements/brief.md",
        "00_requirements/design-basis.json",
        "00_requirements/requirements.csv",
        "00_requirements/assumptions.csv",
        "00_requirements/changes.csv",
        "01_outline/outline.md",
    ),
    "G2": (
        "03_engineering/decisions.csv",
        "03_engineering/parameters.csv",
        "03_engineering/schemes.json",
    ),
    "G3": (
        "01_outline/evidence-placement.csv",
        "03_engineering/calculations.json",
        "04_cad/model-manifest.json",
        "04_cad/nx/model-plan.json",
        "04_cad/drawings.csv",
        "04_cad/bom.csv",
        "05_cae/moldflow-study.json",
    ),
    "G4": (
        "02_sources/claims.csv",
        "02_sources/references.csv",
        "02_sources/search-log.csv",
        "02_sources/evidence-manifest.csv",
        "06_manuscript/chapter-plan.json",
        "06_manuscript/manuscript.md",
        "07_audit/pdf-visual-review.json",
        "deliverables/release-manifest.json",
        "deliverables/release-manifest.md",
    ),
}

SNAPSHOT_SCHEMA_VERSION = 3
_STATE_FIELDS = {"gates", "updated_at", "status", "maturity_level", "release_level"}
_DESIGN_SOFTWARE_FIELDS = {"cad_requested", "cae_requested"}
_LOCK_NAME = ".project-state.lock"
_HISTORY = "approvals/history.jsonl"


def gate_index(gate: str) -> int:
    try:
        return GATES.index(gate)
    except ValueError as exc:
        raise ValueError(f"Unknown gate: {gate}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_relative(root: Path, raw: str) -> str | None:
    raw = raw.strip()
    if not raw or re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.IGNORECASE):
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        relative = candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return relative.as_posix()


def _walk_file_references(value: Any, key: str = "") -> Iterator[str]:
    """Yield project-file strings from the deliberately file-shaped fields."""
    if isinstance(value, dict):
        direct = value.get("path")
        if isinstance(direct, str) and direct.strip():
            yield direct
        direct = value.get("file")
        if isinstance(direct, str) and direct.strip():
            yield direct
        for child_key, child in value.items():
            lower = str(child_key).lower()
            if isinstance(child, str) and child.strip() and (
                lower.endswith("_file")
                or lower.endswith("_path")
                or lower.endswith("_log")
                or lower in {"solver_log", "execution_log"}
            ):
                yield child
            elif isinstance(child, list) and lower in {
                "files",
                "result_files",
                "output_files",
                "artifacts",
                "deliverables",
            }:
                for item in child:
                    if isinstance(item, str) and item.strip():
                        yield item
                    else:
                        yield from _walk_file_references(item, lower)
            elif isinstance(child, (dict, list)):
                yield from _walk_file_references(child, lower)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_file_references(item, key)


def _json_references(root: Path, relative: str) -> set[str]:
    path = root / relative
    if not path.is_file():
        return set()
    try:
        data = read_json(path)
    except Exception:
        return set()
    output: set[str] = set()
    for raw in _walk_file_references(data):
        normalized = _project_relative(root, raw)
        if normalized:
            output.add(normalized)
    return output


def _csv_references(root: Path, relative: str, fields: tuple[str, ...]) -> set[str]:
    path = root / relative
    if not path.is_file():
        return set()
    output: set[str] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                for field in fields:
                    normalized = _project_relative(root, str(row.get(field, "")))
                    if normalized:
                        output.add(normalized)
    except (OSError, csv.Error):
        return set()
    return output


def _recursive_files(root: Path, relative: str) -> set[str]:
    directory = root / relative
    if not directory.is_dir():
        return set()
    output: set[str] = set()
    for path in directory.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.name.endswith((".bak", ".tmp")):
            continue
        output.add(path.relative_to(root).as_posix())
    return output


def _referenced_files(root: Path, gate: str) -> set[str]:
    index = gate_index(gate)
    output: set[str] = set()
    if index >= gate_index("G3"):
        output.update(_json_references(root, "04_cad/model-manifest.json"))
        output.update(_json_references(root, "05_cae/moldflow-study.json"))
        output.update(_csv_references(root, "04_cad/drawings.csv", ("file",)))
        output.update(_csv_references(root, "01_outline/evidence-placement.csv", ("file",)))
    if index >= gate_index("G4"):
        output.update(_json_references(root, "deliverables/release-manifest.json"))
        output.update(_csv_references(root, "02_sources/evidence-manifest.csv", ("file",)))
        output.update(_recursive_files(root, "06_manuscript/figures"))
        output.update(_recursive_files(root, "deliverables/files"))
    return output


def _snapshot_entry(root: Path, relative: str) -> dict[str, Any]:
    path = root / Path(relative)
    if not path.is_file() or path.is_symlink():
        return {"path": relative.replace("\\", "/"), "length": None, "sha256": None}
    return {
        "path": relative.replace("\\", "/"),
        "length": path.stat().st_size,
        "sha256": _sha256(path),
    }


def snapshot(
    root: Path,
    gate: str,
    manifest_override: dict[str, Any] | None = None,
    *,
    include_software: bool = False,
    schema_version: int | None = None,
) -> dict[str, Any]:
    """Return a deterministic, inspectable snapshot for a gate review package."""
    gate_index(gate)
    manifest = manifest_override if manifest_override is not None else read_json(root / "project.json")
    target_schema = 1 if include_software else (
        SNAPSHOT_SCHEMA_VERSION if schema_version is None else schema_version
    )
    if isinstance(target_schema, bool) or target_schema not in {1, 2, SNAPSHOT_SCHEMA_VERSION}:
        raise ValueError(f"Unsupported snapshot schema version: {target_schema}")
    excluded = set(_STATE_FIELDS)
    controlled_manifest = {key: value for key, value in manifest.items() if key not in excluded}
    if target_schema == 2:
        controlled_manifest.pop("software", None)
    elif target_schema >= 3:
        software = manifest.get("software") if isinstance(manifest.get("software"), dict) else {}
        controlled_manifest["software"] = {
            key: software[key]
            for key in sorted(_DESIGN_SOFTWARE_FIELDS)
            if key in software
        }
    encoded = json.dumps(
        controlled_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    entries: list[dict[str, Any]] = [
        {
            "path": "@project.json:controlled",
            "length": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    ]
    relatives: set[str] = set()
    for current in GATES[: gate_index(gate) + 1]:
        relatives.update(GATE_FILES[current])
    relatives.update(_referenced_files(root, gate))
    for relative in sorted(relatives, key=lambda item: item.casefold()):
        entries.append(_snapshot_entry(root, relative))
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": target_schema,
        "algorithm": "sha256",
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "entries": entries,
    }


def snapshot_hash(
    root: Path,
    gate: str,
    manifest_override: dict[str, Any] | None = None,
    *,
    include_software: bool = False,
    schema_version: int | None = None,
) -> str:
    return str(
        snapshot(
            root,
            gate,
            manifest_override,
            include_software=include_software,
            schema_version=schema_version,
        )["sha256"]
    )


def _evidence_entry(root: Path, evidence: str | os.PathLike[str]) -> dict[str, Any]:
    approvals = (root / "approvals").resolve()
    raw = Path(evidence).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve(strict=True)
        relative_to_approvals = resolved.relative_to(approvals)
        relative_to_root = resolved.relative_to(root.resolve())
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValueError("Approval evidence must be an existing file inside the project's approvals directory") from exc
    if resolved.is_symlink() or not resolved.is_file() or resolved.stat().st_size == 0:
        raise ValueError("Approval evidence must be a non-empty regular file, not a link")
    if relative_to_approvals.as_posix().casefold() in {"readme.md", "history.jsonl"}:
        raise ValueError("The approvals README or history log cannot be used as approval evidence")
    return {
        "path": relative_to_root.as_posix(),
        "length": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _evidence_is_current(root: Path, entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    relative = entry.get("path")
    if not isinstance(relative, str):
        return False
    try:
        current = _evidence_entry(root, relative)
    except (OSError, ValueError):
        return False
    return current == {key: entry.get(key) for key in ("path", "length", "sha256")}


@contextmanager
def _project_lock(root: Path, timeout: float = 10.0) -> Iterator[None]:
    """Serialize gate state transitions with an atomic project-local lock."""
    lock_path = root / _LOCK_NAME
    token = f"{uuid.uuid4().hex} {os.getpid()} {time.time():.6f}\n"
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > 900
            except FileNotFoundError:
                continue
            if stale:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Project gate state is locked: {lock_path}")
            time.sleep(0.05)
            continue
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            break
    try:
        yield
    finally:
        try:
            if lock_path.read_text(encoding="utf-8") == token:
                lock_path.unlink()
        except FileNotFoundError:
            pass


def effective_status(root: Path, manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    gates = manifest.get("gates") if isinstance(manifest.get("gates"), dict) else {}
    prior_effectively_approved = True
    for gate in GATES:
        source = gates.get(gate, {}) if isinstance(gates, dict) else {}
        record = dict(source) if isinstance(source, dict) else {}
        declared = record.get("status", "pending")
        reasons: list[str] = []
        if declared == "approved":
            stored_snapshot = record.get("snapshot")
            expected = stored_snapshot.get("sha256") if isinstance(stored_snapshot, dict) else record.get("snapshot_hash")
            stored_schema = stored_snapshot.get("schema_version", 1) if isinstance(stored_snapshot, dict) else 1
            valid_schema = (
                isinstance(stored_schema, int)
                and not isinstance(stored_schema, bool)
                and stored_schema in {1, 2, SNAPSHOT_SCHEMA_VERSION}
            )
            if not valid_schema:
                reasons.append("review snapshot has an unsupported schema")
            elif not isinstance(expected, str) or expected != snapshot_hash(
                root, gate, schema_version=stored_schema
            ):
                reasons.append("review package changed after approval")
            if not _evidence_is_current(root, record.get("evidence")):
                reasons.append("approval evidence is missing or changed")
            if not prior_effectively_approved:
                reasons.append("a prior gate is not effectively approved")
            effective = "approved" if not reasons else "stale"
        else:
            effective = declared if declared in {"pending", "reopened"} else "pending"
        record["effective_status"] = effective
        if reasons:
            record["stale_reasons"] = reasons
        output[gate] = record
        prior_effectively_approved = prior_effectively_approved and effective == "approved"
    return output


def _execution_maturity(root: Path) -> str:
    try:
        cad = read_json(root / "04_cad" / "model-manifest.json")
    except Exception:
        cad = {}
    try:
        cae = read_json(root / "05_cae" / "moldflow-study.json")
    except Exception:
        cae = {}

    cad_execution = cad.get("execution") if isinstance(cad.get("execution"), dict) else {}
    cad_files = cad.get("files") if isinstance(cad.get("files"), list) else []
    cad_license = str(cad.get("license_status", "unknown")).strip().lower()
    cad_actual = (
        cad.get("status") in {"executed", "verified"}
        and cad_license not in {"", "unknown", "unavailable", "missing", "not_run", "not_checked"}
        and cad_execution.get("exit_code") == 0
        and cad_execution.get("opened_verified") is True
        and bool(cad_files)
    )

    cae_execution = cae.get("execution") if isinstance(cae.get("execution"), dict) else {}
    result_files = cae.get("result_files") if isinstance(cae.get("result_files"), list) else []
    cae_license = str(cae.get("license_status", "unknown")).strip().lower()
    cae_actual = (
        cae.get("status") in {"executed", "verified"}
        and cae_license not in {"", "unknown", "unavailable", "missing", "not_run", "not_checked"}
        and cae_execution.get("exit_code") == 0
        and cae_execution.get("success") is True
        and bool(result_files)
        and bool(str(cae.get("solver_log", "")).strip())
    )
    if cad_actual and cae_actual:
        return "L4"
    if cad_actual:
        return "L3"
    return "L2"


def _state_for_highest(root: Path, highest: int) -> dict[str, str]:
    if highest < 0:
        return {"status": "intake", "maturity_level": "L0", "release_level": "draft"}
    statuses = ("evidence_plan", "engineering", "manuscript", "released")
    if highest < gate_index("G3"):
        maturity = "L2"
    else:
        maturity = _execution_maturity(root)
    release = "draft"
    if highest == gate_index("G4"):
        release = "teaching-concept" if maturity == "L2" else "verified-course-design"
    return {"status": statuses[highest], "maturity_level": maturity, "release_level": release}


def effective_project_state(root: Path, manifest: dict[str, Any]) -> dict[str, str]:
    statuses = effective_status(root, manifest)
    highest = -1
    for index, gate in enumerate(GATES):
        if statuses[gate].get("effective_status") != "approved":
            break
        highest = index
    return _state_for_highest(root, highest)


def _append_history(root: Path, event: dict[str, Any]) -> None:
    path = root / _HISTORY
    previous = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    if previous and not previous.endswith("\n"):
        previous += "\n"
    atomic_write_text(path, previous + json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def migrate_snapshots(root: Path, note: str, actor: str = "user") -> dict[str, Any]:
    """Move approved gates to the current snapshot schema without changing approval content."""
    note = note.strip()
    actor = actor.strip()
    if not note or not actor:
        raise ValueError("Snapshot migration note and actor must be non-empty")
    with _project_lock(root):
        manifest = read_json(root / "project.json")
        gates = manifest.get("gates")
        if not isinstance(gates, dict):
            raise ValueError("project.json lacks gate records")
        statuses = effective_status(root, manifest)
        for gate in GATES:
            record = gates.get(gate)
            if isinstance(record, dict) and record.get("status") == "approved":
                if statuses[gate].get("effective_status") != "approved":
                    raise RuntimeError(f"Cannot migrate snapshots: {gate} is not effectively approved")

        prepared: list[tuple[str, dict[str, Any], dict[str, Any], Any, str]] = []
        for gate in GATES:
            record = gates.get(gate)
            if not isinstance(record, dict) or record.get("status") != "approved":
                continue
            old_snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
            old_hash = old_snapshot.get("sha256") or record.get("snapshot_hash")
            old_schema = old_snapshot.get("schema_version", 1)
            if isinstance(old_schema, int) and old_schema >= SNAPSHOT_SCHEMA_VERSION:
                continue
            new_snapshot = snapshot(root, gate, manifest_override=manifest, include_software=False)
            comparison_schema = old_schema if isinstance(old_schema, int) else 1
            old_policy_hash = snapshot_hash(
                root, gate, manifest_override=manifest, schema_version=comparison_schema
            )
            if old_policy_hash != old_hash:
                raise RuntimeError(f"Cannot migrate snapshots: {gate} changed during preparation")
            prepared.append((gate, record, new_snapshot, old_schema, str(old_hash)))

        if not prepared:
            return manifest

        for gate, record, _new_snapshot, old_schema, old_hash in prepared:
            comparison_schema = old_schema if isinstance(old_schema, int) else 1
            if snapshot_hash(root, gate, manifest_override=manifest, schema_version=comparison_schema) != old_hash:
                raise RuntimeError(f"Cannot migrate snapshots: {gate} changed during migration")
            if not _evidence_is_current(root, record.get("evidence")):
                raise RuntimeError(f"Cannot migrate snapshots: {gate} approval evidence changed during migration")

        migrated_at = utc_now()
        migrated: list[dict[str, Any]] = []
        for gate, record, new_snapshot, old_schema, old_hash in prepared:
            record["snapshot"] = new_snapshot
            record["snapshot_hash"] = new_snapshot["sha256"]
            migrations = record.setdefault("snapshot_migrations", [])
            if not isinstance(migrations, list):
                migrations = []
                record["snapshot_migrations"] = migrations
            migration = {
                "from_schema_version": old_schema,
                "to_schema_version": SNAPSHOT_SCHEMA_VERSION,
                "previous_snapshot_sha256": old_hash,
                "snapshot_sha256": new_snapshot["sha256"],
                "at": migrated_at,
                "actor": actor,
                "note": note,
            }
            migrations.append(migration)
            migrated.append({"gate": gate, **migration})
        manifest["updated_at"] = migrated_at
        atomic_write_json(root / "project.json", manifest)
        _append_history(
            root,
            {
                "action": "migrate_snapshots",
                "actor": actor,
                "at": migrated_at,
                "note": note,
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "migrated": migrated,
            },
        )
        return manifest


def approve(root: Path, gate: str, note: str, actor: str, evidence: str | os.PathLike[str]) -> dict[str, Any]:
    note = note.strip()
    actor = actor.strip()
    if not note or not actor:
        raise ValueError("Approval note and actor must be non-empty")
    gate_position = gate_index(gate)
    with _project_lock(root):
        evidence_before = _evidence_entry(root, evidence)
        manifest = read_json(root / "project.json")
        gates = manifest.get("gates")
        if not isinstance(gates, dict) or not isinstance(gates.get(gate), dict):
            raise ValueError(f"project.json lacks a valid {gate} record")
        statuses = effective_status(root, manifest)
        for prior in GATES[:gate_position]:
            if statuses[prior].get("effective_status") != "approved":
                raise RuntimeError(f"Cannot approve {gate}: prior gate {prior} is not effectively approved")
        if gates[gate].get("status") == "approved":
            raise RuntimeError(f"Cannot approve {gate}: gate is already approved; reopen it first")

        before = snapshot(root, gate)
        result = run_audit(root, gate, write_report=True)
        if not isinstance(result, dict) or result.get("passed") is not True:
            raise RuntimeError(f"Cannot approve {gate}: audit has blockers or errors")
        after = snapshot(root, gate)
        evidence_after = _evidence_entry(root, evidence_before["path"])
        if before["sha256"] != after["sha256"] or evidence_before != evidence_after:
            raise RuntimeError(f"Cannot approve {gate}: review package or evidence changed during audit")

        approved_at = utc_now()
        manifest.update(_state_for_highest(root, gate_position))
        manifest["updated_at"] = approved_at
        final_snapshot = snapshot(root, gate, manifest_override=manifest)
        record = gates[gate]
        record.update(
            {
                "status": "approved",
                "approved_at": approved_at,
                "actor": actor,
                "note": note,
                "evidence": evidence_after,
                "snapshot": final_snapshot,
                "snapshot_hash": final_snapshot["sha256"],
            }
        )
        record.pop("reopened_at", None)
        atomic_write_json(root / "project.json", manifest)
        _append_history(
            root,
            {
                "action": "approve",
                "actor": actor,
                "at": approved_at,
                "evidence": evidence_after,
                "gate": gate,
                "note": note,
                "snapshot_sha256": final_snapshot["sha256"],
            },
        )
        return manifest


def reopen(root: Path, gate: str, note: str, actor: str = "user") -> dict[str, Any]:
    note = note.strip()
    actor = actor.strip()
    if not note or not actor:
        raise ValueError("Reopen note and actor must be non-empty")
    position = gate_index(gate)
    with _project_lock(root):
        manifest = read_json(root / "project.json")
        gates = manifest.get("gates")
        if not isinstance(gates, dict):
            raise ValueError("project.json lacks gate records")
        reopened_at = utc_now()
        for current in GATES[position:]:
            source = gates.get(current)
            if not isinstance(source, dict):
                raise ValueError(f"project.json lacks a valid {current} record")
            name = source.get("name")
            source.clear()
            source.update(
                {
                    "name": name,
                    "status": "pending",
                    "approved_at": None,
                    "note": f"Reopened: {note}",
                    "reopened_at": reopened_at,
                }
            )
        manifest.update(_state_for_highest(root, position - 1))
        manifest["updated_at"] = reopened_at
        atomic_write_json(root / "project.json", manifest)
        _append_history(
            root,
            {"action": "reopen", "actor": actor, "at": reopened_at, "gate": gate, "note": note},
        )
        return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and control traceable thesis-project gates")
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status")
    status_parser.add_argument("project")
    approve_parser = sub.add_parser("approve")
    approve_parser.add_argument("project")
    approve_parser.add_argument("gate", choices=GATES)
    approve_parser.add_argument("--note", required=True)
    approve_parser.add_argument("--actor", default="user")
    approve_parser.add_argument("--evidence", required=True, help="Non-empty approval record inside project/approvals")
    reopen_parser = sub.add_parser("reopen")
    reopen_parser.add_argument("project")
    reopen_parser.add_argument("gate", choices=GATES)
    reopen_parser.add_argument("--note", required=True)
    reopen_parser.add_argument("--actor", default="user")
    migrate_parser = sub.add_parser("migrate-snapshots")
    migrate_parser.add_argument("project")
    migrate_parser.add_argument("--note", required=True)
    migrate_parser.add_argument("--actor", default="user")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = project_dir(args.project)
        if args.command == "status":
            manifest = read_json(root / "project.json")
            derived = effective_project_state(root, manifest)
            output = {
                "project_id": manifest.get("project_id"),
                "title": manifest.get("title"),
                "status": derived["status"],
                "maturity_level": derived["maturity_level"],
                "release_level": derived["release_level"],
                "declared_state": {
                    "status": manifest.get("status"),
                    "maturity_level": manifest.get("maturity_level"),
                    "release_level": manifest.get("release_level"),
                },
                "gates": effective_status(root, manifest),
            }
        elif args.command == "approve":
            output = approve(root, args.gate, args.note, args.actor, args.evidence)
        elif args.command == "reopen":
            output = reopen(root, args.gate, args.note, args.actor)
        else:
            output = migrate_snapshots(root, args.note, args.actor)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
