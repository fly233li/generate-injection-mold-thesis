from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from common import atomic_write_bytes, atomic_write_json, atomic_write_text, project_dir, read_json, utc_now
from nx_stage_run import authenticode_info
from project_state import _project_lock


HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
HISTORY_RELATIVE = Path("04_cad/nx/runtime/validation-history.jsonl")
SKILL_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_JOURNALS = {
    "runtime": SKILL_ROOT / "assets/project-template/04_cad/nx/journals/nxopen-probe-journal.py",
    "capability": SKILL_ROOT / "assets/project-template/04_cad/nx/journals/nx-capability-probe-journal.py",
}
RESULT_FILES = {
    "runtime": "nxopen-probe-result.json",
    "capability": "capability/capability-result.json",
}
STATUS_RANK = {"not_run": 0, "verified_runtime": 1, "verified_modeling_drafting_pdf": 2}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_file(root: Path, raw: str | os.PathLike[str], label: str) -> tuple[Path, str]:
    source = Path(raw).expanduser()
    candidate = source if source.is_absolute() else root / source
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root.resolve()).as_posix()
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValueError(f"{label} must be an existing file inside the project") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must be a regular file, not a link")
    return resolved, relative


def same_path(left: str | os.PathLike[str], right: str | os.PathLike[str]) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(os.path.abspath(os.fspath(right)))


