from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from cad_probe import probe as static_probe
from cad_probe import update_project
from common import atomic_write_json, utc_now


TOOLS = ("runstudy.exe", "studymod.exe", "studyrlt.exe")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_cli_bins(roots: list[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in roots:
        root = Path(raw).expanduser()
        if not root.exists():
            continue
        candidates = [root / "bin", root]
        candidates.extend(path.parent for path in root.glob("**/runstudy.exe"))
        for candidate in candidates:
            try:
                candidate = candidate.resolve()
            except OSError:
                continue
            if all((candidate / tool).is_file() for tool in TOOLS):
                found.add(candidate)
    return sorted(found, key=lambda item: str(item).casefold())


def help_probe(executable: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(executable), "-help"], text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30, check=False,
    )
    output = completed.stdout or ""
    expected = {
        "runstudy.exe": "Command line launching of Moldflow analyses",
        "studymod.exe": "Study Modification Utility",
        "studyrlt.exe": "Result Extraction Utility",
    }[executable.name.casefold()]
    return {
        "path": str(executable),
        "sha256": sha256(executable),
        "exit_code": completed.returncode,
        "help_recognized": expected.casefold() in output.casefold(),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "output_excerpt": output[:1000],
    }


def build_result(roots: list[str], verify_cli: bool, config: str | None) -> dict[str, Any]:
    result = static_probe([], roots, config, include_standard=True)
    bins = find_cli_bins(roots or [str(item) for item in result.get("configured_roots", {}).get("moldflow", [])])
    moldflow = result["moldflow"]
    moldflow["selected_root"] = str(bins[0].parent) if bins else ""
    moldflow["cli_bin"] = str(bins[0]) if bins else ""
    for tool in TOOLS:
        moldflow[f"{tool[:-4]}_candidate"] = str(bins[0] / tool) if bins else ""
    moldflow["runtime_status"] = "not_run"
    moldflow["help_probe"] = []
    if bins:
        moldflow["backend"] = "cli_candidate_unverified"
    if verify_cli and bins:
        records = [help_probe(bins[0] / tool) for tool in TOOLS]
        moldflow["help_probe"] = records
        if all(record["help_recognized"] for record in records):
            moldflow["runtime_status"] = "cli_help_verified"
            moldflow["backend"] = "cli_help_verified"
    result["schema_version"] = "2.3"
    result["probe_mode"] = "filesystem_metadata_and_optional_cli_help"
    result["probed_at"] = utc_now()
    result["disclaimer"] = (
        "CLI help verification proves only the command entry points. It does not prove a Moldflow "
        "license, a valid .sdy study, a solver run, convergence, or usable simulation results."
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Moldflow CLI entry points without solving a study")
    parser.add_argument("--project")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument("--moldflow-root", action="append", default=[])
    parser.add_argument("--config")
    parser.add_argument("--verify-cli", action="store_true", help="Run each utility with -help only; no study is solved")
    args = parser.parse_args()
    try:
        result = build_result(args.moldflow_root, args.verify_cli, args.config)
        if args.project:
            update_project(args.project, result)
        if args.json_path:
            atomic_write_json(Path(args.json_path).expanduser().resolve(), result)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
