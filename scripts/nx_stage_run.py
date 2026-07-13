from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from cad_probe import normalize_nx_root
from common import atomic_write_json, atomic_write_text, project_dir, read_json, utc_now


SKILL_ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = SKILL_ROOT / "assets" / "local-software-paths.json"
PROFILE_RELATIVE = Path("04_cad/nx/nx-runtime-config.json")
DEFAULT_RUNTIME_RELATIVE = Path("04_cad/nx/runtime/staging")
DEFAULT_DRIVE_LETTERS = ("N", "R", "S", "T", "V", "W", "X", "Y", "Z")
RUN_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
CMD_UNSAFE = set("%!&|<>^\"()\r\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def authenticode_info(path: Path) -> dict[str, str]:
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    if not powershell.is_file():
        raise FileNotFoundError(f"Windows PowerShell is unavailable: {powershell}")
    environment = os.environ.copy()
    environment["NX_SIGNATURE_PATH"] = str(path)
    script = (
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$s=Get-AuthenticodeSignature -LiteralPath $env:NX_SIGNATURE_PATH;"
        "$subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''};"
        "$thumb=if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{''};"
        "[pscustomobject]@{status=[string]$s.Status;subject=$subject;thumbprint=$thumb}"
        "|ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            env=environment,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Authenticode inspection timed out for {path}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Authenticode inspection failed for {path}: {detail}")
    try:
        data = json.loads(completed.stdout.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Authenticode inspection returned invalid JSON for {path}") from exc
    output = {key: str(data.get(key, "")) for key in ("status", "subject", "thumbprint")}
    if output["status"].casefold() != "valid" or "siemens" not in output["subject"].casefold():
        raise RuntimeError(f"NX executable is not validly signed by Siemens: {path}")
    return output


def component_record(path: Path, *, require_signature: bool = False) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
        raise FileNotFoundError(f"NX runtime component is missing or invalid: {path}")
    record: dict[str, Any] = {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if require_signature:
        record["authenticode"] = authenticode_info(path)
    return record


def file_record(path: Path, root: Path) -> dict[str, Any]:
    try:
        relative = path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except ValueError:
        relative = ""
    regular = path.is_file() and not path.is_symlink()
    return {
        "path": relative,
        "exists": regular,
        "size": path.stat().st_size if regular else None,
        "sha256": sha256_file(path) if regular else None,
    }


def safe_relative(raw: str, label: str) -> Path:
    value = raw.strip().replace("\\", "/")
    path = Path(value)
    if not value or path.is_absolute() or path.drive or path.root or path.anchor or ".." in path.parts:
        raise ValueError(f"{label} must be a project-relative path without '..': {raw}")
    return path


def ensure_project_file(root: Path, raw: str | os.PathLike[str], label: str) -> tuple[Path, Path]:
    source = Path(raw).expanduser()
    candidate = source if source.is_absolute() else root / source
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root.resolve())
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise ValueError(f"{label} must be an existing file inside the project") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"{label} must be a regular file, not a link: {resolved}")
    return resolved, relative


def ensure_ascii(value: str, label: str, *, command_safe: bool = False) -> None:
    if not value.isascii():
        raise ValueError(f"{label} must be ASCII for the NX command environment: {value}")
    if command_safe and any(char in CMD_UNSAFE for char in value):
        raise ValueError(f"{label} contains a character unsafe for cmd.exe")


def drive_in_use(letter: str) -> bool:
    index = ord(letter.upper()) - ord("A")
    if index < 0 or index > 25:
        return True
    mask = int(ctypes.windll.kernel32.GetLogicalDrives()) if os.name == "nt" else 0
    return bool(mask & (1 << index))


def drive_target(letter: str) -> Path | None:
    if os.name != "nt":
        return None
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.kernel32.QueryDosDeviceW(f"{letter.upper()}:", buffer, len(buffer))
    if result == 0:
        return None
    raw = buffer.value
    prefix = "\\??\\"
    if not raw.startswith(prefix):
        return None
    return Path(raw[len(prefix) :])


def same_filesystem_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def select_drive(preferred: list[str]) -> str:
    for raw in preferred:
        letter = str(raw).strip().upper().rstrip(":")
        if re.fullmatch(r"[D-Z]", letter) and not drive_in_use(letter):
            return letter
    raise RuntimeError("No unused staging drive letter is available")


def load_runtime_profile(root: Path, explicit_nx_root: str | None) -> dict[str, Any]:
    profile_path = root / PROFILE_RELATIVE
    profile = read_json(profile_path) if profile_path.is_file() else {}
    if not isinstance(profile, dict):
        raise ValueError(f"NX runtime profile must be a JSON object: {profile_path}")

    configured_root = explicit_nx_root or str(profile.get("nx_root", "")).strip()
    if not configured_root and LOCAL_CONFIG.is_file():
        local = read_json(LOCAL_CONFIG)
        roots = local.get("nx_roots", []) if isinstance(local, dict) else []
        if isinstance(roots, list) and roots:
            configured_root = str(roots[0])
    if not configured_root:
        raise ValueError("No NX root is configured; pass --nx-root or set nx-runtime-config.json")

    nx_root = normalize_nx_root(configured_root, strict=True)
    assert nx_root is not None
    ensure_ascii(str(nx_root), "NX root", command_safe=True)
    bootstrap = nx_root / "UGII" / "ugiicmd.bat"
    runner = nx_root / "NXBIN" / "run_journal.exe"
    ugraf = nx_root / "NXBIN" / "ugraf.exe"
    schema = nx_root / "UGII" / "manifest" / "platform" / "configuration.xsd"
    for label, path in (
        ("Siemens command environment", bootstrap),
        ("run_journal", runner),
        ("ugraf", ugraf),
        ("manifest schema", schema),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} is missing: {path}")

    staging = profile.get("staging") if isinstance(profile.get("staging"), dict) else {}
    mode = str(staging.get("mode", "subst_project_root"))
    if mode != "subst_project_root":
        raise ValueError(f"Unsupported NX staging mode: {mode}")
    runtime_relative = safe_relative(str(staging.get("runtime_dir", DEFAULT_RUNTIME_RELATIVE.as_posix())), "runtime_dir")
    preferred = staging.get("preferred_drive_letters", list(DEFAULT_DRIVE_LETTERS))
    if not isinstance(preferred, list):
        raise ValueError("preferred_drive_letters must be a list")
    timeout = int(staging.get("timeout_seconds", 300))
    if timeout < 1 or timeout > 86400:
        raise ValueError("timeout_seconds must be between 1 and 86400")
    return {
        "profile_path": profile_path if profile_path.is_file() else None,
        "nx_root": nx_root,
        "bootstrap": bootstrap,
        "runner": runner,
        "ugraf": ugraf,
        "manifest_schema": schema,
        "runtime_relative": runtime_relative,
        "preferred_drive_letters": [str(item) for item in preferred],
        "timeout_seconds": timeout,
    }


def mapped_path(letter: str, relative: Path) -> Path:
    return Path(f"{letter}:\\") / relative


def command_wrapper(
    profile: dict[str, Any],
    letter: str,
    journal_relative: Path,
    run_relative: Path,
    journal_args: list[str],
) -> str:
    mapped_run = mapped_path(letter, run_relative)
    mapped_journal = mapped_path(letter, journal_relative)
    mapped_work = mapped_run / "work"
    mapped_tmp = mapped_run / "tmp"
    mapped_user = mapped_run / "user"
    mapped_output = mapped_run / "output"
    for label, value in (
        ("mapped journal path", str(mapped_journal)),
        ("mapped run path", str(mapped_run)),
    ):
        ensure_ascii(value, label, command_safe=True)
    for index, value in enumerate(journal_args):
        ensure_ascii(value, f"journal argument {index + 1}", command_safe=True)

    command = [str(profile["runner"]), str(mapped_journal)]
    if journal_args:
        command.extend(["-args", *journal_args])
    run_line = subprocess.list2cmdline(command)
    lines = [
        "@echo off",
        "setlocal EnableExtensions DisableDelayedExpansion",
        f'set "TEMP={mapped_tmp}"',
        f'set "TMP={mapped_tmp}"',
        f'set "UGII_TMP_DIR={mapped_tmp}"',
        f'set "UGII_USER_DIR={mapped_user}"',
        f'set "UGII_USER_PROFILE_DIR={mapped_user}"',
        f'set "HOME={mapped_user}"',
        'set "UGII_ROOT_DIR="',
        f'set "THESIS_NX_PROJECT_ROOT={letter}:\\"',
        f'set "THESIS_NX_RUN_DIR={mapped_run}"',
        f'set "THESIS_NX_OUTPUT_DIR={mapped_output}"',
        f'call "{profile["bootstrap"]}" "{profile["nx_root"]}"',
        "if errorlevel 1 exit /b %errorlevel%",
        "@echo off",
        f'cd /d "{mapped_work}"',
        run_line,
        "set \"NX_STAGE_EXIT=%ERRORLEVEL%\"",
        "exit /b %NX_STAGE_EXIT%",
    ]
    text = "\r\n".join(lines) + "\r\n"
    ensure_ascii(text, "generated command wrapper")
    return text


def subst_executable() -> Path:
    return Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "subst.exe"


def map_drive(letter: str, target: Path) -> None:
    completed = subprocess.run(
        [str(subst_executable()), f"{letter}:", str(target)],
        check=False,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode == 0:
        for attempt in range(3):
            actual = drive_target(letter)
            if actual is not None and same_filesystem_path(actual, target):
                return
            if attempt < 2:
                time.sleep(0.2)
    detail = completed.stderr.decode(errors="replace").strip()
    raise RuntimeError(f"Failed to create and verify {letter}: staging mapping: {detail}")


def unmap_drive(letter: str, target: Path, attempts: int = 3) -> bool:
    for attempt in range(attempts):
        actual = drive_target(letter)
        if actual is None:
            return True
        if not same_filesystem_path(actual, target):
            return False
        subprocess.run(
            [str(subst_executable()), f"{letter}:", "/D"],
            check=False,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if drive_target(letter) is None:
            return True
        if attempt + 1 < attempts:
            time.sleep(0.2)
    return False


def terminate_tree(process: subprocess.Popen[Any]) -> None:
    subprocess.run(
        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
        check=False,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def execute(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if os.name != "nt":
        raise RuntimeError("NX staging runner currently supports Windows only")
    root = project_dir(args.project)
    profile = load_runtime_profile(root, args.nx_root)
    journal, journal_relative = ensure_project_file(root, args.journal, "journal")
    ensure_ascii(str(mapped_path("N", journal_relative)), "mapped journal path", command_safe=True)

    run_id = args.run_id or (time.strftime("NX-%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8])
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("run-id must contain only ASCII letters, digits, dot, underscore, or hyphen")
    runtime_relative = profile["runtime_relative"]
    run_relative = runtime_relative / run_id
    run_dir = root / run_relative
    if run_dir.exists():
        raise FileExistsError(f"NX run directory already exists: {run_dir}")

    preferred = [args.drive_letter] if args.drive_letter else profile["preferred_drive_letters"]
    letter = select_drive(preferred)
    timeout_seconds = profile["timeout_seconds"] if args.timeout_seconds is None else args.timeout_seconds
    if timeout_seconds < 1 or timeout_seconds > 86400:
        raise ValueError("timeout-seconds must be between 1 and 86400")
    journal_args = list(args.journal_arg or [])
    for index, value in enumerate(journal_args):
        ensure_ascii(value, f"journal argument {index + 1}", command_safe=True)
    expected_project = [safe_relative(item, "expected output") for item in (args.expected or [])]
    expected_run = [safe_relative(item, "expected run file") for item in (args.expected_run_file or [])]
    if not expected_project and not expected_run:
        raise ValueError("At least one --expected or --expected-run-file is required")

    components = {
        "ugraf": component_record(profile["ugraf"], require_signature=True),
        "run_journal": component_record(profile["runner"], require_signature=True),
        "command_environment": component_record(profile["bootstrap"]),
        "manifest_schema": component_record(profile["manifest_schema"]),
    }

    plan = {
        "schema_version": "1.1",
        "run_id": run_id,
        "project": str(root),
        "nx_root": str(profile["nx_root"]),
        "journal": journal_relative.as_posix(),
        "journal_sha256": sha256_file(journal),
        "bootstrap": str(profile["bootstrap"]),
        "runner": str(profile["runner"]),
        "components": components,
        "staging": {
            "mode": "subst_project_root",
            "drive_letter": letter,
            "physical_target": str(root),
            "run_directory": run_relative.as_posix(),
            "persist_environment": False,
            "sets_ugii_root_dir": False,
        },
        "timeout_seconds": timeout_seconds,
        "expected": [item.as_posix() for item in expected_project],
        "expected_run_files": [item.as_posix() for item in expected_run],
        "journal_args": journal_args,
    }
    if args.dry_run:
        return {**plan, "dry_run": True}, 0

    for path in (run_dir / "tmp", run_dir / "user", run_dir / "work", run_dir / "output"):
        path.mkdir(parents=True, exist_ok=False)
    wrapper = run_dir / "launch.cmd"
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    report_path = run_dir / "nx-stage-run-report.json"
    atomic_write_text(wrapper, command_wrapper(profile, letter, journal_relative, run_relative, journal_args), encoding="ascii")

    report: dict[str, Any] = {
        **plan,
        "started_at": utc_now(),
        "finished_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "timed_out": False,
        "success": False,
        "mapping_removed": False,
        "logs": {
            "stdout": stdout_path.relative_to(root).as_posix(),
            "stderr": stderr_path.relative_to(root).as_posix(),
            "wrapper": wrapper.relative_to(root).as_posix(),
        },
    }
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    try:
        map_drive(letter, root)
        mapped_wrapper = mapped_path(letter, wrapper.relative_to(root))
        mapped_work = mapped_path(letter, (run_dir / "work").relative_to(root))
        child_env = os.environ.copy()
        child_env.pop("UGII_ROOT_DIR", None)
        with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                [os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/s", "/c", str(mapped_wrapper)],
                cwd=str(mapped_work),
                env=child_env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                report["exit_code"] = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                report["timed_out"] = True
                terminate_tree(process)
                report["exit_code"] = process.returncode
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error"] = str(exc)
    finally:
        # Always perform owner-aware cleanup.  unmap_drive refuses to delete a
        # mapping whose target is not this project, so this also covers a
        # mapping that becomes visible just after map_drive's verification.
        report["mapping_removed"] = unmap_drive(letter, root)
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["finished_at"] = utc_now()

    expected_records = [file_record(root / item, root) for item in expected_project]
    expected_records.extend(file_record(run_dir / item, root) for item in expected_run)
    report["expected_files"] = expected_records
    report["system_logs"] = [
        file_record(path, root)
        for path in sorted(run_dir.rglob("*.syslog"), key=lambda item: str(item).casefold())
        if path.is_file() and not path.is_symlink()
    ]
    report["logs_detail"] = {
        "stdout": file_record(stdout_path, root),
        "stderr": file_record(stderr_path, root),
        "wrapper": file_record(wrapper, root),
    }
    report["success"] = bool(
        report.get("exit_code") == 0
        and not report.get("timed_out")
        and not report.get("error")
        and report.get("mapping_removed")
        and all(item["exists"] and (item["size"] or 0) > 0 for item in expected_records)
    )
    atomic_write_json(report_path, report)
    return report, 0 if report["success"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a project-local NX journal through an ASCII subst staging path")
    parser.add_argument("--project", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--nx-root")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--drive-letter")
    parser.add_argument("--run-id")
    parser.add_argument("--journal-arg", action="append", default=[])
    parser.add_argument("--expected", action="append", default=[], help="Expected project-relative output; may be repeated")
    parser.add_argument("--expected-run-file", action="append", default=[], help="Expected file relative to this run directory; may be repeated")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    try:
        report, code = execute(build_parser().parse_args())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
