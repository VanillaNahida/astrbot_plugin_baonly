from __future__ import annotations

from functools import cache
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from ..meta import ASSETS_DIR

CARD_WIDTH = 414

FONT_STYLESHEETS = (
    "https://cdn.jsdelivr.net/gh/VanillaNahida/BA-Spark-Cursor/fonts/Blueaka/Blueaka.css",
    "https://cdn.jsdelivr.net/gh/VanillaNahida/BA-Spark-Cursor/fonts/Blueaka_Bold/Blueaka_Bold.css",
)


@cache
def _svg(name: str) -> str:
    return (ASSETS_DIR / "icons" / f"{name}.svg").read_text(encoding="utf-8").strip()


def icon(name: str, size: int = 20) -> Markup:
    try:
        svg = _svg(name)
    except OSError:
        return Markup("")
    return Markup(svg.replace("<svg ", f'<svg width="{size}" height="{size}" aria-hidden="true" ', 1))


_env = Environment(
    loader=FileSystemLoader(ASSETS_DIR),
    autoescape=select_autoescape(("html", "j2")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.globals.update(icon=icon, card_width=CARD_WIDTH, font_stylesheets=FONT_STYLESHEETS)


def render_template(name: str, **context: Any) -> str:
    return _env.get_template(f"templates/{name}").render(**context)
