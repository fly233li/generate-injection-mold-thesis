from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from common import utc_now


TEXT_SUFFIXES = {".md", ".csv", ".txt", ".py"}
JSON_SUFFIXES = {".json"}


def make_slug(title: str) -> str:
    ascii_words = re.findall(r"[a-z0-9]+", title.lower())
    stem = "-".join(ascii_words)[:48].strip("-") if ascii_words else "injection-mold-project"
    digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}"


def replace_string(value: str, tokens: dict[str, str]) -> str:
    for key, replacement in tokens.items():
        value = value.replace("{{" + key + "}}", replacement)
    return value


def replace_json_value(value: Any, tokens: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replace_string(value, tokens)
    if isinstance(value, list):
        return [replace_json_value(item, tokens) for item in value]
    if isinstance(value, dict):
        return {key: replace_json_value(item, tokens) for key, item in value.items()}
    return value


def replace_tokens(root: Path, tokens: dict[str, str]) -> None:
    """Replace template tokens without ever injecting raw text into JSON syntax."""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in JSON_SUFFIXES:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            data = replace_json_value(data, tokens)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
        elif suffix in TEXT_SUFFIXES:
            original = path.read_text(encoding="utf-8-sig")
            text = replace_string(original, tokens)
            if text != original:
                encoding = "utf-8-sig" if suffix == ".csv" else "utf-8"
                path.write_text(text, encoding=encoding, newline="")


def initialize(title: str, root: Path, slug: str | None, mode: str, cad: str, cae: str) -> Path:
    title = title.strip()
    if not title:
        raise ValueError("Title cannot be empty")
    if any(ord(char) < 32 and char not in "\t" for char in title):
        raise ValueError("Title contains control characters")
    slug = slug or make_slug(title)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", slug):
        raise ValueError("Slug must contain 3-80 lowercase letters, digits, or hyphens")

    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / slug
    if destination.exists():
        raise FileExistsError(f"Project already exists: {destination}")

    template = Path(__file__).resolve().parents[1] / "assets" / "project-template"
    if not template.is_dir():
        raise FileNotFoundError(f"Missing project template: {template}")

    from_zero = mode == "from-zero"
    classification = "EDU-CONCEPT" if from_zero else "REAL-PART"
    part_input_status = "missing" if from_zero else "pending_registration"
    teaching_notice = "教学设计用途；未经实物试制、模具调试及专业审核不得直接用于生产"
    if from_zero:
        disclosure = (
            "由于未提供企业任务书、实物测绘资料及既有三维模型，本项目将研究对象定义为面向本科课程设计的原创概念塑件。"
            "几何尺寸、生产批量和性能目标属于经确认的设计输入，不代表现有商品的实测参数或企业数据。"
            "成果用于教学设计，未经实物试制、模具调试及专业审核不得直接用于生产。"
        )
        input_summary = "课程任务书、学校模板、塑件二维图和三维模型均缺失；由题目从零建立原创教学概念。"
    else:
        disclosure = (
            "本项目按已提供塑件资料开展，但所有输入仍须登记来源、版本和文件哈希。"
            "在二维图、三维模型及关键尺寸完成核验前，不得声称数据已测绘或已由企业确认。" + teaching_notice
        )
        input_summary = "已选择 supplied-part 模式；塑件资料状态为待登记，登记完成前 Gate G1 不得通过。"

    temp = root / f".{slug}.creating-{uuid.uuid4().hex}"
    created_at = utc_now()
    project_id = "PRJ-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:12].upper()
    try:
        shutil.copytree(template, temp)
        for relative in (
            "approvals",
            "02_sources/evidence",
            "04_cad/nx/journals",
            "04_cad/exports",
            "04_cad/drawings",
            "05_cae/results",
            "06_manuscript/figures",
            "deliverables/files",
        ):
            (temp / relative).mkdir(parents=True, exist_ok=True)
        replace_tokens(
            temp,
            {
                "TITLE": title,
                "PROJECT_ID": project_id,
                "SLUG": slug,
                "MODE": mode,
                "CAD": cad,
                "CAE": cae,
                "CREATED_AT": created_at,
                "CLASSIFICATION": classification,
                "PART_INPUT_STATUS": part_input_status,
                "DISCLOSURE": disclosure,
                "INPUT_SUMMARY": input_summary,
                "TEACHING_NOTICE": teaching_notice,
            },
        )
        # Parse every JSON file once before publishing the directory.
        for json_path in temp.rglob("*.json"):
            json.loads(json_path.read_text(encoding="utf-8-sig"))
        os.replace(temp, destination)
    except Exception:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a traceable injection-mold thesis project")
    parser.add_argument("--title", required=True, help="Chinese or English thesis title")
    parser.add_argument("--root", required=True, type=Path, help="Parent output directory")
    parser.add_argument("--slug", help="Optional ASCII project folder name")
    parser.add_argument("--mode", choices=("from-zero", "supplied-part"), default="from-zero")
    parser.add_argument("--cad", choices=("nx", "manual", "none"), default="nx")
    parser.add_argument("--cae", choices=("moldflow", "manual", "none"), default="moldflow")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        destination = initialize(args.title, args.root, args.slug, args.mode, args.cad, args.cae)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
