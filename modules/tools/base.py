from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from ..services import PluginServices


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def error_json(message: str) -> str:
    return to_json({"error": message})


@dataclass
class BaonlyTool(FunctionTool[AstrAgentContext]):
    services: Any = Field(default=None, repr=False, exclude=True)

    @property
    def svc(self) -> PluginServices:
        return self.services
