---
name: generate-injection-mold-thesis
description: Design traceable undergraduate injection-mold course-design and thesis packages from a topic or supplied part data. Use for 注塑模具设计、毕业论文或课程设计 requiring original plastic-part definition, material/process analysis, mold structure, engineering calculations, UG/NX models or drawings, Moldflow plans or executed studies, verified CNKI/primary literature, Word cross-references, and final consistency auditing.
---

# Generate Injection Mold Thesis

Build the engineering project first and use the thesis to explain its frozen evidence. Never let fluent prose substitute for a part definition, calculation, drawing, source, execution log, or user approval.

## Establish the execution root

Require Python 3.10 or newer. Resolve `<skill-root>` as the directory containing this `SKILL.md`. Invoke every bundled script by its quoted absolute path; never assume the current working directory contains `scripts/`. Quote every project/file path.

Resolve one working interpreter before starting. On Windows, query the launcher and installed Python paths, then use the quoted absolute `python.exe` path for every command. Do not assume `py` or `python` remains on `PATH` after changing directories.

## Enforce the truth boundary

1. Classify supplied, registered part evidence as `REAL-PART`; classify a title-only original teaching design as `EDU-CONCEPT`.
2. For `EDU-CONCEPT`, disclose that dimensions, geometry, batch assumptions, and targets are confirmed teaching inputs—not measured product or enterprise data.
3. Tag origins as `USR`, `SRC`, `DEC`, `ASM`, `CALC`, `CAD`, `SIM`, or `OBS`. Register values before calculations, drawings, or prose.
4. Treat software detection only as a candidate. Claim `CAD` values only after a real NX run, native/neutral files, log, checksums, open verification, and measured properties. Claim `SIM` values only after a successful Moldflow solve, native study, log, cases, results, and checksums.
5. Use `prepared_unexecuted` when a backend or license is unavailable. Produce a complete plan, but no invented plots, numbers, comparisons, or “optimization” claims.
6. Bind every external claim to verified metadata and an exact locator. A plausible bibliography entry or search snippet is not sufficient evidence.
7. Use real Word `TOC`, `SEQ`, `REF`/`PAGEREF`, and citation fields. Typed numbers do not satisfy release.
8. Stop at every Gate until the user explicitly confirms. Never generate approval evidence on the user's behalf.
9. Reopen the earliest affected Gate after a frozen input changes; regenerate all downstream artifacts.

For a title-only project, include this notice in the design basis and drawings:

> 由于未提供企业任务书、实物测绘资料及既有三维模型，本项目将研究对象定义为面向本科课程设计的原创概念塑件。几何尺寸、生产批量和性能目标属于经确认的设计输入，不代表现有商品的实测参数或企业数据。成果用于教学设计，未经实物试制、模具调试及专业审核不得直接用于生产。

## Initialize safely

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\init_project.py" --title "<论文题目>" --root "<output-parent>" --mode from-zero --cad nx --cae moldflow
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\cad_probe.py" --project "<created-project>" --nx-root "E:\UG2406\NX"
```

Initialization is deliberately incomplete: the template must fail G1 until a real design-basis packet, requirements, and assumptions exist.

On this machine, treat `E:\UG2406\NX` as the preferred NX root. Read [references/local-nx-portable.md](references/local-nx-portable.md) before any NX work. Static detection proves files only; keep runtime and feature scope unverified until a separately approved journal test succeeds.

Run every project NX journal through the project-local ASCII staging adapter; do not call `run_journal.exe`, `CH_NX.BAT`, or the unsigned `SiemensNX` wrappers directly:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\nx_stage_run.py" --project "<project>" --journal "<project>\04_cad\nx\journals\nxopen-probe-journal.py" --expected-run-file "nxopen-probe-result.json"
```

Tell the user before a run because NX may start and check out a license. The adapter temporarily maps the project root to an unused ASCII drive letter, calls Siemens `UGII\ugiicmd.bat`, uses only child-process environment variables, captures logs, component hashes, and Authenticode evidence, then removes only the mapping it owns. For Modeling, Drafting, PDF, native-save, and reopen validation, run the template `nx-capability-probe-journal.py` and require its result, PRT, and PDF as expected run files. Register a successful report with `scripts/nx_register_validation.py`; the registrar requires the canonical skill journal, valid Siemens signatures, current hashes, clean logs, native/PDF headers, and nondecreasing capability status. It records only the tested software capability and never promotes the thesis model automatically.

