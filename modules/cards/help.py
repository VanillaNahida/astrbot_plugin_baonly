from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...utils.timefmt import format_clock
from ..meta import RuntimeInfo
from ..render import CardRenderer, render_template


@dataclass(frozen=True)
class CommandHelp:
    command: str
    example: str
    description: str


COMMANDS = (
    CommandHelp("/bao", "/bao", "截图 Baonly 活动列表页，默认每页 8 场"),
    CommandHelp("/baonly page", "/baonly page 20", "截图活动列表页并指定每页数量，可选 4 / 6 / 8 / 10 / 20 / 23 / 50"),
    CommandHelp("/baonly query", "/baonly query upcoming 深圳市", "文本查询展会列表，可按活动状态与城市筛选"),
    CommandHelp("/baonly detail", "/baonly detail 广州蔚蓝档案", "按活动 ID 或关键词查询单个展会，返回购票链接与详情卡片图片"),
    CommandHelp("/baonly sub", "/baonly sub", "订阅当前会话，展会变更时自动推送（需管理员）"),
    CommandHelp("/baonly unsub", "/baonly unsub", "取消订阅当前会话（需管理员）"),
    CommandHelp("/baonly status", "/baonly status", "查看推送连接状态（连接时长 / API Key 有效性 / 最近推送）"),
    CommandHelp("/baonly list", "/baonly list", "查看全部订阅渠道（群聊 / 私聊）"),
    CommandHelp("/baonly help", "/baonly help", "查看本帮助（使用方法表格图片）"),
)

STATUSES = (
    ("upcoming", "即将举行"),
    ("ongoing", "进行中"),
    ("past", "已结束"),
    ("all", "全部"),
)

TIPS = (
    "命令在群聊与私聊中均可使用，仅 sub / unsub 需要管理员权限",
    "也可以直接用自然语言提问，例如「广州有哪些蔚蓝档案活动？」，插件已注册 LLM 工具",
    "订阅渠道也可在 AstrBot WebUI 插件详情页的「订阅管理」中维护",
    "展会数据来源：https://www.baonly.cn",
)


def help_text() -> str:
    lines = ["Baonly 插件使用帮助："]
    for row in COMMANDS:
        lines += [f"- {row.command}", f"  示例：{row.example}", f"  说明：{row.description}"]
    lines.append("活动状态参数（/baonly query status）：" + " / ".join(f"{k}={v}" for k, v in STATUSES))
    lines += [f"提示：{tip}" for tip in TIPS]
    return "\n".join(lines)


class HelpCardService:
    def __init__(self, renderer: CardRenderer, runtime: RuntimeInfo):
        self._renderer = renderer
        self._runtime = runtime

    def html(self) -> str:
        return render_template(
            "help.html.j2",
            commands=COMMANDS,
            statuses=STATUSES,
            tips=TIPS,
            footer_text=self._runtime.footer(format_clock()),
        )

    async def render(self) -> Path:
        return await self._renderer.render(self.html(), "baonly_help_")
