from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from common import atomic_write_bytes, atomic_write_json, project_dir, read_json, utc_now
from project_state import _project_lock


NX_FILES = {"ugraf.exe", "run_journal.exe", "nxopen.dll", "nxopen.uf.dll", "nxopen.pyd"}
MF_FILES = {"synergy.exe", "studymod.exe", "runstudy.exe", "studyrlt.exe"}
MAX_SCAN_DIRS = 50_000
MAX_SCAN_SECONDS = 20.0
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "assets" / "local-software-paths.json"
NX_SENTINELS = {
    "ugraf": "NXBIN/ugraf.exe",
    "run_journal": "NXBIN/run_journal.exe",
    "nxopen_python": "NXBIN/python/NXOpen.pyd",
    "nxopen_dotnet": "NXBIN/managed/NXOpen.dll",
    "nxopen_uf_dotnet": "NXBIN/managed/NXOpen.UF.dll",
    "environment": "UGII/ugii_env_ug.dat",
    "command_environment": "UGII/ugiicmd.bat",
    "manifest_schema": "UGII/manifest/platform/configuration.xsd",
}
NX_CAPABILITY_FILES = {
    "features": "NXBIN/python/NXOpen_Features.pyd",
    "assemblies": "NXBIN/python/NXOpen_Assemblies.pyd",
    "drawings": "NXBIN/python/NXOpen_Drawings.pyd",
    "drafting": "NXBIN/python/NXOpen_Drafting.pyd",
    "tooling": "NXBIN/python/NXOpen_Tooling.pyd",
    "plastic_designer": "NXBIN/python/NXOpen_PlasticDesigner.pyd",
    "mold_cooling": "NXBIN/python/NXOpen_MoldCooling.pyd",
    "mold_wizard_assets": "MOLDWIZARD",
    "plastic_designer_assets": "PLASTIC_DESIGNER",
}


def fixed_drives() -> list[Path]:
    if os.name != "nt":
        return [Path("/")]
    return [Path(f"{letter}:\\") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]


def standard_candidate_roots() -> list[Path]:
    roots: set[Path] = set()
    for name in ("UGII_BASE_DIR", "UGII_ROOT_DIR"):
        value = os.environ.get(name)
        if value:
            path = Path(value)
            if path.name.casefold() in {"nxbin", "ugii"}:
                path = path.parent
            roots.add(path)
    for drive in fixed_drives():
        for relative in ("Program Files/Siemens", "Program Files (x86)/Siemens", "Siemens", "Program Files/Autodesk", "Program Files (x86)/Autodesk", "Autodesk"):
            path = drive / relative
            if path.exists():
                roots.add(path)
    return sorted(path.resolve() for path in roots if path.exists())


def bounded_find(roots: list[Path], wanted: set[str], max_depth: int = 6) -> tuple[dict[str, list[str]], bool]:
    found: dict[str, list[str]] = {name: [] for name in sorted(wanted)}
    started = time.monotonic(); scanned = 0; truncated = False
    for root in roots:
        base_depth = len(root.parts)
        for current, dirs, files in os.walk(root, onerror=lambda _err: None):
            scanned += 1
            if scanned >= MAX_SCAN_DIRS or time.monotonic() - started >= MAX_SCAN_SECONDS:
                dirs[:] = []; truncated = True; break
            depth = len(Path(current).parts) - base_depth
            if depth >= max_depth:
                dirs[:] = []
            dirs[:] = [item for item in dirs if item.lower() not in {"node_modules", "samples", "help", "documentation", "communicator"}]
            lower = {name.lower(): name for name in files}
            for target in wanted:
                if target in lower:
                    found[target].append(str((Path(current) / lower[target]).resolve()))
        if truncated:
            break
    return ({key: sorted(set(paths)) for key, paths in found.items()}, truncated)


