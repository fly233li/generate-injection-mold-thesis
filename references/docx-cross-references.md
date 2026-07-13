# DOCX fields and cross-references

## Template priority

Preserve a supplied school template. If none exists, use a neutral A4 academic style and leave school, author, student ID, supervisor, and submission date explicitly unfilled; never invent them.

## Stable IDs

Use `FIG-*`, `TAB-*`, `EQ-*`, `SRC-*`, `CLM-*`, and `ART-*`. Map each object to its first claim, section, file, caption, purpose, source/artifact, and Word bookmark/field in `evidence-placement.csv`.

## Real Word fields

- Use a `TOC` field and heading styles for the table of contents.
- Use `SEQ` fields for figure/table/equation numbering.
- Bookmark the generated number and use `REF`/`PAGEREF` for in-text references.
- Use Word citation fields or stable citation bookmarks/fields; manually typed `[12]` is not dynamic.
- Set fields dirty/update-on-open, then actually refresh them in Word or a compatible engine before release.

Draft Markdown may contain `{{cite:SRC-001}}` and `{{xref:FIG-001}}`. These are traceability tokens, not final Word fields. Keep them until document generation and validate their ledger targets. The final DOCX must contain actual fields.

## Placement pattern

Introduce the evidence before insertion, place it near the first substantive mention, then analyze its effect on the design. Define equation symbols and units at first use. Cite adapted figures/tables and identify original CAD/CAE artifacts.

## Strict audit

`docx_audit.py` inspects the document, headers, footers, footnotes, and endnotes; assembles split complex-field instructions; checks bookmarks and targets; and recognizes broken-reference text in Chinese/English. In strict mode, manual captions/references, missing TOC/SEQ/REF, disabled update fields, broken fields, and invalid bookmarks block release.

After refreshing fields, export PDF and visually inspect page completeness, fonts, figures, tables, equations, and cross-reference rendering. Record the reviewed PDF path and hash in `07_audit/pdf-visual-review.json`.
