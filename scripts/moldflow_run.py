from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import atomic_write_json, project_dir, read_json, utc_now
from project_state import _project_lock


TOOLS = ("runstudy.exe", "studymod.exe", "studyrlt.exe")
SAFE_CASE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
RESULT_SUFFIXES = {".sdy", ".mpi", ".udm", ".mfr", ".out", ".xml", ".res", ".pat", ".stl", ".txt"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_file(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser().resolve(strict=True)
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Path must remain inside project: {path}") from exc
    return path


def cli_bin(raw: str) -> Path:
    path = Path(raw).expanduser().resolve(strict=True)
    if path.is_file():
        path = path.parent
    if not path.is_dir() or not all((path / tool).is_file() for tool in TOOLS):
        raise ValueError("Moldflow CLI directory must contain runstudy.exe, studymod.exe and studyrlt.exe")
    return path


def file_entry(root: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "role": role,
        "length": path.stat().st_size,
        "sha256": sha256(path),
    }


def run_logged(command: list[str], cwd: Path, stdout: Path, stderr: Path, timeout: int) -> int:
    with stdout.open("w", encoding="utf-8", newline="") as out, stderr.open("w", encoding="utf-8", newline="") as err:
        process = subprocess.run(command, cwd=cwd, stdout=out, stderr=err, text=True, timeout=timeout, check=False)
    return process.returncode


def inventory_case(root: Path, case_dir: Path, runtime_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for base, default_role in ((case_dir, "moldflow_study"), (runtime_dir, "moldflow_result")):
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if base == case_dir and path.suffix.casefold() not in RESULT_SUFFIXES:
                continue
            role = default_role
            if path.name.casefold().endswith("runstudy.stdout.log"):
                role = "moldflow_log"
            elif path.name.casefold().endswith("screen-output.txt"):
                role = "moldflow_extract"
            elif path.suffix.casefold() == ".sdy":
                role = "moldflow_study"
            entries.append(file_entry(root, path, role))
    return entries


def metadata_ready(data: dict[str, Any], case_id: str) -> list[str]:
    missing: list[str] = []
    for field in ("tool_version", "material_grade", "material_card_id", "geometry_revision"):
        if str(data.get(field, "")).strip().casefold() in {"", "unknown", "unselected", "none"}:
            missing.append(field)
    mesh = data.get("mesh")
    if not isinstance(mesh, dict) or not mesh.get("type") or not mesh.get("target_size_mm") or not mesh.get("element_count") or not mesh.get("quality_metrics"):
        missing.append("mesh(type,target_size_mm,element_count,quality_metrics)")
    cases = data.get("cases")
    if not isinstance(cases, list) or not any(isinstance(case, dict) and case.get("case_id") == case_id for case in cases):
        missing.append(f"cases[{case_id}]")
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a saved Moldflow study and retain solver evidence")
    parser.add_argument("--project", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--study", required=True, help="Saved .sdy study inside the project case folder")
    parser.add_argument("--moldflow-bin", required=True)
    parser.add_argument("--execute", action="store_true", help="Actually invoke runstudy; otherwise uses runstudy -dry-run")
    parser.add_argument("--commit", action="store_true", help="Promote the study manifest only after a successful actual solve and extraction")
    parser.add_argument("--session-key-file", help="Optional session-key file; contents are never copied or logged")
    parser.add_argument("--timeout-sec", type=int, default=7200)
    args = parser.parse_args()
    try:
        if not SAFE_CASE.fullmatch(args.case_id):
            raise ValueError("case-id must use letters, digits, _ or - and be at most 80 characters")
        if args.commit and not args.execute:
            raise ValueError("--commit requires --execute")
        root = project_dir(args.project)
        study = project_file(root, args.study)
        if study.suffix.casefold() != ".sdy":
            raise ValueError("study must be a .sdy file")
        bin_dir = cli_bin(args.moldflow_bin)
        case_dir = study.parent
        runtime_dir = root / "05_cae" / "runtime" / f"MF-{args.case_id}"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = runtime_dir / "temp"
        temp_dir.mkdir(exist_ok=True)
        output = runtime_dir / "runstudy.stdout.log"; error = runtime_dir / "runstudy.stderr.log"
        command = [str(bin_dir / "runstudy.exe"), study.name, "-temp", str(temp_dir), "-keeptmp", "-units", "METRIC"]
        if not args.execute:
            command.append("-dry-run")
        if args.session_key_file:
            key_file = Path(args.session_key_file).expanduser().resolve(strict=True)
            command.extend(["-kfile", str(key_file)])
        run_exit = run_logged(command, case_dir, output, error, args.timeout_sec)
        extract_exit: int | None = None
        extract_output = runtime_dir / "screen-output"
        extract_log = runtime_dir / "studyrlt.stdout.log"; extract_error = runtime_dir / "studyrlt.stderr.log"
        extracted = runtime_dir / "screen-output.txt"
        if args.execute and run_exit == 0:
            extract_command = [str(bin_dir / "studyrlt.exe"), study.name, "-exportoutput", "-output", str(extract_output), "-unit", "Metric"]
            extract_exit = run_logged(extract_command, case_dir, extract_log, extract_error, args.timeout_sec)
            candidates = list(runtime_dir.glob("screen-output*.txt"))
            if candidates and candidates[0] != extracted:
                candidates[0].replace(extracted)
        entries = inventory_case(root, case_dir, runtime_dir)
        record = {
            "schema_version": "1.0", "case_id": args.case_id, "created_at": utc_now(),
            "study": file_entry(root, study, "moldflow_study"),
            "cli": {tool: file_entry(root, bin_dir / tool, "moldflow_cli") for tool in TOOLS},
            "mode": "execute" if args.execute else "dry_run",
            "command": ["<session-key-redacted>" if token == "-kfile" or (index and command[index - 1] == "-kfile") else token for index, token in enumerate(command)],
            "execution": {"runstudy_exit_code": run_exit, "studyrlt_exit_code": extract_exit, "success": bool(args.execute and run_exit == 0 and extract_exit == 0 and extracted.is_file())},
            "result_files": entries,
            "limitations": "A dry run, executable presence or an output image is not a solver result. Commit requires a successful solve, extraction and complete study metadata.",
        }
        atomic_write_json(runtime_dir / "case-result.json", record)
        if args.commit:
            if not record["execution"]["success"]:
                raise RuntimeError("Cannot commit Moldflow evidence: runstudy/studyrlt did not complete successfully")
            with _project_lock(root):
                manifest_path = root / "05_cae" / "moldflow-study.json"
                data = read_json(manifest_path)
                if not isinstance(data, dict):
                    raise ValueError("moldflow-study.json must be an object")
                missing = metadata_ready(data, args.case_id)
                if missing:
                    raise RuntimeError("Cannot commit Moldflow evidence; register actual study metadata first: " + ", ".join(missing))
                data["backend"] = "moldflow"; data["status"] = "executed"; data["license_status"] = "verified"
                data["execution"] = {"exit_code": 0, "completed_at": utc_now(), "success": True, "case_id": args.case_id}
                data["solver_log"] = output.relative_to(root).as_posix()
                data["result_files"] = entries
                atomic_write_json(manifest_path, data)
        print(json.dumps({"case_id": args.case_id, "record": str((runtime_dir / "case-result.json").relative_to(root)), "success": record["execution"]["success"], "committed": bool(args.commit)}, ensure_ascii=False))
        return 0 if run_exit == 0 and (not args.execute or extract_exit == 0) else 1
    except subprocess.TimeoutExpired as exc:
        print(f"ERROR: Moldflow command timed out: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
