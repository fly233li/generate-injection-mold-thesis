# Project schema

All project text is UTF-8. CSV files use a BOM for Excel compatibility. Stable IDs never change; revisions are positive integers. Use `scripts/register_record.py` instead of editing active ledger rows when practical.

## Directory tree

```text
<project>/
├─ project.json
├─ software-probe.json
├─ approvals/
├─ 00_requirements/
│  ├─ brief.md
│  ├─ design-basis.json
│  ├─ requirements.csv
│  ├─ assumptions.csv
│  └─ changes.csv
├─ 01_outline/
│  ├─ outline.md
│  └─ evidence-placement.csv
├─ 02_sources/
│  ├─ references.csv
│  ├─ claims.csv
│  ├─ evidence-manifest.csv
│  ├─ search-log.csv
│  └─ evidence/
├─ 03_engineering/
│  ├─ parameters.csv
│  ├─ calculations.json
│  ├─ decisions.csv
│  └─ schemes.json
├─ 04_cad/
│  ├─ model-manifest.json
│  ├─ drawings.csv
│  ├─ bom.csv
│  ├─ nx/model-plan.json
│  ├─ nx/nx-runtime-config.json
│  ├─ nx/runtime/validation-history.jsonl
│  ├─ nx/journals/
│  ├─ exports/
│  └─ drawings/
├─ 05_cae/
│  ├─ moldflow-study.json
│  └─ results/
├─ 06_manuscript/
│  ├─ chapter-plan.json
│  ├─ manuscript.md
│  └─ figures/
├─ 07_audit/
│  ├─ issues.json
│  ├─ audit-report.md
│  └─ pdf-visual-review.json
└─ deliverables/
   ├─ release-manifest.json
   ├─ release-manifest.md
   └─ files/
```

## Core ledgers

- Requirements: `req_id,category,requirement,origin,priority,acceptance,chapter_id,calc_ids,drawing_ids,case_ids,verification,status,revision,supersedes`
- Assumptions: `assumption_id,statement,value,unit,criticality,basis_source_id,uncertainty_or_range,status,approval_gate,affected_items,validation_method,revision,supersedes`
- Parameters: `param_id,name,symbol,value,unit,quantity,origin_type,source_ref,status,assumption_id,nx_expression,used_in,revision`
- Decisions: `decision_id,category,question,alternatives,selected_option,rationale,evidence_ids,impact,status,revision`
- Sources: `source_id,...,exact_locator,claim_ids,status,...,citation_key,used_in,revision`
- Claims: `claim_id,claim_text,claim_type,source_ids,exact_locator,section_id,status,revision`
- Placements: `object_id,object_type,title_or_caption,section_id,first_mention_claim_id,insertion_position,purpose,source_or_artifact_id,file,word_bookmark_or_field,status,revision`
- Drawings: `drawing_id,title,drawing_type,file,model_revision,requirement_ids,status,checked_by,revision,notes`
- BOM: `item_id,item_no,part_name,quantity,material,standard_or_drawing_id,model_revision,status,revision,notes`

List-valued CSV cells use a JSON array or semicolon-separated IDs.

## Controlled enums

- Project classification: `REAL-PART`, `EDU-CONCEPT`.
- Origin: `USR`, `SRC`, `DEC`, `ASM`, `CALC`, `CAD`, `SIM`, `OBS`.
- Artifact status: `planned`, `prepared_unexecuted`, `executed`, `verified`, `stale`, `rejected`.
- Required decision categories: `material`, `cavity_count`, `parting_surface`, `gate`, `venting`, `side_action`, `ejection`, `cooling`, `mold_base`, `injection_machine`.
- Required calculation categories: `part_mass`, `cavity_count`, `injection_capacity`, `clamp_force`, `cooling`, `ejection`.
- Drawing types required at G3: `part`, `assembly`.

## Calculation record

Each confirmed/verified calculation contains `id`, `category`, `name`, `expression`, `result_value`, `result_unit`, `formula_source`, `applicability`, `input_ids`, `substitution`, `acceptance`, `margin`, `independent_check`, `tolerance`, `used_in`, `revision`, and `status`. Expressions reference confirmed parameter IDs only.

## File manifests

Every executed CAD/CAE/release file entry is an object:

```json
{"path":"relative/path.ext","role":"nx_native","status":"verified","sha256":"64 lowercase hex digits"}
```

Paths remain inside the project and cannot be links. `executed` requires a successful execution record and log; `verified` additionally requires opening/inspection. `prepared_unexecuted` contains plans but no software-derived values.

`project.json.software`, `software-probe.json`, and `04_cad/nx/nx-runtime-config.json` describe the current environment. Snapshot schema v3 keeps the design choices `cad_requested` and `cae_requested` inside every Gate hash while excluding only detected paths, runtime/license state, evidence pointers, and other operational software fields. G3 remains protected through `model-manifest.json`, drawings, native files, logs, and their referenced hashes. Schema v1 (all software fields) and v2 (all software fields excluded) remain verifiable for migration. Migrate a valid legacy snapshot before changing software paths; never refresh a stale design snapshot as a software migration.

## Release manifest

`release-manifest.json` identifies exactly one final DOCX and PDF plus the calculation book, drawings, BOM, and source ledger. If NX or Moldflow ran, list their native files and logs. Store project/design-basis revisions, limitations, unexecuted items, status, and checksums.
