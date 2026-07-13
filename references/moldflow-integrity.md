# Moldflow workflow and result integrity

Probe Autodesk Moldflow Insight, Synergy, Adviser, automation utilities, solver access, and license independently. An installed GUI, Communicator, or API does not prove that a solver license is available.

## Detect capabilities

Search versioned Autodesk roots for Synergy/Insight/Adviser and locate, when present:

- `synergy.exe`;
- `studymod.exe`;
- `runstudy.exe`;
- `studyrlt.exe`;
- command definitions and result/unit data files.

Check the `synergy.Synergy` COM registration for legacy automation and test the current product environment for the Moldflow Python API. Moldflow 2026 documents `from moldflow import Synergy` and requires the separately installed API; do not infer compatibility from the system Python version. See Autodesk's [script execution guidance](https://help.autodesk.com/cloudhelp/2026/ENU/MoldflowInsight-CLC-Automation/files/synergy-application-program/command-line/MFLO_RUNNING_A_MACRO_OR_SCRIPT_FROM_WINDOWS_EXPLORER_CLI.html).

Insight command automation can use `studymod` to modify a study, `runstudy` to solve, and `studyrlt` to extract results; verify the detected release's help and a minimal test before use. See the [official command-line automation overview](https://help.autodesk.com/cloudhelp/2026/ENU/MoldflowInsight-CLC-Automation/files/MOLDFLOW-COMMAND-LINE-CONCEPT.html).

Named-user `runstudy` can require a session key. Treat keys as credentials: never store them in the project, logs, manuscript, or release package. See the [official runstudy guidance](https://help.autodesk.com/cloudhelp/2025/ENU/MoldflowInsight-CLC-Automation/files/cmd-line-control/MFLO_AUTOMN_RNSDY_UTLTY_CPT.html).

Do not assume Adviser exposes the same automation as Insight. Use a manual GUI adapter unless the actual installation and test prove otherwise. Communicator can review a result package but is not a solver.

## Exchange geometry safely

Retain the native NX file and export a compatible Parasolid or STEP copy. Moldflow 2026 supports defined NX, Parasolid, STEP, UDM, STL, and JT versions; verify release compatibility using Autodesk's [supported import formats](https://help.autodesk.com/cloudhelp/2026/ENU/MoldflowInsight-CLC-NewUser/files/Import-and-Export/GUID-D63BA077-3570-42B4-8464-A8C1E91D66FE.html).

If the NX release is newer than the supported native importer, use a supported Parasolid or STEP version and verify body count, units, bounding box, and volume after import. Import a single part cavity unless the format/workflow explicitly supports more; create multi-cavity instances and runners deliberately in the study rather than importing a complete mold assembly as the plastic part.

## Define the study before solving

Record:

- case ID and purpose;
- geometry file, revision, and hash;
- exact material grade and Moldflow database/card identity;
- mesh type, target size, element count, and quality metrics;
- cavity instances, runner, gate, vent, cooling, inserts, and mold materials;
- machine and process settings with sources;
- analysis sequence, solver version, and controlled comparison variables;
- expected result IDs and acceptance criteria.

Choose analyses because they answer a design question: gate-location screening, fill/pack, cooling, or warpage. Do not run every analysis merely to create screenshots.

## Validate executed results

An executed case needs:

- input study/project files and hashes;
- complete solver log and successful completion state;
- no unresolved license, convergence, termination, or missing-result error;
- expected native result files;
- successful `studyrlt` or equivalent extraction of key values and units;
- images tied to case ID, result name, scale/range, unit, view, and geometry revision.

Preserve applicable `.mpi`, `.sdy`, `.udm`, `.mfr`, `.out`, result files, extracted XML/text/CSV, and images. Do not judge completion from one legacy file extension because result packaging changes by release. See the [Moldflow 2026 result compatibility notes](https://help.autodesk.com/cloudhelp/2026/ENU/MoldflowInsight-CLC-WhatsNew/files/MFLO-WHATS-NEW-2026-0.html).

When geometry, material, mesh, runner/gate, cooling, machine, or process settings change, mark affected cases stale and rerun them.

## Degrade honestly

If no usable solver exists, produce a geometry-exchange plan, material-selection requirement, mesh plan, case matrix, settings/source table, result checklist, and executable templates where supported. Set status `prepared_unexecuted`. Do not fabricate mesh counts, fill time, pressure, clamp force, weld lines, air traps, temperature, shrinkage, warpage, plots, software version, or “improved by x%” conclusions.