def registry_products() -> list[dict[str, str]]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    products: list[dict[str, str]] = []
    key_paths = (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")
    accepted = re.compile(r"(siemens\s+nx|unigraphics|moldflow\s+(insight|adviser|synergy))", re.I)
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_path in key_paths:
            try:
                with winreg.OpenKey(hive, key_path) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            with winreg.OpenKey(root, winreg.EnumKey(root, index)) as sub:
                                name = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                                if not accepted.search(name) or "communicator" in name.lower():
                                    continue
                                def optional(field: str) -> str:
                                    try: return str(winreg.QueryValueEx(sub, field)[0])
                                    except OSError: return ""
                                products.append({"name": name, "version": optional("DisplayVersion"), "location": optional("InstallLocation")})
                        except OSError:
                            continue
            except OSError:
                continue
    unique = {(item["name"], item["version"], item["location"]): item for item in products}
    return sorted(unique.values(), key=lambda item: item["name"].lower())


def com_registered(prog_id: str) -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id):
            return True
    except OSError:
        return False


def normalize_nx_root(raw: str | os.PathLike[str], *, strict: bool = True) -> Path | None:
    path = Path(raw).expanduser()
    try:
        path = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        if strict:
            raise FileNotFoundError(f"NX root does not exist: {path}")
        return None
    if path.is_file() and path.name.casefold() in {"ugraf.exe", "run_journal.exe"}:
        path = path.parent
    if path.name.casefold() in {"nxbin", "ugii"}:
        path = path.parent
    if not path.is_dir():
        if strict:
            raise ValueError(f"NX root is not a directory: {path}")
        return None
    if not (path / "NXBIN" / "ugraf.exe").is_file():
        if strict:
            raise ValueError(f"NX root lacks NXBIN\\ugraf.exe: {path}")
        return None
    return path.resolve()


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "dwSignature", "dwStrucVersion", "dwFileVersionMS", "dwFileVersionLS",
        "dwProductVersionMS", "dwProductVersionLS", "dwFileFlagsMask", "dwFileFlags",
        "dwFileOS", "dwFileType", "dwFileSubtype", "dwFileDateMS", "dwFileDateLS",
    )]


def windows_file_version(path: Path) -> str:
    if os.name != "nt" or not path.is_file():
        return ""
    try:
        version = ctypes.windll.version
        size = version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
            return ""
        pointer = ctypes.c_void_p(); length = ctypes.c_uint()
        if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return ""
        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        parts = (info.dwFileVersionMS >> 16, info.dwFileVersionMS & 0xFFFF, info.dwFileVersionLS >> 16, info.dwFileVersionLS & 0xFFFF)
        while len(parts) > 2 and parts[-1] == 0:
            parts = parts[:-1]
        return ".".join(str(part) for part in parts)
    except Exception:
        return ""


def inspect_nx_root(root: Path, source: str) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    for name, relative in NX_SENTINELS.items():
        path = root / Path(relative)
        checks[name] = {"path": str(path), "exists": path.is_file(), "size": path.stat().st_size if path.is_file() else None}
    capabilities = {name: (root / Path(relative)).exists() for name, relative in NX_CAPABILITY_FILES.items()}
    ugraf = root / "NXBIN" / "ugraf.exe"
    complete = all(check["exists"] for check in checks.values())
    return {
        "root": str(root), "source": source, "valid_layout": checks["ugraf"]["exists"],
        "automation_layout_complete": complete, "version_candidate": windows_file_version(ugraf),
        "checks": checks, "capabilities": capabilities,
    }


