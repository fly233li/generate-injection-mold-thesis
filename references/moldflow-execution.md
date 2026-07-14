# Moldflow 2024 execution and thesis integration

Use this workflow only after G2 approval and after the case matrix, geometry revision, material grade/card, mesh plan, process settings, and acceptance criteria have been registered.

## 1. Probe before opening a study

Run `scripts/moldflow_probe.py` with `--verify-cli`. It is a help-only probe: it verifies the exact `runstudy`, `studymod`, and `studyrlt` binaries and records their hashes and outputs. It does not claim a license or a solve.

On this workstation, the verified candidates are:

- Insight CLI: `D:\autodesk02\Moldflow Insight 2024\bin`;
- Synergy UI: `D:\autodesk02\Moldflow Synergy 2024\bin\synergy.exe`;
- build: Moldflow Insight 2024, `47.0.56`.

## 2. Build each study in Synergy

Create one folder per case under `05_cae\MF01\cases\<CASE-ID>`. Import only the plastic-part geometry; preserve the imported STEP/Parasolid file and its hash. In Synergy, select the exact material-card identity, create the mesh, set the gate/runner/cooling variation, define the analysis sequence, and save the native `.sdy` study in that case folder.

Record actual mesh statistics, quality criteria, material card ID, process settings and result requests in `05_cae/moldflow-study.json` before committing any result. Never use a material name as a substitute for the database/card ID.

## 3. Execute and extract

Tell the user before an execution because `runstudy` may consume a named-user or network license and create result files. Run `moldflow_run.py --execute` only with a saved local `.sdy`; it writes an immutable run record and invokes `studyrlt -exportoutput` in METRIC units after a zero exit code. A session-key file may be passed with `--session-key-file`; the script sends the file path to `runstudy` but never copies or records its contents.

Keep the `.sdy`, solver output, complete run log, extracted text, native result files and `case-result.json`. Result images must be exported from the executed study and carry the case ID, result name, unit, visible scale/range, view and geometry revision in their caption or adjacent table.

## 4. Promote results only after validation

Use `moldflow_run.py --commit` only after a zero-exit `runstudy` and a successful `studyrlt` export are present. The command refuses to promote when material, geometry revision, mesh metrics, native study, solver log, or extracted output are absent. It stores SHA-256 values for every recorded result file.

Do not use a PNG, `.out`, or a successful process exit by itself as proof of a valid result. Inspect solver output for licensing, termination and convergence errors and verify that the expected result is present for the intended case.

## 5. Place actual results in the thesis

For each executed case, register measured values as `SIM` parameters with `source_ref` containing the case ID. Add the following objects to `01_outline/evidence-placement.csv` before prose:

- a settings/mesh table immediately after the first description of the study;
- a result-comparison table after the first comparison claim;
- one figure per analysed result (fill time, pressure, weld line/air trap, temperature, shrinkage or warpage) immediately after the claim it supports.

In the body, introduce the case and controlled variable, place the table/figure, then discuss the numerical result and decision. State the result unit and whether lower/higher is favourable. Do not write “optimized”, “improved”, “Moldflow results show”, or percentage improvements unless the committed case record and its extracted value support the exact statement.

After integration, regenerate the DOCX/PDF, refresh Word fields, perform the PDF visual review, refresh the release manifest, and rerun G3/G4. Add `moldflow_study`, `moldflow_log`, `moldflow_extract` and each cited plot to the release manifest with SHA-256 hashes.
