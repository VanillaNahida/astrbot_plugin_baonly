from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from ...utils.text import clean

_SECTION = "BASE_INFO"
_GROUP_WORD = "群"
_NUMBER = re.compile(r"\d{5,12}")
_BARE_NUMBER = re.compile(r"\d{5,11}")
_SEPARATORS = "：:，, "


def _strip_title(title: str, content: str) -> str:
    if content.startswith(title):
        content = content[len(title) :].lstrip(_SEPARATORS)
    return content


def _is_group(title: str, content: str) -> bool:
    if _GROUP_WORD in title:
        return True
    if _GROUP_WORD in content and _NUMBER.search(content):
        return True
    return bool(_BARE_NUMBER.fullmatch(content))


def group_lines(info_items: Iterable[Any]) -> list[str]:
    lines = []
    for item in info_items or ():
        if not isinstance(item, dict) or item.get("section") != _SECTION:
            continue
        title = clean(item.get("title"))
        content = _strip_title(title, clean(item.get("content")))
        if title and content and _is_group(title, content):
            lines.append(f"{title}：{content}")
    return lines