def validate_record(
    root: Path,
    record: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[Path, str]:
    if not isinstance(record, dict):
        raise ValueError(f"{label} is not a file record")
    relative = record.get("path")
    size = record.get("size")
    digest = record.get("sha256")
    if record.get("exists") is not True or not isinstance(relative, str) or not relative:
        raise ValueError(f"{label} does not identify an existing project file")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0 or (size == 0 and not allow_empty):
        raise ValueError(f"{label} has no acceptable file size")
    if not isinstance(digest, str) or not HEX_SHA256.fullmatch(digest):
        raise ValueError(f"{label} has no valid SHA-256")
    path, normalized = project_file(root, relative, label)
    if path.stat().st_size != size or sha256_file(path) != digest:
        raise ValueError(f"{label} no longer matches its recorded size and SHA-256")
    return path, normalized


def joined_project_relative(base: str, raw: str, label: str) -> str:
    base_path = Path(base.replace("\\", "/"))
    child = Path(raw.replace("\\", "/"))
    if (
        not base
        or base_path.is_absolute()
        or base_path.drive
        or base_path.root
        or base_path.anchor
        or ".." in base_path.parts
    ):
        raise ValueError("NX staging report has an invalid run directory")
    if (
        not raw
        or child.is_absolute()
        or child.drive
        or child.root
        or child.anchor
        or ".." in child.parts
    ):
        raise ValueError(f"capability result has an invalid {label}")
    return (base_path / child).as_posix()


def validate_component(
    components: dict[str, Any],
    name: str,
    expected_path: Path,
    *,
    require_signature: bool = False,
) -> None:
    record = components.get(name)
    if not isinstance(record, dict):
        raise ValueError(f"NX staging report lacks component evidence for {name}")
    if not same_path(str(record.get("path", "")), expected_path):
        raise ValueError(f"NX staging component {name} is not from the declared NX root")
    if not expected_path.is_file() or expected_path.is_symlink() or expected_path.stat().st_size <= 0:
        raise ValueError(f"NX staging component {name} is missing or invalid")
    if record.get("size") != expected_path.stat().st_size or record.get("sha256") != sha256_file(expected_path):
        raise ValueError(f"NX staging component {name} no longer matches its size and SHA-256")
    if require_signature:
        recorded_signature = record.get("authenticode")
        if not isinstance(recorded_signature, dict):
            raise ValueError(f"NX staging component {name} lacks Authenticode evidence")
        current_signature = authenticode_info(expected_path)
        for key in ("status", "subject", "thumbprint"):
            if str(recorded_signature.get(key, "")) != str(current_signature.get(key, "")):
                raise ValueError(f"NX staging component {name} Authenticode evidence changed")


def validate_report(
    root: Path,
    report_path: Path,
    report: Any,
    scope: str,
) -> dict[str, tuple[Path, str]]:
    if not isinstance(report, dict):
        raise ValueError("NX staging report must be a JSON object")
    if report.get("schema_version") != "1.1":
        raise ValueError("NX staging report must use schema 1.1 component evidence")
    if report.get("success") is not True or report.get("exit_code") != 0:
        raise ValueError("NX staging report is not successful with exit code 0")
    if report.get("timed_out") is not False or report.get("mapping_removed") is not True:
        raise ValueError("NX staging report does not prove clean completion and mapping removal")
    staging = report.get("staging") if isinstance(report.get("staging"), dict) else {}
    if staging.get("mode") != "subst_project_root" or staging.get("persist_environment") is not False:
        raise ValueError("NX staging report does not use the approved project-local subst profile")
    if staging.get("sets_ugii_root_dir") is not False:
        raise ValueError("NX staging report unexpectedly sets UGII_ROOT_DIR")
    if not same_path(str(staging.get("physical_target", "")), root):
        raise ValueError("NX staging report belongs to a different project")
    if not same_path(str(report.get("project", "")), root):
        raise ValueError("NX staging report project root does not match this project")
    run_directory = str(staging.get("run_directory", ""))
    report_run_directory = report_path.parent.relative_to(root.resolve()).as_posix()
    if run_directory != report_run_directory:
        raise ValueError("NX staging report is not stored in its declared run directory")
    nx_root = str(report.get("nx_root", ""))
    nx_root_path = Path(nx_root)
    if not same_path(str(report.get("bootstrap", "")), Path(nx_root) / "UGII/ugiicmd.bat"):
        raise ValueError("NX staging report did not use the Siemens command environment from its NX root")
    if not same_path(str(report.get("runner", "")), Path(nx_root) / "NXBIN/run_journal.exe"):
        raise ValueError("NX staging report did not use run_journal from its NX root")
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    validate_component(components, "ugraf", nx_root_path / "NXBIN/ugraf.exe", require_signature=True)
    validate_component(
        components,
        "run_journal",
        nx_root_path / "NXBIN/run_journal.exe",
        require_signature=True,
    )
    validate_component(components, "command_environment", nx_root_path / "UGII/ugiicmd.bat")
    validate_component(
        components,
        "manifest_schema",
        nx_root_path / "UGII/manifest/platform/configuration.xsd",
    )
    if report.get("journal_args") != []:
        raise ValueError("canonical NX diagnostic journals do not accept journal arguments")
    journal, _journal_relative = project_file(root, str(report.get("journal", "")), "journal")
    journal_digest = report.get("journal_sha256")
    if not isinstance(journal_digest, str) or sha256_file(journal) != journal_digest:
        raise ValueError("NX staging report journal hash does not match the project journal")
    canonical = CANONICAL_JOURNALS[scope]
    if not canonical.is_file() or sha256_file(journal) != sha256_file(canonical):
        raise ValueError(f"{scope} report did not execute the canonical skill journal")
    logs_detail = report.get("logs_detail") if isinstance(report.get("logs_detail"), dict) else {}
    stdout_path, stdout_relative = validate_record(root, logs_detail.get("stdout"), "stdout log")
    stderr_path, stderr_relative = validate_record(root, logs_detail.get("stderr"), "stderr log", allow_empty=True)
    wrapper_path, wrapper_relative = validate_record(root, logs_detail.get("wrapper"), "command wrapper")
    run_path = Path(run_directory)
    for label, relative in (
        ("stdout log", stdout_relative),
        ("stderr log", stderr_relative),
        ("command wrapper", wrapper_relative),
    ):
        try:
            Path(relative).relative_to(run_path)
        except ValueError as exc:
            raise ValueError(f"{label} is outside the declared run directory") from exc
    if stderr_path.stat().st_size != 0:
        raise ValueError("successful canonical NX diagnostic has nonempty stderr")
    wrapper = wrapper_path.read_text(encoding="ascii")
    drive_letter = str(staging.get("drive_letter", "")).strip().upper().rstrip(":")
    mapped_journal = f"{drive_letter}:\\" + str(report.get("journal", "")).replace("/", "\\")
    required_wrapper_text = (
        'set "UGII_ROOT_DIR="',
        f'call "{nx_root_path / "UGII/ugiicmd.bat"}" "{nx_root_path}"',
        str(nx_root_path / "NXBIN/run_journal.exe"),
        mapped_journal,
    )
    if not drive_letter or any(item not in wrapper for item in required_wrapper_text):
        raise ValueError("NX command wrapper does not match the approved launch contract")
    if str(root) in wrapper:
        raise ValueError("NX command wrapper leaks the physical project path instead of the ASCII mapping")
    system_logs = report.get("system_logs")
    if not isinstance(system_logs, list):
        raise ValueError("NX staging report system_logs must be a list")
    for index, record in enumerate(system_logs):
        _path, relative = validate_record(root, record, f"system_logs[{index}]", allow_empty=True)
        try:
            Path(relative).relative_to(run_path)
        except ValueError as exc:
            raise ValueError(f"system_logs[{index}] is outside the declared run directory") from exc
    if stdout_path.stat().st_size <= 0:
        raise ValueError("successful canonical NX diagnostic has no stdout evidence")
    expected = report.get("expected_files")
    if not isinstance(expected, list) or not expected:
        raise ValueError("NX staging report has no expected-file evidence")
    verified: dict[str, tuple[Path, str]] = {}
    for index, record in enumerate(expected):
        path, relative = validate_record(root, record, f"expected_files[{index}]")
        if relative in verified:
            raise ValueError(f"duplicate expected-file evidence: {relative}")
        verified[relative] = (path, relative)
    required_expected = {
        joined_project_relative(run_directory, RESULT_FILES[scope], "result")
    }
    if scope == "capability":
        required_expected.update(
            {
                joined_project_relative(run_directory, "capability/nx-capability-probe.prt", "part_file"),
                joined_project_relative(run_directory, "capability/nx-capability-probe.pdf", "pdf_file"),
            }
        )
    if set(verified) != required_expected:
        raise ValueError("canonical NX diagnostic expected-file set is incomplete or contains extra files")
    if not report_path.is_file():
        raise ValueError("NX staging report disappeared during validation")
    return verified


def validate_result(
    scope: str,
    result: Any,
    verified: dict[str, tuple[Path, str]],
    run_directory: str,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("NX validation result must be a JSON object")
    expected_journal = CANONICAL_JOURNALS[scope].name
    if result.get("journal") != expected_journal:
        raise ValueError(f"{scope} result was not produced by {expected_journal}")
    if not isinstance(result.get("nx_full_version"), str) or not result.get("nx_full_version", "").strip():
        raise ValueError(f"{scope} result has no NX full version")
    if scope == "runtime":
        if result.get("nxopen_imported") is not True or result.get("session_acquired") is not True:
            raise ValueError("runtime result does not prove NXOpen import and session acquisition")
        namespaces = result.get("namespace_imports")
        required = ("NXOpen.Features", "NXOpen.Drawings", "NXOpen.Drafting")
        if not isinstance(namespaces, dict) or any(namespaces.get(name) != "ok" for name in required):
            raise ValueError("runtime result does not prove the required NXOpen namespace imports")
        return {
            "runtime_status": "verified_runtime",
            "scope": ["nxopen_session", "features_namespace", "drawings_namespace", "drafting_namespace"],
            "limitations": result.get("limitations", []),
        }

    required_true = (
        "success",
        "part_created",
        "block_feature_created",
        "drawing_sheet_created",
        "base_view_created",
        "part_saved",
        "pdf_exported",
        "reopen_succeeded",
    )
    if any(result.get(key) is not True for key in required_true):
        raise ValueError("capability result does not prove all required operations")
    for key in (
        "body_count_after_modeling",
        "drawing_view_count",
        "body_count_after_reopen",
        "drawing_sheet_count_after_reopen",
        "drawing_view_count_after_reopen",
    ):
        value = result.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"capability result has an invalid {key}")
    covered_paths: dict[str, Path] = {}
    for key in ("part_file", "pdf_file"):
        relative = result.get(key)
        covered = joined_project_relative(run_directory, relative, key) if isinstance(relative, str) else ""
        if not covered or covered not in verified:
            raise ValueError(f"capability result {key} is not covered by expected-file evidence")
        covered_paths[key] = verified[covered][0]
    part_path = covered_paths["part_file"]
    pdf_path = covered_paths["pdf_file"]
    if part_path.read_bytes()[:8] != b"SPLMSSTR":
        raise ValueError("capability PRT does not have the Siemens native-part signature")
    if pdf_path.read_bytes()[:5] != b"%PDF-":
        raise ValueError("capability PDF does not have a PDF header")
    if result.get("part_size_bytes") != part_path.stat().st_size:
        raise ValueError("capability PRT size does not match the journal result")
    if result.get("pdf_size_bytes") != pdf_path.stat().st_size:
        raise ValueError("capability PDF size does not match the journal result")
    return {
        "runtime_status": "verified_modeling_drafting_pdf",
        "scope": ["nxopen_session", "basic_modeling", "drafting_base_view", "native_save_reopen", "pdf_export"],
        "limitations": result.get("limitations", []),
    }


def append_history(path: Path, event: dict[str, Any]) -> None:
    previous = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    if previous and not previous.endswith("\n"):
        previous += "\n"
    atomic_write_text(path, previous + json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def register(project: str, report_raw: str, result_raw: str, scope: str) -> dict[str, Any]:
    root = project_dir(project)
    with _project_lock(root):
        report_path, report_relative = project_file(root, report_raw, "report")
        result_path, result_relative = project_file(root, result_raw, "result")
        report = read_json(report_path)
        verified = validate_report(root, report_path, report, scope)
        staging = report.get("staging") if isinstance(report.get("staging"), dict) else {}
        run_directory = str(staging.get("run_directory", ""))
        expected_result = joined_project_relative(run_directory, RESULT_FILES[scope], "result")
        if result_relative != expected_result or result_relative not in verified:
            raise ValueError("result file is not the canonical result covered by expected-file evidence")
        result = read_json(result_path)
        capability = validate_result(scope, result, verified, run_directory)

        manifest_path = root / "project.json"
        probe_path = root / "software-probe.json"
        history_path = root / HISTORY_RELATIVE
        manifest = read_json(manifest_path)
        probe = read_json(probe_path)
        software = manifest.get("software") if isinstance(manifest.get("software"), dict) else None
        nx = probe.get("nx") if isinstance(probe.get("nx"), dict) else None
        if software is None or nx is None:
            raise ValueError("project and software probe must contain software/NX objects")
        report_root = str(report.get("nx_root", ""))
        if not same_path(report_root, str(nx.get("selected_root", ""))) or not same_path(
            report_root, str(software.get("nx_root", ""))
        ):
            raise ValueError("report NX root does not match the current static probe and project configuration")

        run_id = str(report.get("run_id", "")).strip()
        if not run_id:
            raise ValueError("NX staging report has no run_id")
        attempts = nx.setdefault("runtime_attempts", [])
        if not isinstance(attempts, list):
            raise ValueError("software-probe nx.runtime_attempts must be a list")
        prior_attempt = next(
            (
                item
                for item in attempts
                if isinstance(item, dict) and item.get("attempt_id") == run_id
            ),
            None,
        )
        now = utc_now()
        validation = {
            "status": capability["runtime_status"],
            "scope": capability["scope"],
            "validated_at": now,
            "attempt_id": run_id,
            "report": report_relative,
            "report_sha256": sha256_file(report_path),
            "result": result_relative,
            "result_sha256": sha256_file(result_path),
            "nx_full_version": result.get("nx_full_version", ""),
            "limitations": capability["limitations"],
        }
        if prior_attempt is not None:
            if prior_attempt.get("report") != report_relative:
                raise ValueError("attempt_id was already registered from a different report")
            if (
                prior_attempt.get("report_sha256") != validation["report_sha256"]
                or prior_attempt.get("result_sha256") != validation["result_sha256"]
            ):
                raise ValueError("attempt_id/report was already registered with different evidence")
            current = nx.get("runtime_validation")
            registered_validation = (
                current
                if isinstance(current, dict) and current.get("report") == report_relative
                else {
                    "status": prior_attempt.get("result"),
                    "attempt_id": run_id,
                    "report": report_relative,
                    "report_sha256": prior_attempt.get("report_sha256"),
                    "result": result_relative,
                    "result_sha256": prior_attempt.get("result_sha256"),
                }
            )
            return {"registered": False, "reason": "already_registered", "validation": registered_validation}

        current_status = str(nx.get("runtime_status", "not_run"))
        status_promoted = STATUS_RANK.get(capability["runtime_status"], -1) >= STATUS_RANK.get(current_status, -1)
        attempt = {
            "attempt_id": run_id,
            "executed_at": report.get("finished_at"),
            "exit_code": report.get("exit_code"),
            "result": capability["runtime_status"],
            "report": report_relative,
            "report_sha256": validation["report_sha256"],
            "result_file": result_relative,
            "result_sha256": validation["result_sha256"],
            "staging_mode": "subst_project_root",
            "mapping_removed": True,
            "status_promoted": status_promoted,
        }
        attempts.append(attempt)
        execution_profile = {
            "staging_mode": "subst_project_root",
            "official_command_environment": report.get("bootstrap"),
            "persist_environment": False,
            "sets_ugii_root_dir": False,
        }
        if status_promoted:
            nx.update(
                {
                    "runtime_status": capability["runtime_status"],
                    "license_status": "available_for_tested_scope",
                    "backend": "nxopen_python_run_journal",
                    "runtime_validation": validation,
                    "execution_profile": execution_profile,
                }
            )
            software.update(
                {
                    "nx_backend": "nxopen_python_run_journal",
                    "nx_license": "available_for_tested_scope",
                    "nx_runtime_status": capability["runtime_status"],
                    "nx_runtime_evidence": report_relative,
                    "nx_validation_scope": capability["scope"],
                    "nx_execution_profile": execution_profile,
                }
            )
        software["software_revision"] = int(software.get("software_revision", 0)) + 1
        manifest["updated_at"] = now
        history_event = {
            "action": "register_nx_validation",
            "at": now,
            "attempt_id": run_id,
            "scope": scope,
            "status": capability["runtime_status"],
            "status_promoted": status_promoted,
            "report": report_relative,
            "report_sha256": validation["report_sha256"],
            "result": result_relative,
            "result_sha256": validation["result_sha256"],
            "cad_artifact_promoted": False,
        }

        backups = {
            probe_path: probe_path.read_bytes(),
            manifest_path: manifest_path.read_bytes(),
            history_path: history_path.read_bytes() if history_path.is_file() else None,
        }
        try:
            atomic_write_json(probe_path, probe)
            atomic_write_json(manifest_path, manifest)
            append_history(history_path, history_event)
        except Exception as exc:
            rollback_errors: list[str] = []
            for path, data in backups.items():
                try:
                    if data is None:
                        if path.is_file():
                            path.unlink()
                    else:
                        atomic_write_bytes(path, data)
                except Exception as rollback_exc:
                    rollback_errors.append(f"{path}: {rollback_exc}")
            if rollback_errors:
                raise RuntimeError(
                    "NX validation registration failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise
        return {
            "registered": True,
            "validation": validation,
            "current_status_updated": status_promoted,
            "cad_artifact_promoted": False,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and register project-local NX staging evidence")
    parser.add_argument("--project", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--scope", required=True, choices=("runtime", "capability"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        output = register(args.project, args.report, args.result, args.scope)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