Use guarded ledger registration. In PowerShell, write one UTF-8 JSON record file and pass `--record`; do not use inline `--data` JSON because shell quoting can corrupt it:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\register_record.py" --project "<project>" --kind requirement --record "<record.json>"
```

Use `--replace-if-revision <current>` only for an intentional revision. The tool preserves prior versions in ledger history.

Read [references/project-schema.md](references/project-schema.md) before writing structured records.

## Follow the gated workflow

### 1. Intake and concept packet

Parse the title, define the part boundary, identify safety-sensitive use, and list missing inputs. Develop 2–3 original plastic-part concepts. Recommend one with reasons. Draft the three-level thesis outline and required calculations, drawings, studies, and sources.

For title-only work, read [references/zero-based-part-definition.md](references/zero-based-part-definition.md) and [references/workflow-and-gates.md](references/workflow-and-gates.md).

### 2. G1 — design basis and outline

Freeze classification, part boundary, functions, environment, interfaces, selected concept, finite envelope, wall/draft/feature strategy, material candidates, production basis, targets, constraints, requirements, K3 assumptions, deliverables, and outline.

Present this packet to the user. After an explicit confirmation, save the exact confirmation text in `<project>/approvals/G1-*.md` and run:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\project_state.py" approve "<project>" G1 --note "设计基线已确认" --evidence "<project>\approvals\G1-confirmation.md"
```

Do not begin committed geometry or a final mold scheme before G1 approval.

### 3. Evidence plan and literature

Map each requirement to chapter, calculation, drawing, Moldflow case, and acceptance evidence. Search CNKI for Chinese academic literature and use official standards, publishers, DOI/Crossref records, manufacturers, Siemens, and Autodesk as primary verification sources. Record search attempts, rejected candidates, access level, exact locator, claim IDs, and saved evidence hashes.

Read [references/literature-verification.md](references/literature-verification.md).

### 4. Mold schemes and G2

Compare at least two complete combinations of material, cavity count/layout, parting, gating, venting, side action, ejection, cooling, mold base, and injection machine. Record alternatives, evidence, impacts, sensitivities, and rejection reasons. After user approval, save its evidence and approve G2.

Read [references/mold-engineering.md](references/mold-engineering.md).

### 5. Engineering and G3

Create confirmed parameter and calculation baselines. Cover part mass, cavity count, injection capacity, clamp force, cooling, ejection, and project-specific checks. Record formula applicability, substitution, acceptance, margin, and independent check.

Create the original part, mold assembly, part/assembly drawings, and BOM. Use [references/ug-nx-workflow.md](references/ug-nx-workflow.md) and the local portable-NX constraints in [references/local-nx-portable.md](references/local-nx-portable.md). Prepare or execute Moldflow according to [references/moldflow-integrity.md](references/moldflow-integrity.md). Keep model, drawing, BOM, CAE, and parameter revisions aligned.

Run:

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\engineering_audit.py" --project "<project>"
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\audit_project.py" --project "<project>" --gate G3
```

Present the artifacts and limitations. Save the user's explicit approval evidence, then approve G3.

### 6. Placement, manuscript, and G4

Build the placement matrix before prose. Introduce each figure/table/equation, insert it near its first substantive claim, and analyze its effect afterward. Write the body from frozen engineering evidence; write abstracts and conclusions last. Use the complete chapter logic in [references/thesis-architecture.md](references/thesis-architecture.md).

Generate a substantive DOCX/PDF. Refresh Word fields, inspect the PDF visually, populate the structured release manifest with canonical files and SHA-256 values, and list every unexecuted item. Read [references/docx-cross-references.md](references/docx-cross-references.md) and [references/quality-and-release.md](references/quality-and-release.md).

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\docx_audit.py" "<final.docx>"
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\audit_project.py" --project "<project>" --gate G4
```

Only after both pass and the user confirms the release packet may G4 be approved with saved evidence.

## Check state and handle changes

```powershell
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\project_state.py" status "<project>"
& "<python-executable>" -B -X utf8 "<skill-root>\scripts\project_state.py" reopen "<project>" G2 --note "方案输入变更"
```

Treat any `stale`, `blocker`, hash mismatch, broken field, unresolved ID, unconfirmed parameter, unexecuted software claim, or missing approval evidence as a stop condition. Correct the originating record or artifact, regenerate dependents, and rerun the audits.
