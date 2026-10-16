<div align="center">

# baonly查询站 astrbot 插件

![访问计数](https://count.getloli.com/@astrbot_plugin_baonly?name=astrbot_plugin_baonly&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

**连接 [baonly查询站](https://www.baonly.cn/) 并处理数据的 astrbot 插件**

</div>

## 安装

1. 在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_baonly` 或 `Baonly 截图查询`
2. 点击安装插件
3. 或通过仓库地址安装：复制 `https://github.com/VanillaNahida/astrbot_plugin_baonly` 粘贴到 WebUI 安装

> [!NOTE]
>
> 插件依赖 `playwright` 与 `websockets`。安装后请确保已安装 Chromium 浏览器内核（如未安装，可运行 `playwright install chromium` 安装）。

## 配置

| 配置项 | 类型 | 默认值 | 说明                                                                                                                 |
|--------|------|--------|----------------------------------------------------------------------------------------------------------------------|
| `token` | string | 空 | 查询站 apikey                                                                                                        |
| `user_agent` | string | Chrome 149 UA | 无头浏览器与查询 API 使用的 User-Agent 标识                                                                          |
| `proxy_host` | string | 空 | HTTP 代理地址，为空则不使用代理                                                                                      |
| `proxy_port` | string | 空 | HTTP 代理端口号                                                                                                      |
| `proxy_username` | string | 空 | HTTP 代理认证用户名                                                                                                  |
| `proxy_password` | string | 空 | HTTP 代理认证密码                                                                                                    |
| `extra_wait_seconds` | int | 0 | 截图前额外等待的秒数                                                                                                 |
| `detail_image_enabled` | bool | true | 是否将展会详情渲染成卡片图片发送；关闭后 `/baonly detail` 与 LLM 工具仅返回文本                                      |
| `detail_render_mode` | string | `auto` | 详情图片渲染方式：`auto`（优先 AstrBot 文转图，重试全部失败后回退 Playwright）/ `astrbot` / `playwright`             |
| `detail_render_retry` | int | 3 | 每种渲染方式各自的重试次数；`auto` 模式下 AstrBot 文转图重试全部失败后自动回退 Playwright                            |
| `disable_group_push` | bool | false | 关闭群发（**仅供测试使用，正常情况下请不要开启**）：开启后活动变更不再推送到群聊，只推送到私聊订阅，并输出 INFO 日志 |
| `push_delay_seconds` | int | 0 | 推送基础延时（秒），每次推送实际叠加 0.5~1 秒随机抖动，降低风控风险                                                  |
| `ws_ping_interval` | int | 30 | WebSocket 心跳间隔（秒）                                                                                             |
| `ws_reconnect_interval` | int | 30 | WebSocket 断线重连间隔（秒）                                                                                         |
| `events_page_size` | int | 20 | 活动列表默认每页条数                                                                                                 |

## 命令总览

| 命令 | 示例用法 | 说明 |
|------|----------|------|
| `/bao` | `/bao` | 截图 Baonly 网页活动列表，默认每页 8 场 |
| `/baonly page` | `/baonly page 20` | 截图并指定每页数量（4/6/8/10/20/23/50） |
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
