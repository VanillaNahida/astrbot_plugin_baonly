from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from .log import log


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(backup)
            log.error(f"{path.name} 解析失败，已备份为 {backup.name}: {exc}")
        except OSError:
            log.error(f"{path.name} 解析失败且无法备份: {exc}")
        return None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
