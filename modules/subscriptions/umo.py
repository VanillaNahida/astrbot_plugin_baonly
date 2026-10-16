from __future__ import annotations

GROUP = "GroupMessage"
FRIEND = "FriendMessage"
FALLBACK_PLATFORM = "AstrBot"

_LEGACY_TYPES = {"group", "private", "groupmessage", "friendmessage"}


def message_type(is_group: bool) -> str:
    return GROUP if is_group else FRIEND


def build_umo(umo: str, is_group: bool, channel_id: str = "") -> str:
    kind = message_type(is_group)
    parts = str(umo or "").strip().split(":")
    platform = parts[0] or FALLBACK_PLATFORM
    channel_id = str(channel_id or "").strip()
    if channel_id:
        return f"{platform}:{kind}:{channel_id}"
    if len(parts) >= 3 and parts[1].lower() in _LEGACY_TYPES:
        parts[1] = kind
    return ":".join(parts)


def channel_of(umo: str) -> str:
    parts = str(umo).split(":")
    return parts[-1] if len(parts) >= 3 else str(umo)


def is_group_umo(umo: str) -> bool:
    parts = str(umo).split(":")
    return len(parts) >= 3 and parts[1] == GROUP
