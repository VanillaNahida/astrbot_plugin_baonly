from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from astrbot.core.utils.astrbot_path import get_astrbot_data_path

PLUGIN_NAME = "astrbot_plugin_baonly"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent

ASSETS_DIR = PLUGIN_ROOT / "data"

DATA_DIR = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
TEMP_DIR = Path(get_astrbot_data_path()) / "temp" / PLUGIN_NAME

SITE_ORIGIN = "https://www.baonly.cn"
API_BASE = f"{SITE_ORIGIN}/api/public"
STREAM_URL = "wss://www.baonly.cn/api/public/stream"
EVENT_PAGE_URL = SITE_ORIGIN + "/event/{event_id}"

def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return ""


@cache
def _metadata() -> str:
    try:
        return (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    except OSError:
        return ""


def metadata_field(name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:[^\S\n]*(.+?)[^\S\n]*$", _metadata(), re.MULTILINE)
    return match.group(1).strip("\"'") if match else ""


def plugin_version() -> str:
    return metadata_field("version").removeprefix("v")


@dataclass(frozen=True)
class RuntimeInfo:
    astrbot: str
    playwright: str
    plugin: str
    author: str

    @classmethod
    def detect(cls) -> RuntimeInfo:
        return cls(
            astrbot=package_version("astrbot"),
            playwright=package_version("playwright"),
            plugin=plugin_version(),
            author=metadata_field("author"),
        )

    def footer(self, captured_at: str) -> str:
        parts = [
            f"截图时间：{captured_at}",
            "数据来源自 www.baonly.cn",
            f"Powered By Playwright v{self.playwright}",
        ]
        if self.astrbot:
            parts.append(f"AstrBot v{self.astrbot}")
        parts.append(f"{PLUGIN_NAME} v{self.plugin}")
        if self.author:
            parts.append(f"作者：{self.author}")
        return " | ".join(parts)
