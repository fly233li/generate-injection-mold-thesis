from __future__ import annotations

import re

import _init_project_impl as _impl
from _init_project_impl import *


def replace_string(value: str, tokens: dict[str, str]) -> str:
    if not tokens:
        return value
    pattern = re.compile(r"\{\{(" + "|".join(re.escape(key) for key in sorted(tokens, key=len, reverse=True)) + r")\}\}")
    return pattern.sub(lambda match: tokens[match.group(1)], value)


_impl.replace_string = replace_string
make_slug = _impl.make_slug
replace_json_value = _impl.replace_json_value
replace_tokens = _impl.replace_tokens
initialize = _impl.initialize
build_parser = _impl.build_parser


def main() -> int:
    return _impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