def load_local_config(config_path: str | os.PathLike[str] | None) -> tuple[Path | None, dict[str, Any]]:
    path = Path(config_path).expanduser().resolve() if config_path else DEFAULT_CONFIG
    if not path.is_file():
        return None, {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError(f"Software-path config must be a JSON object: {path}")
    return path, data


def add_file(files: dict[str, list[str]], key: str, path: Path) -> None:
    if path.is_file():
        files.setdefault(key, []).append(str(path.resolve()))
        files[key] = sorted(set(files[key]))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_evidence_file(root: Path, raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        path = (root / Path(raw)).resolve(strict=True)
        path.relative_to(root.resolve())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return path if path.is_file() and not path.is_symlink() else None


def _runtime_evidence_current(root: Path, previous_nx: dict[str, Any]) -> tuple[bool, str]:
    validation = previous_nx.get("runtime_validation")
    if not isinstance(validation, dict):
        return False, "registered runtime validation is missing"
    report_path = _project_evidence_file(root, validation.get("report"))
    if report_path is None:
        return False, "registered runtime report is missing"
    if validation.get("report_sha256") != sha256_file(report_path):
        return False, "registered runtime report changed"
    try:
        report = read_json(report_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False, "registered runtime report is unreadable"
    if not isinstance(report, dict) or report.get("schema_version") != "1.1":
        return False, "registered runtime report lacks schema 1.1 component evidence"
    if report.get("success") is not True or report.get("mapping_removed") is not True:
        return False, "registered runtime report is not a clean success"
    nx_root = Path(str(previous_nx.get("selected_root", "")))
    components = report.get("components") if isinstance(report.get("components"), dict) else {}
    expected_components = {
        "ugraf": nx_root / "NXBIN/ugraf.exe",
        "run_journal": nx_root / "NXBIN/run_journal.exe",
        "command_environment": nx_root / "UGII/ugiicmd.bat",
        "manifest_schema": nx_root / "UGII/manifest/platform/configuration.xsd",
    }
    for name, path in expected_components.items():
        record = components.get(name)
        if (
            not isinstance(record, dict)
            or not path.is_file()
            or path.is_symlink()
            or os.path.normcase(os.path.abspath(str(record.get("path", ""))))
            != os.path.normcase(os.path.abspath(str(path)))
            or record.get("size") != path.stat().st_size
            or record.get("sha256") != sha256_file(path)
        ):
            return False, f"registered runtime component changed: {name}"
    journal_path = _project_evidence_file(root, report.get("journal"))
    if journal_path is None or report.get("journal_sha256") != sha256_file(journal_path):
        return False, "registered runtime journal changed"
    expected_files = report.get("expected_files")
    if not isinstance(expected_files, list) or not expected_files:
        return False, "registered runtime report has no expected-file evidence"
    for record in expected_files:
        if not isinstance(record, dict):
            return False, "registered runtime expected-file evidence is invalid"
        path = _project_evidence_file(root, record.get("path"))
        if (
            path is None
            or record.get("exists") is not True
            or record.get("size") != path.stat().st_size
            or record.get("sha256") != sha256_file(path)
        ):
            return False, "registered runtime output changed"
    return True, ""


def moldflow_cli_sets(files: dict[str, list[str]]) -> list[str]:
    parents: list[str] = []
    for path in files.get("runstudy.exe", []):
        parent = Path(path).parent
        if all((parent / name).is_file() for name in ("studymod.exe", "runstudy.exe", "studyrlt.exe")):
            parents.append(str(parent.resolve()))
    return sorted(set(parents))


def probe(nx_roots: list[str] | None = None, moldflow_roots: list[str] | None = None, config_path: str | None = None, include_standard: bool = True) -> dict[str, object]:
    config_file, config = load_local_config(config_path)
    configured_nx = [str(item) for item in config.get("nx_roots", [])] if isinstance(config.get("nx_roots", []), list) else []
    configured_mf = [str(item) for item in config.get("moldflow_roots", [])] if isinstance(config.get("moldflow_roots", []), list) else []
    installations: list[dict[str, Any]] = []
    seen_roots: set[str] = set()
    invalid_configured: list[str] = []
    for raw, source, strict in [*((item, "explicit_root", True) for item in (nx_roots or [])), *((item, "local_config", False) for item in configured_nx)]:
        root = normalize_nx_root(raw, strict=strict)
        if root is None:
            invalid_configured.append(str(raw)); continue
        key = str(root).casefold()
        if key in seen_roots:
            continue
        seen_roots.add(key); installations.append(inspect_nx_root(root, source))

    explicit_mf: list[Path] = []
    for raw in [*(moldflow_roots or []), *configured_mf]:
        path = Path(raw).expanduser()
        if raw in (moldflow_roots or []):
            path = path.resolve(strict=True)
            if not path.is_dir(): raise ValueError(f"Moldflow root is not a directory: {path}")
        elif not path.exists():
            continue
        explicit_mf.append(path.resolve())

    scan_roots = [*explicit_mf, *(standard_candidate_roots() if include_standard else [])]
    files, truncated = bounded_find(scan_roots, NX_FILES | MF_FILES) if scan_roots else ({name: [] for name in sorted(NX_FILES | MF_FILES)}, False)
    for installation in installations:
        root = Path(installation["root"])
        add_file(files, "ugraf.exe", root / "NXBIN" / "ugraf.exe")
        add_file(files, "run_journal.exe", root / "NXBIN" / "run_journal.exe")
        add_file(files, "nxopen.pyd", root / "NXBIN" / "python" / "NXOpen.pyd")
        add_file(files, "nxopen.dll", root / "NXBIN" / "managed" / "NXOpen.dll")
        add_file(files, "nxopen.uf.dll", root / "NXBIN" / "managed" / "NXOpen.UF.dll")
    for name in sorted(NX_FILES | MF_FILES):
        found = shutil.which(name)
        if found:
            add_file(files, name, Path(found))

    products = registry_products(); cli_sets = moldflow_cli_sets(files)
    nx_product = any(re.search(r"siemens\s+nx|unigraphics", item["name"], re.I) for item in products)
    moldflow_product = any(re.search(r"moldflow\s+(insight|adviser|synergy)", item["name"], re.I) for item in products)
    selected = next((item for item in installations if item["valid_layout"]), None)
    nx_detected = bool(selected or files.get("ugraf.exe") or nx_product)
    mf_gui = bool(files.get("synergy.exe"))
    capabilities = [name for name, present in (selected or {}).get("capabilities", {}).items() if present]
    nx_output = {
        "detected": nx_detected,
        "selected_root": selected.get("root", "") if selected else "",
        "detection_source": selected.get("source", "filesystem_scan" if nx_detected else "none") if selected else ("filesystem_scan" if nx_detected else "none"),
        "version_candidate": selected.get("version_candidate", "") if selected else "",
        "gui": bool((selected or {}).get("checks", {}).get("ugraf", {}).get("exists") or files.get("ugraf.exe")),
        "gui_candidate": (selected or {}).get("checks", {}).get("ugraf", {}).get("path", ""),
        "run_journal_candidate": (selected or {}).get("checks", {}).get("run_journal", {}).get("path", "") or (files.get("run_journal.exe") or [""])[0],
        "embedded_nxopen_python_candidate": (selected or {}).get("checks", {}).get("nxopen_python", {}).get("path", ""),
        "nxopen_dotnet_candidate": (selected or {}).get("checks", {}).get("nxopen_dotnet", {}).get("path", ""),
        "nxopen_uf_dotnet_candidate": (selected or {}).get("checks", {}).get("nxopen_uf_dotnet", {}).get("path", ""),
        "command_environment_candidate": (selected or {}).get("checks", {}).get("command_environment", {}).get("path", ""),
        "manifest_schema_candidate": (selected or {}).get("checks", {}).get("manifest_schema", {}).get("path", ""),
        "nxopen_python_in_system_python": importlib.util.find_spec("NXOpen") is not None,
        "capability_files_detected": capabilities,
        "preferred_backend": "nxopen_python_run_journal" if selected and selected["automation_layout_complete"] else "candidate_unverified",
        "runtime_status": "not_run",
        "license_status": "unknown",
        "backend": "candidate_unverified" if nx_detected else "unavailable",
        "installations": installations,
    }
    return {
        "schema_version": "2.2", "probe_mode": "filesystem_metadata_only", "probed_at": utc_now(),
        "platform": platform.platform(), "config_file": str(config_file) if config_file else "",
        "configured_roots": {"nx": [*(nx_roots or []), *configured_nx], "moldflow": [*(moldflow_roots or []), *configured_mf]},
        "invalid_configured_roots": invalid_configured, "candidate_roots": [str(path) for path in scan_roots],
        "scan_truncated": truncated, "products": products, "files": files, "nx": nx_output,
        "moldflow": {
            "detected": mf_gui or bool(cli_sets) or moldflow_product, "synergy_gui": mf_gui,
            "legacy_com_registered": com_registered("synergy.Synergy"), "cli_sets": cli_sets,
            "python_api_in_system_python": importlib.util.find_spec("moldflow") is not None,
            "license_status": "unknown", "backend": "candidate_unverified" if mf_gui or cli_sets or moldflow_product else "unavailable",
        },
        "disclaimer": "Static file detection does not prove a valid license, NX runtime, Modeling, Drafting, Mold Wizard, or successful engineering operation. Run a separately approved NXOpen smoke test before promotion.",
    }


def _merge_previous_probe(root: Path, result: dict[str, Any]) -> None:
    """Preserve runtime evidence and superseded-root history across static probes."""
    path = root / "software-probe.json"
    if not path.is_file():
        return
    previous = read_json(path)
    if not isinstance(previous, dict):
        return
    previous_nx = previous.get("nx") if isinstance(previous.get("nx"), dict) else {}
    current_nx = result.get("nx") if isinstance(result.get("nx"), dict) else {}
    previous_root = str(previous_nx.get("selected_root", "")).casefold()
    current_root = str(current_nx.get("selected_root", "")).casefold()
    prior_history = previous.get("probe_history") if isinstance(previous.get("probe_history"), list) else []
    result["probe_history"] = list(prior_history)

    if previous_root and previous_root != current_root:
        historical = {key: value for key, value in previous.items() if key != "probe_history"}
        identity = (historical.get("probed_at"), previous_nx.get("selected_root"))
        existing = {
            (item.get("probed_at"), (item.get("nx") or {}).get("selected_root"))
            for item in result["probe_history"]
            if isinstance(item, dict) and isinstance(item.get("nx"), dict)
        }
        if identity not in existing:
            result["probe_history"].append(historical)
        return

    if previous_root and previous_root == current_root:
        evidence_current, stale_reason = _runtime_evidence_current(root, previous_nx)
        if previous_nx.get("runtime_status") not in {None, "", "not_run"} and not evidence_current:
            current_nx["runtime_evidence_stale"] = stale_reason
            return
        for key in (
            "runtime_status",
            "license_status",
            "backend",
            "runtime_attempts",
            "runtime_validation",
            "execution_profile",
        ):
            if key in previous_nx and (
                key not in {"runtime_status", "license_status", "backend"}
                or previous_nx.get("runtime_status") not in {None, "", "not_run"}
            ):
                current_nx[key] = previous_nx[key]


def update_project(project: str | os.PathLike[str], result: dict[str, Any]) -> Path:
    root = project_dir(project)
    with _project_lock(root):
        _merge_previous_probe(root, result)
        manifest = read_json(root / "project.json")
        software = manifest.setdefault("software", {})
        if not isinstance(software, dict):
            raise ValueError("project.json software must be an object")
        nx = result["nx"]; moldflow = result["moldflow"]
        software.update({
            "probe_status": "completed", "nx_backend": nx["backend"], "nx_license": nx["license_status"],
            "nx_root": nx["selected_root"], "nx_detection_source": nx["detection_source"],
            "nx_executable": nx["gui_candidate"], "nx_run_journal": nx["run_journal_candidate"],
            "nx_command_environment": nx["command_environment_candidate"],
            "nx_manifest_schema": nx["manifest_schema_candidate"],
            "nxopen_uf_dotnet": nx["nxopen_uf_dotnet_candidate"],
            "nx_version_candidate": nx["version_candidate"], "nx_runtime_status": nx["runtime_status"],
            "nx_preferred_backend": nx["preferred_backend"], "nx_capability_files": nx["capability_files_detected"],
            "moldflow_backend": moldflow["backend"], "moldflow_license": moldflow["license_status"],
        })
        manifest["updated_at"] = utc_now()
        probe_path = root / "software-probe.json"
        manifest_path = root / "project.json"
        backups = {
            probe_path: probe_path.read_bytes() if probe_path.is_file() else None,
            manifest_path: manifest_path.read_bytes(),
        }
        try:
            atomic_write_json(probe_path, result)
            atomic_write_json(manifest_path, manifest)
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
                    "Static software probe update failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                ) from exc
            raise
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description="Statically probe Siemens NX/UG and Autodesk Moldflow without starting them")
    parser.add_argument("--project"); parser.add_argument("--json", dest="json_path")
    parser.add_argument("--nx-root", action="append", default=[], help="Explicit NX install root; may be repeated")
    parser.add_argument("--moldflow-root", action="append", default=[], help="Explicit Moldflow install root; may be repeated")
    parser.add_argument("--config", help="Optional local software-path JSON; defaults to the skill asset")
    parser.add_argument("--no-standard-search", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        result = probe(args.nx_root, args.moldflow_root, args.config, not args.no_standard_search)
        if args.project:
            update_project(args.project, result)
        if args.json_path:
            atomic_write_json(Path(args.json_path).expanduser().resolve(), result)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
    print(json.dumps(result, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
