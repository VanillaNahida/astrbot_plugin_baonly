"""BAOnly 插件帮助卡片：使用方法表格的 HTML 模板 + 渲染入口。

样式与展会详情卡片保持一致（同字体 Blueaka、同品牌粉配色、同页脚版本信息），
渲染同样走 ``detail_card`` 的双后端管线（AstrBot 文转图 / 本地 Playwright）。
渲染失败时由调用方回退到 :func:`build_help_text` 文本说明。
"""

import os

from .detail_card import (
    DEFAULT_RENDER_RETRY,
    _esc,
    _footer_html,
    _icon,
    build_card_document,
    render_html_card,
)

PLUGIN_NAME = "astrbot_plugin_baonly"

# 命令表格：(命令, 示例用法, 说明)
COMMAND_ROWS = (
    ("/bao", "/bao", "截图 BAOnly 活动列表页，默认每页 4 场"),
    (
        "/baonly page",
        "/baonly page 20",
        "截图活动列表页并指定每页数量，可选 4 / 6 / 10 / 20 / 23 / 50",
    ),
    (
        "/baonly query",
        "/baonly query upcoming 深圳市",
        "文本查询展会列表，可按活动状态与城市筛选",
    ),
    (
        "/baonly detail",
        "/baonly detail 广州蔚蓝档案",
        "按活动 ID 或关键词查询单个展会，返回购票链接与详情卡片图片",
    ),
    (
        "/baonly sub",
        "/baonly sub",
        "订阅当前会话，展会变更时自动推送（需管理员）",
    ),
    ("/baonly unsub", "/baonly unsub", "取消订阅当前会话（需管理员）"),
    (
        "/baonly status",
        "/baonly status",
        "查看推送连接状态（连接时长 / API Key 有效性 / 最近推送）",
    ),
    ("/baonly list", "/baonly list", "查看全部订阅渠道（群聊 / 私聊）"),
    ("/baonly help", "/baonly help", "查看本帮助（使用方法表格图片）"),
)

# 活动状态筛选参数：(参数, 中文说明)
STATUS_ROWS = (
    ("upcoming", "即将举行"),
    ("ongoing", "进行中"),
    ("past", "已结束"),
    ("all", "全部"),
)

# 使用提示
TIP_ROWS = (
    "命令在群聊与私聊中均可使用，仅 sub / unsub 需要管理员权限",
    "也可以直接用自然语言提问，例如「广州有哪些蔚蓝档案活动？」，插件已注册 LLM 工具",
    "订阅渠道也可在 AstrBot WebUI 插件详情页的「订阅管理」中维护",
    "展会数据来源：https://www.baonly.cn",
)

_HELP_CSS = """
.help-hero {
  background: linear-gradient(135deg, #E94E99 0%, #F48FB1 100%);
  color: #FFFFFF; padding: 24px 16px 44px;
}
.help-hero-title { font-size: 22px; font-weight: 700; line-height: 1.3; }
.help-hero-sub { font-size: 12px; line-height: 1.5; margin-top: 6px; opacity: 0.92; }
table.cmds { width: 100%; border-collapse: collapse; table-layout: fixed; }
table.cmds th {
  font-size: 12px; font-weight: 700; color: #E94E99; background: #FCE4EC;
  text-align: left; padding: 7px 8px;
}
table.cmds th.col-cmd { width: 47%; }
table.cmds td {
  padding: 8px; vertical-align: top; border-bottom: 1px solid #F2F2F2;
}
table.cmds tr:last-child td { border-bottom: none; }
td.cmd code {
  display: inline-block; font-size: 11.5px; font-weight: 700; color: #E94E99;
  background: #FCE4EC; border-radius: 6px; padding: 2px 6px;
  font-family: Consolas, "SFMono-Regular", Menlo, monospace;
}
td.cmd .eg {
  display: block; margin-top: 5px; font-size: 10.5px; color: #9E9E9E;
  line-height: 1.5; word-break: break-word;
}
td.exp { font-size: 12px; color: #333333; line-height: 1.65; }
.status-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.status-chips .chip { background: #FCE4EC; color: #E94E99; }
.status-chips code { font-family: Consolas, "SFMono-Regular", Menlo, monospace; }
.tips { display: flex; flex-direction: column; gap: 8px; }
.tip { display: flex; gap: 6px; font-size: 12px; color: #333333; line-height: 1.6; }
.tip .tic { flex: 0 0 14px; height: 14px; color: #E94E99; display: flex; }
"""


