from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from common import atomic_write_json, blocking, issue, sort_issues, utc_now


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
W_ATTR = "{" + W + "}"
WORD_PART_RE = re.compile(
    r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes)\.xml$",
    re.IGNORECASE,
)
FIELD_TYPES = ("TOC", "SEQ", "REF", "PAGEREF", "CITATION")

CAPTION_RE = re.compile(
    r"^\s*(?P<label>图|表)\s*(?P<number>\d+(?:\s*[.·\-—–]\s*\d+)*)",
    re.UNICODE,
)
EQUATION_RE = re.compile(
    r"[（(]\s*(?P<number>\d+\s*[.·\-—–]\s*\d+)\s*[）)]\s*$",
    re.UNICODE,
)
FIGURE_TABLE_REFERENCE_RE = re.compile(
    r"(?:(?:如|见|参见|由)\s*)?(?P<label>图|表)\s*"
    r"(?P<number>\d+(?:\s*[.·\-—–]\s*\d+)*)",
    re.UNICODE,
)
NUMBERED_CITATION_RE = re.compile(
    r"\[\s*(?P<number>\d+(?:\s*[-–—,，]\s*\d+)*)\s*\]",
    re.UNICODE,
)
BROKEN_FIELD_RE = re.compile(
    r"(?:错误\s*[!！]\s*(?:"
    r"未定义书签|书签未定义|未找到引用源|找不到引用源|引用源未找到|"
    r"未找到目录项|找不到目录项|未找到图表目录|找不到图表目录"
    r")|ERROR\s*[!！]\s*(?:"
    r"BOOKMARK\s+NOT\s+DEFINED|REFERENCE\s+SOURCE\s+NOT\s+FOUND|"
    r"NO\s+TABLE\s+OF\s+CONTENTS\s+ENTRIES\s+FOUND|"
    r"NO\s+TABLE\s+OF\s+FIGURES\s+ENTRIES\s+FOUND"
    r"))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FieldSpan:
    instruction: str
    field_type: str
    result_start: int
    result_end: int


def _normalise_instruction(chunks: list[str] | tuple[str, ...]) -> str:
    # Word is free to split a field instruction at any character boundary.  Joining
    # raw chunks first preserves both "RE" + "F" and the meaningful spaces before
    # switches or bookmark names.
    return re.sub(r"\s+", " ", "".join(chunks).strip())


def _field_type(instruction: str) -> str:
    match = re.match(r"^([A-Za-z]+)\b", instruction)
    return match.group(1).upper() if match else ""


def _paragraph_content(paragraph: ET.Element) -> tuple[str, list[FieldSpan]]:
    visible: list[str] = []
    fields: list[FieldSpan] = []
    stack: list[dict[str, object]] = []
    length = 0

    def append_visible(value: str) -> None:
        nonlocal length
        visible.append(value)
        length += len(value)

    def append_field(instruction: str, start: int, end: int) -> None:
        normalised = _normalise_instruction((instruction,))
        if normalised:
            fields.append(FieldSpan(normalised, _field_type(normalised), start, end))

    def walk(element: ET.Element) -> None:
        nonlocal length
        if element.tag == W_ATTR + "fldSimple":
            instruction = element.get(W_ATTR + "instr") or ""
            start = length
            for child in element:
                walk(child)
            append_field(instruction, start, length)
            return

        if element.tag == W_ATTR + "fldChar":
            marker = (element.get(W_ATTR + "fldCharType") or "").lower()
            if marker == "begin":
                stack.append({"chunks": [], "result_start": length})
            elif marker == "separate" and stack:
                stack[-1]["result_start"] = length
            elif marker == "end" and stack:
                context = stack.pop()
                instruction = _normalise_instruction(tuple(context["chunks"]))  # type: ignore[arg-type]
                append_field(instruction, int(context["result_start"]), length)
            return

        if element.tag == W_ATTR + "instrText":
            chunk = element.text or ""
            if stack:
                chunks = stack[-1]["chunks"]
                assert isinstance(chunks, list)
                chunks.append(chunk)
            else:
                # Some producers emit a bare instrText without fldChar wrappers.
                # It is still auditable, although it has no protected result span.
                append_field(chunk, length, length)
            return

        if element.tag == W_ATTR + "t":
            append_visible(element.text or "")
            return
        if element.tag == W_ATTR + "tab":
            append_visible("\t")
            return
        if element.tag in {W_ATTR + "br", W_ATTR + "cr"}:
            append_visible("\n")
            return

        for child in element:
            walk(child)

    walk(paragraph)

    # Retain the instruction from a field whose result continues in another
    # paragraph (TOC fields commonly do).  Its local result span ends here.
    for context in stack:
        instruction = _normalise_instruction(tuple(context["chunks"]))  # type: ignore[arg-type]
        append_field(instruction, int(context["result_start"]), length)
    return "".join(visible), fields


def _overlaps_field(
    fields: list[FieldSpan],
    start: int,
    end: int,
    allowed_types: set[str],
) -> bool:
    return any(
        field.field_type in allowed_types
        and field.result_end > field.result_start
        and max(start, field.result_start) < min(end, field.result_end)
        for field in fields
    )


def _policy_severity(strict: bool, strict_level: str = "error") -> str:
    return strict_level if strict else "warning"


def _extract_ref_target(instruction: str) -> str | None:
    command = re.match(r"^\s*(?:REF|PAGEREF)\b", instruction, re.IGNORECASE)
    if not command:
        return None
    tail = instruction[command.end() :]
    target = re.match(r"\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s\\]+))", tail)
    if not target:
        return None
    return next((value for value in target.groups() if value is not None), None)


def _empty_result(document_path: Path, issues: list[dict[str, str]], strict: bool) -> dict[str, object]:
    ordered = sort_issues(issues)
    summary = {
        level: sum(1 for item in ordered if item["severity"] == level)
        for level in ("blocker", "error", "warning", "info")
    }
    return {
        "schema_version": "2.0",
        "generated_at": utc_now(),
        "source": str(document_path),
        "strict": strict,
        "passed": not blocking(ordered),
        "summary": summary,
        "field_counts": {name: 0 for name in FIELD_TYPES},
        "bookmark_count": 0,
        "audited_parts": [],
        "issues": ordered,
    }


def audit_docx(path: str | Path, strict: bool = True) -> dict[str, object]:
    document_path = Path(path).expanduser().resolve()
    issues: list[dict[str, str]] = []
    if not document_path.is_file() or document_path.stat().st_size == 0:
        issues.append(
            issue(
                "DOCX001",
                "blocker",
                "DOCX file is missing or empty",
                location=str(document_path),
            )
        )
        return _empty_result(document_path, issues, strict)

    try:
        with zipfile.ZipFile(document_path) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                issues.append(
                    issue(
                        "DOCX002",
                        "blocker",
                        "Invalid DOCX package: word/document.xml is absent",
                        location=str(document_path),
                    )
                )
                return _empty_result(document_path, issues, strict)
            part_names = sorted(name for name in names if WORD_PART_RE.match(name))
            part_bytes = {name: archive.read(name) for name in part_names}
            settings_xml = archive.read("word/settings.xml") if "word/settings.xml" in names else None
    except Exception as exc:
        issues.append(
            issue(
                "DOCX002",
                "blocker",
                f"Invalid DOCX package: {exc}",
                location=str(document_path),
            )
        )
        return _empty_result(document_path, issues, strict)

    roots: dict[str, ET.Element] = {}
    for part_name, payload in part_bytes.items():
        try:
            roots[part_name] = ET.fromstring(payload)
        except ET.ParseError as exc:
            issues.append(
                issue(
                    "DOCX003",
                    "blocker" if part_name == "word/document.xml" else "error",
                    f"Invalid Word XML part: {exc}",
                    location=part_name,
                )
            )

    if "word/document.xml" not in roots:
        return _empty_result(document_path, issues, strict)

    all_fields: list[tuple[str, FieldSpan]] = []
    bookmark_names: list[tuple[str, str]] = []

    for part_name, root in roots.items():
        paragraphs = root.findall(".//w:p", NS)
        for number, paragraph in enumerate(paragraphs, start=1):
            text, fields = _paragraph_content(paragraph)
            all_fields.extend((part_name, field) for field in fields)
            location = f"{part_name} paragraph {number}"
            snippet = text.strip()[:100]

            caption = CAPTION_RE.match(text)
            if caption and not _overlaps_field(
                fields,
                *caption.span("number"),
                {"SEQ"},
            ):
                issues.append(
                    issue(
                        "DOCX101",
                        _policy_severity(strict),
                        "Caption number is manually typed rather than generated by a SEQ field",
                        snippet,
                        location,
                    )
                )

            equation = EQUATION_RE.search(text)
            if equation and not _overlaps_field(
                fields,
                *equation.span("number"),
                {"SEQ"},
            ):
                issues.append(
                    issue(
                        "DOCX102",
                        _policy_severity(strict),
                        "Equation number is manually typed rather than generated by a SEQ field",
                        equation.group(0),
                        location,
                    )
                )

            for reference in FIGURE_TABLE_REFERENCE_RE.finditer(text):
                if caption and reference.start() < caption.end():
                    continue
                if not _overlaps_field(
                    fields,
                    *reference.span("number"),
                    {"REF", "PAGEREF"},
                ):
                    issues.append(
                        issue(
                            "DOCX103",
                            _policy_severity(strict),
                            "In-text figure/table reference is manually typed rather than generated by REF/PAGEREF",
                            reference.group(0),
                            location,
                        )
                    )

            for citation in NUMBERED_CITATION_RE.finditer(text):
                if not _overlaps_field(
                    fields,
                    *citation.span("number"),
                    {"REF", "CITATION"},
                ):
                    issues.append(
                        issue(
                            "DOCX104",
                            _policy_severity(strict),
                            "Numbered citation is manually typed rather than generated by REF/CITATION",
                            citation.group(0),
                            location,
                        )
                    )

            if BROKEN_FIELD_RE.search(text):
                issues.append(
                    issue(
                        "DOCX105",
                        "blocker",
                        "Broken or unresolved Word field text is present",
                        snippet,
                        location,
                    )
                )

        starts_by_id: dict[str, list[tuple[int, str]]] = defaultdict(list)
        ends_by_id: dict[str, list[int]] = defaultdict(list)
        sequence = 0
        for element in root.iter():
            sequence += 1
            if element.tag == W_ATTR + "bookmarkStart":
                bookmark_id = element.get(W_ATTR + "id") or ""
                bookmark_name = element.get(W_ATTR + "name") or ""
                starts_by_id[bookmark_id].append((sequence, bookmark_name))
                if bookmark_name:
                    bookmark_names.append((part_name, bookmark_name))
                else:
                    issues.append(
                        issue(
                            "DOCX113",
                            "error",
                            "Bookmark start has no name",
                            bookmark_id,
                            part_name,
                        )
                    )
            elif element.tag == W_ATTR + "bookmarkEnd":
                bookmark_id = element.get(W_ATTR + "id") or ""
                ends_by_id[bookmark_id].append(sequence)

        for bookmark_id in sorted(set(starts_by_id) | set(ends_by_id)):
            starts = starts_by_id.get(bookmark_id, [])
            ends = ends_by_id.get(bookmark_id, [])
            entity = bookmark_id or "<missing id>"
            if not bookmark_id:
                issues.append(
                    issue(
                        "DOCX114",
                        "error",
                        "Bookmark start/end has no w:id",
                        entity,
                        part_name,
                    )
                )
            if len(starts) != 1 or len(ends) != 1:
                issues.append(
                    issue(
                        "DOCX115",
                        "error",
                        f"Bookmark range must contain one start and one end; found {len(starts)} start(s) and {len(ends)} end(s)",
                        entity,
                        part_name,
                    )
                )
            elif ends[0] < starts[0][0]:
                issues.append(
                    issue(
                        "DOCX116",
                        "error",
                        "Bookmark end appears before its start",
                        entity,
                        part_name,
                    )
                )

    bookmark_counts = Counter(name for _, name in bookmark_names)
    for name, count in sorted(bookmark_counts.items()):
        if count > 1:
            locations = ", ".join(part for part, candidate in bookmark_names if candidate == name)
            issues.append(
                issue(
                    "DOCX106",
                    "error",
                    f"Duplicate bookmark name appears {count} times",
                    name,
                    locations,
                )
            )

    for part_name, field in all_fields:
        if field.field_type not in {"REF", "PAGEREF"}:
            continue
        target = _extract_ref_target(field.instruction)
        if target and target not in bookmark_counts:
            issues.append(
                issue(
                    "DOCX107",
                    "blocker",
                    "REF/PAGEREF targets a missing bookmark",
                    target,
                    part_name,
                )
            )

    counts = {
        name: sum(1 for _, field in all_fields if field.field_type == name)
        for name in FIELD_TYPES
    }
    missing_rules = {
        "TOC": ("DOCX108", "No TOC field was found"),
        "SEQ": ("DOCX109", "No SEQ field was found for dynamic captions/equations"),
        "REF": ("DOCX117", "No REF field was found for dynamic cross-references"),
    }
    for field_name, (rule, message) in missing_rules.items():
        if counts[field_name] == 0:
            issues.append(
                issue(
                    rule,
                    _policy_severity(strict),
                    message,
                    location="word/document.xml",
                )
            )

    if settings_xml is None:
        issues.append(
            issue(
                "DOCX112",
                _policy_severity(strict),
                "Word settings.xml is absent, so automatic field updating cannot be verified",
                location="word/settings.xml",
            )
        )
    else:
        try:
            settings = ET.fromstring(settings_xml)
            update = settings.find(".//w:updateFields", NS)
            value = (update.get(W_ATTR + "val") if update is not None else None)
            disabled = update is None or (value or "true").strip().lower() in {
                "false",
                "0",
                "off",
                "no",
            }
            if disabled:
                issues.append(
                    issue(
                        "DOCX110",
                        _policy_severity(strict),
                        "Word is not configured to update fields on open",
                        location="word/settings.xml",
                    )
                )
        except ET.ParseError as exc:
            issues.append(
                issue(
                    "DOCX111",
                    _policy_severity(strict),
                    f"Could not parse Word settings: {exc}",
                    location="word/settings.xml",
                )
            )

    ordered = sort_issues(issues)
    summary = {
        level: sum(1 for item in ordered if item["severity"] == level)
        for level in ("blocker", "error", "warning", "info")
    }
    return {
        "schema_version": "2.0",
        "generated_at": utc_now(),
        "source": str(document_path),
        "strict": strict,
        "passed": not blocking(ordered),
        "summary": summary,
        "field_counts": counts,
        "bookmark_count": len(bookmark_counts),
        "audited_parts": sorted(roots),
        "issues": ordered,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit real Word fields, bookmarks, captions, and references"
    )
    parser.add_argument("docx")
    parser.add_argument("--json", dest="json_path")
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Downgrade final-document policy violations to warnings",
    )
    args = parser.parse_args()
    result = audit_docx(args.docx, strict=not args.lenient)
    if args.json_path:
        atomic_write_json(Path(args.json_path).expanduser().resolve(), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
