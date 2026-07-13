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


def make_docx(path: Path, body: str, update_fields: bool = True) -> None:
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>'
    settings = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="{W}"><w:updateFields w:val="{str(update_fields).lower()}"/></w:settings>'
    content_types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("word/settings.xml", settings)


class DocxAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_dynamic_caption_and_ref_pass(self) -> None:
        body = (
            '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>TOC \\o "1-3"</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
            '<w:p><w:bookmarkStart w:id="1" w:name="fig_one"/><w:r><w:t>图 </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>SEQ Figure</w:instrText></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r><w:bookmarkEnd w:id="1"/><w:r><w:t> 示例图</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>见图 </w:t></w:r><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>REF fig_one \\h</w:instrText></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
        )
        path = self.root / "dynamic.docx"
        make_docx(path, body)
        result = audit_docx(path)
        self.assertTrue(result["passed"], result["issues"])
        self.assertEqual(result["field_counts"]["SEQ"], 1)
        self.assertEqual(result["field_counts"]["REF"], 1)

    def test_manual_caption_fails(self) -> None:
        path = self.root / "manual.docx"
        make_docx(path, '<w:p><w:r><w:t>图2.1 手工题注</w:t></w:r></w:p>')
        result = audit_docx(path)
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["rule"] == "DOCX101" for item in result["issues"]))

    def test_missing_ref_bookmark_fails(self) -> None:
        path = self.root / "broken.docx"
        body = '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>SEQ Figure</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p><w:p><w:r><w:instrText>REF missing</w:instrText></w:r></w:p>'
        make_docx(path, body)
        result = audit_docx(path)
        self.assertFalse(result["passed"])
        self.assertTrue(any(item["rule"] == "DOCX107" for item in result["issues"]))


if __name__ == "__main__":
    unittest.main()