def _section(title: str, icon_name: str, inner: str) -> str:
    return (
        '<div class="section"><h2><span class="hic">{icon}</span>{title}</h2>'
        "{inner}</div>"
    ).format(icon=_icon(icon_name, 18), title=_esc(title), inner=inner)


def _command_table_html() -> str:
    rows = []
    for command, example, desc in COMMAND_ROWS:
        rows.append(
            '<tr><td class="cmd"><code>{cmd}</code>'
            '<span class="eg">示例：{eg}</span></td>'
            '<td class="exp">{desc}</td></tr>'.format(
                cmd=_esc(command), eg=_esc(example), desc=_esc(desc)
            )
        )
    return (
        '<table class="cmds"><thead><tr>'
        '<th class="col-cmd">命令 / 示例</th><th>说明</th>'
        "</tr></thead><tbody>{rows}</tbody></table>"
    ).format(rows="".join(rows))


def _status_chips_html() -> str:
    chips = "".join(
        '<span class="chip"><code>{key}</code><span>{label}</span></span>'.format(
            key=_esc(key), label=_esc(label)
        )
        for key, label in STATUS_ROWS
    )
    return '<div class="status-chips">{}</div>'.format(chips)


def _tips_html() -> str:
    return '<div class="tips">{}</div>'.format(
        "".join(
            '<div class="tip"><span class="tic">{}</span><span>{}</span></div>'.format(
                _icon("badge-check", 14), _esc(tip)
            )
            for tip in TIP_ROWS
        )
    )


def build_help_card_html(
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
) -> str:
    """把使用帮助渲染为完整 HTML 字符串。"""
    body = "".join(
        [
            '<div class="help-hero">'
            '<div class="help-hero-title">BAOnly 插件帮助</div>'
            '<div class="help-hero-sub">蔚蓝档案同人 ONLY 展会 · '
            "截图 / 查询 / 订阅推送</div></div>",
            '<div class="body">',
            _section("命令列表", "file-text", _command_table_html()),
            _section("活动状态参数", "clock", _status_chips_html()),
            _section("使用提示", "info", _tips_html()),
            _footer_html(astrbot_version, plugin_name, plugin_version),
            "</div>",
        ]
    )
    return build_card_document(body, _HELP_CSS)


def build_help_text() -> str:
    """帮助文本（图片渲染失败时的兜底输出）。"""
    lines = ["BAOnly 插件使用帮助："]
    for command, example, desc in COMMAND_ROWS:
        lines.append(f"- {command}")
        lines.append(f"  示例：{example}")
        lines.append(f"  说明：{desc}")
    lines.append("活动状态参数（/baonly query status）：" + " / ".join(
        f"{key}={label}" for key, label in STATUS_ROWS
    ))
    lines.extend(f"提示：{tip}" for tip in TIP_ROWS)
    return "\n".join(lines)


async def render_help_card(
    mode: str = "auto",
    retry: int = DEFAULT_RENDER_RETRY,
    output_dir: str = "",
    user_agent: str = "",
    astrbot_version: str = "",
    plugin_name: str = "",
    plugin_version: str = "",
    proxy_host: str = "",
    proxy_port: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> str:
    """渲染帮助卡片，返回本地图片路径。"""
    html_text = build_help_card_html(
        astrbot_version, plugin_name, plugin_version
    )
    output_dir = output_dir or os.path.join(
        os.path.abspath("data"), "temp", PLUGIN_NAME
    )
    return await render_html_card(
        html_text,
        output_dir=output_dir,
        filename_prefix="baonly_help_",
        mode=mode,
        retry=retry,
        user_agent=user_agent,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        proxy_username=proxy_username,
        proxy_password=proxy_password,
    )
