# Quality and release

## Severity

- `blocker`: stop the Gate or release;
- `error`: required output is wrong; fix before approval;
- `warning`: limitation that must remain visible;
- `info`: traceability note.

## Required checks

### Truth and requirements

- Missing school/template/part inputs are disclosed; no school, author, student ID, supervisor, enterprise, or experiment is invented.
- `EDU-CONCEPT` geometry and production targets are confirmed design inputs, never measurements.
- Every active requirement has acceptance evidence and valid cross-ledger IDs.

### Engineering

- Values are finite, unit-compatible, versioned, and origin-bound.
- Confirmed calculations use confirmed parameters only; unknown statuses and unsafe expressions fail.
- Calculations cover part mass, cavity count, injection capacity, clamp force, cooling, and ejection, plus project-specific checks.
- Part, mold, drawings, BOM, machine checks, CAE, and prose use consistent revisions.

### NX and Moldflow

- Detection never proves a license. Promote to `executed` only after a real successful run.
- Executed NX includes `.prt`, neutral geometry, checksums, tool/version/license record, log, open verification, volume, mass, and projected area.
- Executed Moldflow includes study file, material card, mesh metrics, cases, successful solver record/log, result files, geometry revision, and checksums.
- `prepared_unexecuted`, `stale`, or `rejected` evidence cannot support CAD/SIM claims.

### Literature and manuscript

- Each external claim maps to verified source metadata and an exact locator.
- CNKI is preferred for Chinese academic literature, but CNKI snippets alone are not sufficient evidence.
- No orphan source, claim, figure, table, equation, drawing, or requirement remains.
- Word TOC/captions/references are real fields; final strict audit blocks manual numbering.

### Release

- `release-manifest.json` identifies canonical outputs and verifies SHA-256 values.
- Final DOCX is a substantive OOXML package; final PDF has a PDF signature, plausible size, and a matching visual-review record.
- Released files include manuscript, calculation book, drawings, BOM, source ledger, and actual NX/Moldflow outputs when executed.
- Limitations and every unexecuted item are listed.

Run:

```powershell
py -3 "<skill-root>\scripts\engineering_audit.py" --project "<project>"
py -3 "<skill-root>\scripts\audit_project.py" --project "<project>" --gate G4
py -3 "<skill-root>\scripts\docx_audit.py" "<paper.docx>"
```

No blocker may be waived by rewording. Correct the source ledger/artifact, regenerate dependents, and rerun.
