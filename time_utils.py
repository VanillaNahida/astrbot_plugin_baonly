"""活动时间展示工具：统一以开放 API 的「标准时间」为准。

字段约定（见 https://www.baonly.cn/docs/api 开放文档）：

- ``startAt``：开始时间，ISO 8601，服务端已按 Asia/Shanghai 归一 —— 权威时间
- ``endAt``：结束时间；单日活动为 null
- ``timeLabel``：源站原始时间文案，**仅在时间无法解析成时间点时**作为回退

因此展示时一律先解析 ``startAt`` / ``endAt``，只有解析不出时间点时才退回
``timeLabel``；文案本身不含日期（如「预计时间」「预售」「具体时间与场地暂定」）时，
作为附注跟在标准时间后面，既不丢信息也不会顶替标准时间。
"""

import re
from datetime import datetime, timedelta, timezone

# 服务端已按 Asia/Shanghai 归一，这里同样按东八区展示
CST = timezone(timedelta(hours=8))

# 完全无法确定时间时的占位文案
PLACEHOLDER = "时间待定"

# 文案里只要出现数字，就认为它已经给出了日期/时间，不再作为附注重复展示
_HAS_DIGIT = re.compile(r"\d")


def parse_dt(value):
    """解析 ISO 8601 时间串并归一到东八区，失败返回 None。"""
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def format_date(value) -> str:
    """把时间点格式化成 ``YYYY.MM.DD``，无法解析返回空串。"""
    dt = parse_dt(value)
    return dt.strftime("%Y.%m.%d") if dt else ""


def format_time_range(
    start_at, end_at, time_label="", placeholder: str = PLACEHOLDER
) -> str:
    """把活动的标准时间格式化成展示文案。

    优先使用 ``startAt`` / ``endAt``：跨天输出 ``2026.09.30 - 2026.10.01``，
    单日只输出一个日期；解析不出时间点时才回退到源站文案 ``timeLabel``。
    """
    label = str(time_label or "").strip()
    start = parse_dt(start_at)
    if start is None:
        return label or placeholder

    text = format_date(start)
    end = parse_dt(end_at)
    if end is not None and end.date() != start.date():
        text += " - " + format_date(end)
    if label and not _HAS_DIGIT.search(label):
        text += f"（{label}）"
    return text
