from __future__ import annotations

import time
import uuid
from pathlib import Path

from .log import log


def unique_path(directory: Path, prefix: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"


def purge_older_than(directory: Path, max_age_seconds: float) -> int:
    if not directory.is_dir():
        return 0
    deadline = time.time() - max_age_seconds
    removed = 0
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < deadline:
                path.unlink()
                removed += 1
        except OSError as exc:
            log.debug(f"清理临时文件失败 {path.name}: {exc}")
    return removed
