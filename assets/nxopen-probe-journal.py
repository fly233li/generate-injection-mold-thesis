# -*- coding: utf-8 -*-
"""Machine-readable NXOpen runtime probe; run only through nx_stage_run.py."""

from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import NXOpen


def main() -> None:
    run_dir = os.environ.get("THESIS_NX_RUN_DIR", "")
    if not run_dir:
        raise RuntimeError("THESIS_NX_RUN_DIR is required; use nx_stage_run.py")
    output = Path(run_dir) / "nxopen-probe-result.json"
    session = NXOpen.Session.GetSession()
    namespaces = {}
    for name in ("NXOpen.Features", "NXOpen.Drawings", "NXOpen.Drafting"):
        try:
            importlib.import_module(name)
            namespaces[name] = "ok"
        except Exception as exc:
            namespaces[name] = f"{type(exc).__name__}: {exc}"
    result = {
        "schema_version": "1.0",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "journal": Path(__file__).name,
        "python_version": sys.version,
        "nx_full_version": session.GetEnvironmentVariableValue("NX_FULL_VERSION"),
        "nxopen_imported": True,
        "session_acquired": True,
        "namespace_imports": namespaces,
        "work_part_open": session.Parts.Work is not None,
        "system_log": session.LogFile.FileName,
        "scope": "runtime_and_namespace_import_only",
        "limitations": [
            "Does not verify Modeling, Drafting, Mold Wizard, or production output.",
            "Does not promote any CAD artifact status.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    session.LogFile.WriteLine("THESIS_NXOPEN_PROBE_RESULT=" + str(output))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
