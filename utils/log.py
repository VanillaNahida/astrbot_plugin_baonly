from __future__ import annotations

from typing import Any

from astrbot.api import logger as _logger

_PREFIX = "[Baonly]"


class _PrefixedLogger:
    __slots__ = ()

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        _logger.debug(f"{_PREFIX} {msg}", *args, stacklevel=2, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        _logger.info(f"{_PREFIX} {msg}", *args, stacklevel=2, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        _logger.warning(f"{_PREFIX} {msg}", *args, stacklevel=2, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        _logger.error(f"{_PREFIX} {msg}", *args, stacklevel=2, **kwargs)


log = _PrefixedLogger()
