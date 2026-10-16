from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

CST = timezone(timedelta(hours=8))

PLACEHOLDER = "时间待定"

_HAS_DIGIT = re.compile(r"\d")


def now() -> datetime:
    return datetime.now(CST)


def parse_dt(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if value > 1e11 else value
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(CST)


def format_date(value: object) -> str:
    dt = parse_dt(value)
    return dt.strftime("%Y.%m.%d") if dt else ""


def format_time_range(
    start_at: object,
    end_at: object,
    time_label: object = "",
    placeholder: str = PLACEHOLDER,
) -> str:
    label = str(time_label or "").strip()
    start = parse_dt(start_at) or parse_dt(end_at)
    if start is None:
        return label or placeholder

    text = format_date(start)
    end = parse_dt(end_at)
    if end is not None and end.date() != start.date():
        text += " - " + format_date(end)
    if label and not _HAS_DIGIT.search(label):
        text += f"（{label}）"
    return text


def event_window(start_at: object, end_at: object) -> tuple[datetime | None, datetime | None]:
    start = parse_dt(start_at)
    end = parse_dt(end_at)
    if start is not None and end is None:
        end = datetime.combine(start.date(), time.max, tzinfo=CST)
    return start, end


def format_clock(value: datetime | None = None) -> str:
    return (value or now()).strftime("%Y/%m/%d %H:%M")


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}小时{minutes}分{secs}秒"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"
