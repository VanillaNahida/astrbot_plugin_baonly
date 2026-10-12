# BAOnly 截图查询

![访问计数](https://count.getloli.com/@astrbot_plugin_baonly?name=astrbot_plugin_baonly&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

一个专为蔚蓝档案玩家打造的 BAOnly（蔚蓝档案 ONLY 同人展）活动查询、截图与订阅推送插件。已全面迁移至 `www.baonly.cn`。

# 功能特性

- **Playwright 网页截图**：通过无头 Chromium 访问 [BAONLY 查询站](https://www.baonly.cn/)，截图活动列表页并直接发送到聊天中
- **可调每页数量**：支持 4 / 6 / 10 / 20 / 23 / 50 场每页，适配不同展示需求
- **HTTP 代理支持**：可配置代理服务器访问目标站点，支持代理认证
- **LLM 工具 + 命令双通道查询**：接入 BAOnly 公开 API，AI 和命令均可查询展会列表与详情
- **多维度筛选**：API 查询支持按城市 / 省份 / 大区 / 标签 / 运营标记（已取消 / 已延期 / 地点变更）/ 活动状态（即将举行 / 进行中 / 已结束 / 全部）筛选，并支持按距离排序
- **展会详情卡片图片**：`/baonly detail` 同时支持活动 ID 与关键词（标题 / 主办方 / 城市 / 场馆）检索，命中后渲染移动端详情卡片图片（时间、地点、票价、票档、嘉宾），并附上 BAOnly 活动页面链接与购票链接
- **帮助卡片图片**：`/baonly help` 把全部命令、示例与使用提示渲染成表格图片发送，样式与详情卡片一致
- **WebSocket 订阅推送**：长连接订阅活动变更（新增/修改/删除、公告、维护），并按各「群聊 / 私聊」会话配置主动推送
- **WebUI 插件页管理订阅**：在插件详情页简洁管理订阅渠道

# 原理

插件注册 `bao` / `baonly` 命令用于网页截图与查询，并注册 `baonly_query_events`、`baonly_event_detail` 两个 LLM 工具供 AI 调用。

截图流程通过 Playwright 无头浏览器完成：先访问活动列表页并注入反调试脚本，关闭公告弹窗与新手引导，按需切换每页显示数量，随后滚动页面触发懒加载并等待所有图片解码完成，最后注入页脚水印后整页截图并回传。

订阅推送：插件启动时建立 `wss://www.baonly.cn/api/public/stream` 长连接，推送消息自带 `eventId`（合并消息为 `eventIds` 数组）与可选的 `note` 备注；插件按 ID 拉取 `GET /api/public/events/{eventId}`，只对比这些活动并推送变更（仅推送 WS 下发的活动）。断线后自动重连，重连时做一次全量对齐，只刷新本地缓存基线、不推送。

> [!TIP]
> 内置 API 需要鉴权才能调用。若需获取 Token，请加群并联系管理员获取。

# 使用方法

## 安装

1. 在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_baonly` 或 `BAOnly 截图查询`
2. 点击安装插件
3. 或通过仓库地址安装：复制 `https://github.com/VanillaNahida/astrbot_plugin_baonly` 粘贴到 WebUI 安装

> [!NOTE]
>
> 插件依赖 `playwright` 与 `websockets`。安装后请确保已安装 Chromium 浏览器内核（如未安装，可运行 `playwright install chromium` 安装）。

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `token` | string | 空 | BAOnly beta 站 API Key，用于 `x-api-key` 请求头（查询 + WebSocket 订阅握手），需 `stream:events` 权限才能收到推送 |
| `user_agent` | string | Chrome 149 UA | 无头浏览器与查询 API 使用的 User-Agent 标识 |
| `proxy_host` | string | 空 | HTTP 代理地址，为空则不使用代理 |
| `proxy_port` | string | 空 | HTTP 代理端口号 |
| `proxy_username` | string | 空 | HTTP 代理认证用户名 |
| `proxy_password` | string | 空 | HTTP 代理认证密码 |
| `extra_wait_seconds` | int | 0 | 截图前额外等待的秒数 |
| `detail_image_enabled` | bool | true | 是否将展会详情渲染成卡片图片发送；关闭后 `/baonly detail` 与 LLM 工具仅返回文本 |
| `detail_render_mode` | string | `auto` | 详情图片渲染方式：`auto`（优先 AstrBot 文转图，重试全部失败后回退 Playwright）/ `astrbot` / `playwright` |
| `detail_render_retry` | int | 3 | 每种渲染方式各自的重试次数；`auto` 模式下 AstrBot 文转图重试全部失败后自动回退 Playwright |
| `disable_group_push` | bool | false | 关闭群发（**仅供测试使用，正常情况下请不要开启**）：开启后活动变更不再推送到群聊，只推送到私聊订阅，并输出 INFO 日志 |
| `push_delay_seconds` | int | 0 | 推送基础延时（秒），每次推送实际叠加 0.5~1 秒随机抖动，降低风控风险 |
| `ws_ping_interval` | int | 30 | WebSocket 心跳间隔（秒） |
| `ws_reconnect_interval` | int | 30 | WebSocket 断线重连间隔（秒） |
| `events_page_size` | int | 20 | 活动列表默认每页条数 |

## 命令总览

| 命令 | 示例用法 | 说明 |
|------|----------|------|
| `/bao` | `/bao` | 截图 BAOnly 网页活动列表，默认每页 4 场 |
| `/baonly page` | `/baonly page 20` | 截图并指定每页数量（4/6/10/20/23/50） |
| `/baonly query` | `/baonly query upcoming 深圳市` | 文本查询展会列表，可按状态、城市筛选 |
| `/baonly detail` | `/baonly detail 广州蔚蓝档案` | 查询单个展会详情。支持活动 ID，也支持标题 / 主办方 / 城市 / 场馆等关键词检索；命中后发送「活动页面链接 + 购票链接 + 详情卡片图片」 |
| `/baonly sub` | `/baonly sub` | 订阅当前会话，展会变更时自动推送（需管理员权限） |
| `/baonly unsub` | `/baonly unsub` | 取消订阅当前会话（需管理员权限） |
| `/baonly status` | `/baonly status` | 查看推送连接状态（连接时长、API Key 有效性、最近推送等） |
| `/baonly list` | `/baonly list` | 查看全部订阅渠道（群聊显示「群名+群号」，私聊显示「昵称+QQ号」） |
| `/baonly help` | `/baonly help` | 查看插件使用方法，渲染成命令表格图片发送（渲染失败时回退文本） |

命令在群聊与私聊中均可使用。仅 `/baonly sub`、`/baonly unsub` 需要管理员权限，其余命令所有人可用（也可在 AstrBot WebUI 的「指令管理」中按需调整）。

## LLM 工具

插件自动注册 `baonly_query_events`（列表查询）、`baonly_event_detail`（详情查询）与 `baonly_event_image`（详情图片发送）三个工具供 AI 调用，无需手动触发：

- 近期蔚蓝档案 ONLY / 同人展活动（即将举行 / 进行中 / 已结束 / 全部）
- 活动时间、举办城市、省份、场馆地址、票价区间
- 指定城市 / 省份 / 大区 / 标签 / 运营标记筛选，例如「广州有哪些蔚蓝档案活动？」「有哪些活动已取消？」
- 单个展会的完整介绍、票档、嘉宾、购票链接等深入查询
- 按活动 ID 生成展会详情卡片图片并直接发送给用户（`baonly_event_image`）

## 订阅推送与插件页

- 通过 `/baonly sub` 让机器人把当前「群聊或私聊」会话加入订阅列表，之后站内发生活动变更时，机器人会主动推送变更内容到该会话。
- 推送文本：仅「更新」使用 Git Diff 记号，逐字段列出 `--- 旧值` / `+++ 新值`；新增与下架按普通字段列表输出（不加记号）。尾部固定输出「详情」链接（有则输出）与「活动ID」，WS 消息带 `note` 时在最后追加一行「备注：xxx」：

```text
[BAOnly活动更新] 广州蔚蓝档案 ONLY
--- 时间：2026.09.30 - 2026.10.01
+++ 时间：2026.10.01 - 2026.10.02
--- 标记：（无）
+++ 标记：已取消
详情：https://www.baonly.cn/event/123
活动ID：123
备注：运营放行，时间已更正
```

- 推送中的「时间」一律取接口的标准时间（`startAt` / `endAt`，服务端已按东八区归一）：单日输出 `2026.09.30`，跨天输出 `2026.09.30 - 2026.10.01`。源站原始时间文案（`timeLabel`）只在标准时间无法解析时作为回退；文案本身不含日期时（如「预计时间」「预售」）会以括号附注在标准时间之后，不会顶替标准时间。

- 只有 WS 下发的活动才会推送；断线重连时的全量对齐只刷新本地缓存基线，不会产生推送。

- 也可以在 AstrBot WebUI 的插件详情页打开「订阅管理」Page，直观地查看、新增、移除订阅渠道。
- 订阅显示名会从号码自动获取：群聊显示「群昵称 + 群号」，私聊显示「用户昵称 + QQ号」；Page 支持一键列出当前群列表，点击即可订阅。

# 独立命令行工具

插件附带 `screenshot.py`，可在不启动 AstrBot 的情况下本地运行并调试截图功能：

```bash
# 截取第一页（默认 4 场/页）
python screenshot.py

# 指定每页数量
python screenshot.py --page-size 20

# 指定页码
python screenshot.py --page 3

# 遍历所有页面截图
python screenshot.py --all

# 指定输出文件名
python screenshot.py --output baonly.png
```

| 参数 | 说明 |
|------|------|
| `--page` | 指定页码（默认第 1 页） |
| `--page-size` | 每页显示数量，可选 `4/6/10/20/23/50`（默认 4） |
| `--all` | 遍历所有页面截图 |
| `--output` | 输出文件名 |

# Bug 反馈

如果在使用过程中遇到任何问题，请通过以下方式反馈：

- https://github.com/VanillaNahida/astrbot_plugin_baonly/issues
- QQ群（见下方）

# QQ 群

- 一群：621457510
- 二群：1031065631
- 三群：195260107（推荐）
- 四群：1074471035

# Star History

[![Star History Chart](https://api.star-history.com/svg?repos=VanillaNahida/astrbot_plugin_baonly&type=Date)](https://star-history.com/#VanillaNahida/astrbot_plugin_baonly&Date)
