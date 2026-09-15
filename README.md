# BAOnly 截图查询

![访问计数](https://count.getloli.com/@astrbot_plugin_baonly?name=astrbot_plugin_baonly&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)
  
> [!TIP]
> 与你的日常，便是奇迹！

一个专为蔚蓝档案玩家打造的 BAOnly（蔚蓝档案 ONLY 同人展）活动查询与截图插件，支持 Playwright 无头浏览器截图 BAOnly 活动列表页，并通过 BAOnly 公开 API 为 AI 提供活动信息查询能力。

<p align="center">
  <img width="1080" alt="image" src="https://github.com/user-attachments/assets/e71a1d99-c1cf-41c7-ba01-1f23aed20231" />
</p>

<div align="center">

[![License](https://img.shields.io/github/license/VanillaNahida/astrbot_plugin_baonly?style=flat-square)](https://github.com/VanillaNahida/astrbot_plugin_baonly/blob/main/LICENSE)
[![Stars](https://img.shields.io/github/stars/VanillaNahida/astrbot_plugin_baonly?style=flat-square)](https://github.com/VanillaNahida/astrbot_plugin_baonly/stargazers)
[![Forks](https://img.shields.io/github/forks/VanillaNahida/astrbot_plugin_baonly?style=flat-square)](https://github.com/VanillaNahida/astrbot_plugin_baonly/network)
[![Issues](https://img.shields.io/github/issues/VanillaNahida/astrbot_plugin_baonly?style=flat-square)](https://github.com/VanillaNahida/astrbot_plugin_baonly/issues)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat-square)](https://www.python.org/)
[![作者](https://img.shields.io/badge/%E4%BD%9C%E8%80%85-VanillaNahida-green)](https://github.com/VanillaNahida)

</div>

# 功能特性

- **Playwright 网页截图**：通过无头 Chromium 访问 [BAONLY 查询站](https://www.baonly.cn/)，截图活动列表页并直接发送到聊天中
- **可调每页数量**：支持 4 / 6 / 10 / 20 / 23 / 50 场每页，适配不同展示需求
- **HTTP 代理支持**：可配置代理服务器访问目标站点，支持代理认证
- **LLM 工具提供的活动查询**：接入 BAOnly 公开 API，为 AI 提供活动查询能力，可回答活动时间、地点、票价、售票状态、主办方等问题。
- **城市与状态筛选**：API 查询支持按城市、按活动状态（即将举行 / 进行中 / 已结束 / 全部）筛选

# 原理

插件注册 `bao` / `baonly` 命令用于网页截图，并注册一个名为 `baonly_query_events` 的 LLM 工具供 AI 调用查询活动数据。

截图流程通过 Playwright 无头浏览器完成：先访问活动列表页并注入反调试脚本，关闭公告弹窗后按需切换每页显示数量，随后滚动页面触发懒加载并等待所有图片解码完成，最后注入页脚水印后整页截图并回传。

> [!TIP]
> 内置API需要鉴权才能调用，若需要获取Token，请加群[295829474](https://qm.qq.com/q/o6IqrmBh9S)，并联系群管理员`丐陌nya~`(10510544)获取。

```
截图流程:
/bao 或 /baonly page 4
    ↓
Playwright 无头 Chromium 访问 https://www.baonly.cn/
    ↓
注入反调试脚本 → 关闭公告弹窗 → 设置每页数量(默认4场/页)
    ↓
滚动页面触发懒加载 → 等待图片全部解码
    ↓
注入页脚水印(时间/来源/版本/作者)
    ↓
整页截图 → data/temp/astrbot_plugin_baonly/*.png → 发送图片

API 查询流程(AI 调用 LLM 工具):
baonly_query_events(status, include_past, city)
    ↓
GET https://api.baonly.cn/api/public/events
    携带 Bearer Token 与自定义 UA
    ↓
解析 events 数据 → 活动名称/时间/地点/票价/售票状态/主办方/标签
    ↓
返回 JSON 给 AI 回答用户
```

# 使用方法

## 安装

1. 在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_baonly` 或 `BAOnly 截图查询`
2. 点击安装插件
3. 或者通过仓库地址安装：复制 `https://github.com/VanillaNahida/astrbot_plugin_baonly` 粘贴到 WebUI 安装

> [!NOTE]
>
> 插件依赖 `playwright`，安装插件后请确保已安装 Chromium 浏览器内核（如未安装，可运行 `playwright install chromium` 安装）。

## 配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `user_agent` | string | Chrome 149 UA | 无头浏览器请求网页时使用的 User-Agent 标识 |
| `token` | string | 内置默认值 | 调用 BAOnly API 时使用的 Bearer Token，用于 Authorization 请求头 |
| `proxy_host` | string | （空） | HTTP 代理地址，为空则不使用代理 |
| `proxy_port` | string | （空） | HTTP 代理端口号 |
| `proxy_username` | string | （空） | HTTP 代理认证用户名，为空则不认证 |
| `proxy_password` | string | （空） | HTTP 代理认证密码 |
| `extra_wait_seconds` | int | 0 | 截图前额外等待的秒数，用于等待异步加载的资源 |

## 命令总览

| 命令 | 示例用法 | 权限要求 | 说明 |
|------|----------|----------|------|
| `/bao` | `/bao` | 无 | 截图 BAOnly 网页活动列表，默认每页 4 场 |
| `/baonly page` | `/baonly page 20` | 无 | 截图活动列表并指定每页显示数量，可选 `4/6/10/20/23/50` |

截图完成后图片将直接发送到当前会话，无需额外操作。

## LLM 工具（API 查询）

插件会自动注册 `baonly_query_events` 工具供 AI 调用，无需手动触发。AI 可以根据对话内容自动查询并回答：

- 近期蔚蓝档案 ONLY / 同人展活动（即将举行 / 进行中 / 已结束 / 全部）
- 活动时间、举办城市、场馆地址、票价区间
- 售票状态（预售中 / 已售罄 / 未开售 / 待定）、主办方、标签
- 指定城市筛选，例如"广州有哪些蔚蓝档案活动？"

### 查询参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `status` | string | 活动状态筛选：`upcoming`（即将举行）/ `ongoing`（进行中）/ `past`（已结束）/ `all`（全部），默认 `upcoming` |
| `include_past` | boolean | 是否包含已结束的活动，默认 `false` |
| `city` | string | 按城市名称筛选活动，例如 `深圳市`、`上海市`、`广州市`，不填返回全部城市 |

# 独立命令行工具

插件附带 `screenshot.py`，可在不启动 AstrBot 的情况下本地运行并调试截图功能：

```bash
# 截取第一页（默认 4 场/页）
python screenshot.py

# 指定每页数量
python screenshot.py --page-size 20

# 截取指定页码
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
- QQ群：
  - 三群：195260107
  - 四群：1074471035

# QQ 群

- 一群：621457510
- 二群：1031065631
- 三群：195260107（推荐）
- 四群：1074471035

# Star History

[![Star History Chart](https://api.star-history.com/svg?repos=VanillaNahida/astrbot_plugin_baonly&type=Date)](https://star-history.com/#VanillaNahida/astrbot_plugin_baonly&Date)
