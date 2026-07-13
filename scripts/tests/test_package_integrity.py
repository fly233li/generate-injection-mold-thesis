from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".md", ".py", ".json", ".csv", ".yaml", ".yml", ".txt"}


def reject_nonfinite(token: str):
    raise ValueError(token)


class PackageIntegrityTests(unittest.TestCase):
    def test_release_tree_contains_no_backup_files(self) -> None:
        unwanted = [path for path in SKILL_ROOT.rglob("*") if ".bak" in path.name.lower() or path.name == ".patch-test"]
        self.assertEqual(unwanted, [], unwanted)

    def test_all_text_is_strict_utf8_and_json_is_finite(self) -> None:
        failures: list[str] = []
        for path in SKILL_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_bytes().decode("utf-8-sig", errors="strict")
                if path.suffix.lower() == ".json":
                    json.loads(text, parse_constant=reject_nonfinite)
            except Exception as exc:
                failures.append(f"{path.relative_to(SKILL_ROOT)}: {exc}")
        self.assertEqual(failures, [], failures)

    def test_skill_local_markdown_links_resolve(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        missing: list[str] = []
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", skill):
            if "://" in target or target.startswith("#"):
                continue
            clean = target.split("#", 1)[0]
            if clean and not (SKILL_ROOT / clean).is_file():
                missing.append(target)
        self.assertEqual(missing, [], missing)


if __name__ == "__main__":
    unittest.main()
