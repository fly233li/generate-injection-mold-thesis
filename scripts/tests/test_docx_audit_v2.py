from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from docx_audit import audit_docx


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def complex_field(chunks: list[str], result: str = "") -> str:
    instructions = "".join(
        f'<w:r><w:instrText xml:space="preserve">{chunk}</w:instrText></w:r>'
        for chunk in chunks
    )
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        + instructions
        + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + (f"<w:r><w:t>{result}</w:t></w:r>" if result else "")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def valid_body() -> str:
    return (
        "<w:p>"
        + complex_field(["TO", 'C \\o "1-3"'])
        + "</w:p>"
        + '<w:p><w:bookmarkStart w:id="1" w:name="fig_one"/>'
        + "<w:r><w:t>图 </w:t></w:r>"
        + complex_field(["SE", "Q Figure \\* ARABIC"], "2-1")
        + "<w:r><w:t> 示例图</w:t></w:r>"
        + '<w:bookmarkEnd w:id="1"/></w:p>'
        + "<w:p><w:r><w:t>见图 </w:t></w:r>"
        + complex_field(["RE", "F fig_one \\h"], "2-1")
        + "</w:p>"
    )


def make_docx(
    path: Path,
    body: str,
    *,
    update_fields: bool = True,
    extra_parts: dict[str, str] | None = None,
) -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:settings xmlns:w="{W}"><w:updateFields w:val="{str(update_fields).lower()}"/>'
        "</w:settings>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/settings.xml", settings)
        for name, payload in (extra_parts or {}).items():
            archive.writestr(name, payload)


class DocxAuditV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_split_complex_instructions_are_joined_and_pass(self) -> None:
        path = self.root / "split-fields.docx"
        make_docx(path, valid_body())
        result = audit_docx(path)
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["field_counts"]["TOC"], 1)
        self.assertEqual(result["field_counts"]["SEQ"], 1)
        self.assertEqual(result["field_counts"]["REF"], 1)

    def test_unrelated_field_in_same_paragraph_does_not_mask_manual_text(self) -> None:
        path = self.root / "same-paragraph.docx"
        body = (
            valid_body()
            + "<w:p><w:r><w:t>见图9-9；</w:t></w:r>"
            + complex_field(["REF fig_one \\h"], "2-1")
            + "</w:p>"
            + "<w:p><w:r><w:t>图8-8 手工题注；</w:t></w:r>"
            + complex_field(["SEQ Figure"], "3")
            + "</w:p>"
            + "<w:p><w:r><w:t>[9] 手工文献；</w:t></w:r>"
            + complex_field(["CITATION source_one"], "[1]")
            + "</w:p>"
        )
        make_docx(path, body)
        result = audit_docx(path)
        rules = [item["rule"] for item in result["issues"]]
        self.assertFalse(result["passed"])
        self.assertIn("DOCX101", rules)
        self.assertIn("DOCX103", rules)
        self.assertIn("DOCX104", rules)
        self.assertEqual(rules.count("DOCX103"), 1)
        self.assertEqual(rules.count("DOCX104"), 1)

    def test_header_footer_note_parts_are_audited(self) -> None:
        cases = {
            "word/header1.xml": "hdr",
            "word/footer1.xml": "ftr",
            "word/footnotes.xml": "footnotes",
            "word/endnotes.xml": "endnotes",
        }
        for part, root_tag in cases.items():
            with self.subTest(part=part):
                path = self.root / (part.replace("/", "-") + ".docx")
                payload = (
                    f'<w:{root_tag} xmlns:w="{W}"><w:p><w:r>'
                    "<w:t>错误!未定义书签。</w:t>"
                    f"</w:r></w:p></w:{root_tag}>"
                )
                make_docx(path, valid_body(), extra_parts={part: payload})
                result = audit_docx(path)
                self.assertFalse(result["passed"])
                self.assertTrue(
                    any(
                        item["rule"] == "DOCX105" and part in item["location"]
                        for item in result["issues"]
                    ),
                    result["issues"],
                )

    def test_chinese_and_english_broken_field_results_are_blockers(self) -> None:
        for index, message in enumerate(
            (
                "错误！未找到引用源。",
                "错误!书签未定义。",
                "Error! Bookmark not defined.",
                "ERROR! Reference source not found.",
            )
        ):
            with self.subTest(message=message):
                path = self.root / f"broken-{index}.docx"
                body = valid_body() + f"<w:p><w:r><w:t>{message}</w:t></w:r></w:p>"
                make_docx(path, body)
                result = audit_docx(path)
                self.assertFalse(result["passed"])
                self.assertTrue(
                    any(
                        item["rule"] == "DOCX105" and item["severity"] == "blocker"
                        for item in result["issues"]
                    )
                )

    def test_bookmark_start_end_and_ref_target_are_validated(self) -> None:
        path = self.root / "bookmark-integrity.docx"
        body = (
            valid_body()
            + '<w:p><w:bookmarkStart w:id="7" w:name="open_only"/>'
            + complex_field(["REF missing_target \\h"], "9")
            + "</w:p>"
        )
        make_docx(path, body)
        result = audit_docx(path)
        rules = {item["rule"] for item in result["issues"]}
        self.assertFalse(result["passed"])
        self.assertIn("DOCX107", rules)
        self.assertIn("DOCX115", rules)

    def test_strict_update_fields_failure_is_lenient_warning(self) -> None:
        path = self.root / "update-off.docx"
        make_docx(path, valid_body(), update_fields=False)
        strict_result = audit_docx(path)
        lenient_result = audit_docx(path, strict=False)
        self.assertFalse(strict_result["passed"])
        self.assertTrue(
            any(
                item["rule"] == "DOCX110" and item["severity"] == "error"
                for item in strict_result["issues"]
            )
        )
        self.assertTrue(lenient_result["passed"], lenient_result["issues"])
        self.assertTrue(
            any(
                item["rule"] == "DOCX110" and item["severity"] == "warning"
                for item in lenient_result["issues"]
            )
        )

    def test_strict_missing_toc_seq_and_ref_are_errors(self) -> None:
        path = self.root / "missing-required-fields.docx"
        make_docx(path, "<w:p><w:r><w:t>普通正文</w:t></w:r></w:p>")
        strict_result = audit_docx(path)
        lenient_result = audit_docx(path, strict=False)
        strict_by_rule = {item["rule"]: item["severity"] for item in strict_result["issues"]}
        self.assertFalse(strict_result["passed"])
        self.assertEqual(strict_by_rule["DOCX108"], "error")
        self.assertEqual(strict_by_rule["DOCX109"], "error")
        self.assertEqual(strict_by_rule["DOCX117"], "error")
        self.assertTrue(lenient_result["passed"], lenient_result["issues"])


if __name__ == "__main__":
    unittest.main()
