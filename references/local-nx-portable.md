# Local NX 2406

## Confirmed root and layout

Use `E:\UG2406\NX` as the executable root. Siemens-signed `NXBIN\ugraf.exe` and `NXBIN\run_journal.exe` report version `2406.1700`. The tree contains NXOpen Python/.NET/UF, `UGII\ugiicmd.bat`, `UGII\manifest\platform\configuration.xsd`, Drafting, Mold Wizard, Mold Cooling, Plastic Designer, and Siemens NXOpen samples.

Treat `E:\UG2406\SiemensNX` only as a collection of unsigned portable launch wrappers, not as an NX root. Do not use root `CH_NX.BAT`; it assigns `UGII_BASE_DIR` to the nonexistent nested path `E:\UG2406\NX\NX`.

Static files do not prove a usable runtime, license, or feature scope.

## Verified local behavior

On 2026-07-13, Siemens `run_journal.exe` acquired an NXOpen session and reported `v2406.0.0.1700`. A bounded capability journal then created a 40×30×20 mm solid, an A4 drawing sheet and base view, saved a native PRT, exported PDF, closed the part, reopened it, and verified one body, one sheet, and one drawing view.

Direct PDF conversion failed when NX used a Chinese project path for intermediate CGM files. The same test passed when the physical project stayed in place but was temporarily exposed through an ASCII `subst` drive. Therefore use the bundled staging adapter for every journal, even though the NX installation root is already ASCII.

The tested scope covers NXOpen runtime, basic solid modeling, Drafting sheet/base-view creation, native save/reopen, and PDF export. It does not prove Mold Wizard operations or the correctness of a thesis production model.

## Static probe

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\cad_probe.py" --project "<project>" --nx-root "E:\UG2406\NX"
```

The probe requires the executable/NXOpen layout, Siemens command environment, and manifest schema. It still records `candidate_unverified` until runtime evidence is separately registered. On later probes of the same root, a verified status is preserved only while its schema 1.1 report, component hashes, canonical journal, and expected outputs remain unchanged; otherwise it returns to `not_run` with a stale-evidence reason.

## Journal execution

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\nx_stage_run.py" --project "<project>" --journal "<project>\04_cad\nx\journals\nxopen-probe-journal.py" --expected-run-file "nxopen-probe-result.json"
```

After a successful run, register the machine-readable evidence explicitly:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\nx_register_validation.py" --project "<project>" --report "<project>\04_cad\nx\runtime\staging\<run-id>\nx-stage-run-report.json" --result "<project>\04_cad\nx\runtime\staging\<run-id>\nxopen-probe-result.json" --scope runtime
```

For the bounded Modeling/Drafting/PDF test, run `nx-capability-probe-journal.py` and pass all three expected files:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\nx_stage_run.py" --project "<project>" --journal "<project>\04_cad\nx\journals\nx-capability-probe-journal.py" --expected-run-file "capability/capability-result.json" --expected-run-file "capability/nx-capability-probe.prt" --expected-run-file "capability/nx-capability-probe.pdf"
```

Register that report with `--scope capability`. Schema 1.1 reports bind the run to the canonical skill journal; Siemens-signed `ugraf.exe` and `run_journal.exe`; current hashes for both executables, `ugiicmd.bat`, and `configuration.xsd`; the generated wrapper/stdout/stderr/syslogs; every expected file; and the reported result. Capability registration additionally checks the NX native-part signature, PDF header, saved sizes, and reopen counts. Registration is serialized with the project-state lock, restores prior files on a write failure, and never replaces a stronger current capability with a weaker later probe. It updates only operational software evidence; `04_cad/model-manifest.json` remains unchanged until the real thesis model passes its own acceptance criteria.

The adapter enforces these rules:

- Map only the thesis project root to an unused ASCII drive; all physical writes remain inside the project.
- Call Siemens `UGII\ugiicmd.bat <nx-root>` before `NXBIN\run_journal.exe`.
- Clear inherited `UGII_ROOT_DIR`; do not invent or persist it.
- Put NX user, temp, work, output, wrapper, stdout, stderr, report, and syslog paths under `04_cad/nx/runtime/staging/<run-id>`.
- Terminate only the launched process tree on timeout and always attempt to remove the mapping.
- Verify the mapping still targets this project before removal and retry bounded cleanup; never delete a mapping owned by another target.
- Require zero exit, expected nonempty files, hashes, and native reopen/measurement evidence before CAD promotion.
- Keep diagnostic outputs separate from production artifacts; diagnostics never make `M01-PREP` executed.

Do not import `NXOpen.pyd` with system Python and do not use auxiliary PyPy executables under `MACH`.
