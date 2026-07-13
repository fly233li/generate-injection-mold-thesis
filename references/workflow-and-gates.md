# Workflow and gates

## State sequence

`intake → concept → evidence_plan → scheme → engineering → manuscript → release_review → released`

The Agent may research safely while awaiting approval, but may not freeze geometry, a mold scheme, or a release without the matching user confirmation.

## G1 — design basis and outline

Present one review packet containing:

- `REAL-PART` or `EDU-CONCEPT` classification and input status;
- part boundary, function, environment, interfaces, coordinates, and opening direction;
- 2–3 original part concepts, recommendation, advantages, risks, and rejection reasons;
- finite envelope, wall/draft/feature strategy, at least two material candidates;
- production basis, quality targets, safety constraints, deliverables;
- approved requirements, K3 assumptions, and three-level outline.

Write the confirmed result to `design-basis.json`. Save the user's exact confirmation in `approvals/` and approve with `--evidence`. Do not create approval evidence unless the user actually confirms.

## G2 — mold scheme

Compare at least two complete schemes over at least five criteria. Record all required decision categories: material, cavity count, parting, gate, venting, side action (including an explicit no-side-action decision), ejection, cooling, mold base, and injection machine. Each approved decision has at least two alternatives, rationale, evidence IDs, and impact.

## G3 — engineering artifacts

Require:

- at least the mandatory calculation categories with confirmed inputs, applicability, substitution, acceptance, margin, and independent check;
- a prepared NX feature/expression plan or actual hashed NX native/neutral files, execution record, log, and measured properties;
- part and assembly drawings tied to the model revision, plus a usable BOM;
- a prepared Moldflow material/mesh/case plan or an actual hashed study, solve log, cases, and results;
- requirement-to-calculation/drawing/case links and a complete placement matrix.

`prepared_unexecuted` may pass with warnings only when the plan is complete. It must never create `CAD`/`SIM` parameters or result claims.

## G4 — release

Require a substantive manuscript, five or more claim-bound sources and claims, verified placements, one canonical DOCX/PDF, dynamic fields, a matching visual PDF review, structured release manifest, checksums, and disclosed limitations. A renamed text file, tiny OOXML package, stale artifact, missing source, or manually typed reference blocks release.

## Approval and change control

Run the gate audit, create approval evidence from the actual user message, then call:

```powershell
py -3 "<skill-root>\scripts\project_state.py" approve "<project>" G1 --note "已确认设计基线" --evidence "<project>\approvals\G1-confirmation.md"
```

The approval command holds a project lock, compares pre/post-audit snapshots, stores the evidence hash, and commits once. Any upstream change makes that gate and all later gates stale.

For a frozen input change, append a change record, supersede the old ledger revision, mark dependents stale, then run:

```powershell
py -3 "<skill-root>\scripts\project_state.py" reopen "<project>" G1 --note "设计输入变更"
```

Reopen the earliest affected gate. Regenerate dependents in requirement → parameter → calculation → CAD/drawing/BOM → CAE → placement → manuscript order.
