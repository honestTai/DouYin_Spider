<div align="center">
  <img width="160" src="./author/logo.jpg" alt="Douyin Multi-Agent MCP">

  # Douyin Multi-Agent MCP

  **多账号、独立浏览器环境、图片评论与定时调度的抖音 MCP 服务**

  [![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
  [![MCP](https://img.shields.io/badge/MCP-stdio-6c5ce7)](https://modelcontextprotocol.io/)
  [![SQLite](https://img.shields.io/badge/SQLite-local-044a64)](https://www.sqlite.org/)
  [![Agents](https://img.shields.io/badge/Kimi%20%C2%B7%20Codex%20%C2%B7%20Claude-success)](#安装到-agent)

</div>

> 这是基于 `cv-cat/Douyin_Spider` 深度定制的独立分支，不再只是上游采集接口的简单封装。项目使用抖音 Web 私有接口，不是官方开放 API。默认仅预览；真实评论必须显式确认。请仅在已授权账号和内容上使用，并遵守平台规则及适用法律。

## ❤️ Sponsor：HRouter

**[HRouter](https://hrouter.net/home)** 是本项目维护者正在建设的模型接入、API Key 管理与用量跟踪平台，面向 AI 编码和应用开发。

- **统一模型接入**：Claude、GPT、Gemini、Grok、DeepSeek、Qwen 等主流模型，一套 API 即可调用。
- **按量使用**：无需分别订阅多个服务，充值余额、创建 API Key，即可按实际用量调用。
- **请求可追溯**：集中管理密钥、模型路由和调用记录，便于核对成本与排查问题。
- **与 MCP 配合**：HRouter 负责模型接入与用量管理，本项目负责本地浏览器、抖音执行与账号数据，二者独立部署。

**[访问 HRouter 官网 →](https://hrouter.net/home)** · **[了解 HRouter Desktop →](https://github.com/honestTai/HRouter-Desktop)**

## 核心能力

- **多账号独立执行**：每个账号拥有自己的关键词、评论文字、图片、环境、IP、限额和执行历史。
- **高赞低评筛选**：按最多点赞建立候选池，再按互动比值选择目标。
- **文字与图片评论**：支持文字、图片、文字加图片，以及指定作品定向评论。
- **多种浏览器环境**：AdsPower、本机 Chrome WebBridge、Chromium CDP、Firefox WebDriver BiDi。
- **独立 IP**：AdsPower 自动读取环境代理；本地账号可配置独立 HTTP/SOCKS5 代理。
- **定时调度**：独立后台进程、全局限速、账号轮换、每日限额、风控熔断。
- **SQLite 数据**：账号策略、作品去重、运行记录、调度配置均持久化保存。
- **Agent 数据查询**：直接查看账号状态、候选作品、点赞数、评论数、上传 URI 和失败原因。

## 账号隔离规则

每个账号分别配置并独立轮换：

```text
搜索关键词
评论文字
评论图片
浏览器环境
代理/IP
小时与每日限额
作品去重状态
```

去重按 `(account_id, aweme_id)` 保存：

- 同一账号不会重复评论同一作品。
- 不同账号可以评论同一作品。
- 全局只共享调度频率和最小执行间隔，不共享内容或作品去重状态。

## 快速开始

### 1. 获取项目

```bash
git clone -b feature/mcp-engagement https://github.com/honestTai/DouYin_Spider.git
cd DouYin_Spider
python3.10 -m venv .venv
```

macOS / Linux 下文使用 `.venv/bin/python`；Windows 替换为 `.venv\Scripts\python.exe`。

### 2. 安装依赖

```bash
.venv/bin/python -m pip install --use-deprecated=legacy-resolver -r requirements.txt
.venv/bin/python -m pip install 'protobuf>=5.27'
```

### 3. 配置单账号凭据

复制 `.env.example` 为 `.env`，填写当前账号的浏览器凭据：

```bash
DY_COOKIES=''
DY_TICKET=''
DY_TS_SIGN=''
DY_CLIENT_CERT=''
DY_PRIVATE_KEY=''
DY_DTRAIT_BLOB=''
```

这些值必须来自同一次浏览器登录会话。多账号模式不必共享 `.env`，会在各自工作进程中从对应浏览器环境读取。

### 4. 验证 MCP

```bash
.venv/bin/python mcp_server.py
```

服务通过标准输入输出通信，启动后等待 MCP 客户端连接，不会主动评论或私信。

## 安装到 Agent

```bash
# Kimi Code：当前项目 .kimi-code/mcp.json
.venv/bin/python -m dy_mcp.install --agent kimi

# Codex
.venv/bin/python -m dy_mcp.install --agent codex

# Claude Code
.venv/bin/python -m dy_mcp.install --agent claude

# 输出通用 JSON
.venv/bin/python -m dy_mcp.install --agent json
```

安装后重启 Agent 或新开会话。Kimi Code 可用 `/mcp` 查看连接状态。

## MCP 工具

| 工具 | 用途 |
| :--- | :--- |
| `run_engagement` | 单账号搜索、文字/图片评论，可选作者私信 |
| `list_adspower_profiles` | 列出 AdsPower 环境，不返回 Cookie 或代理密码 |
| `upsert_account` | 新增或更新独立账号、环境、关键词、文案、图片和限额 |
| `refresh_account_runtime` | 首次从已登录浏览器保存 Cookie、签名参数和指纹；失效后重新绑定 |
| `list_accounts` | 查看账号配置、凭证保存状态、小时/每日评论数和最近结果 |
| `run_account_once` | 独立进程搜索预览或真实评论；支持 `aweme_id` 定向执行 |
| `configure_scheduler` | 查询、启动、停止定时调度并调整频率 |
| `list_activity` | 查询 SQLite 中的真实运行记录 |

所有执行类工具默认 `dry_run=true`。真实评论必须同时设置：

```json
{
  "dry_run": false,
  "confirm": true
}
```

## 单账号搜索与评论

```json
{
  "query": "AI Claude",
  "comment_text": "这家claude是纯血的,0注入",
  "message_text": "",
  "limit": 1,
  "dry_run": true,
  "sort_type": "1"
}
```

- `sort_type`：`0` 综合、`1` 最多点赞、`2` 最新发布。
- `publish_time`：`0` 不限、`1` 一天内、`7` 一周内、`180` 半年内。
- `message_text` 留空时不私信。
- `comment_text` 可在仅图片评论时留空。

## 多账号配置

账号配置完成后，调用一次 `refresh_account_runtime`：

```json
{"account_id": "账号ID"}
```

该工具从绑定的已登录浏览器获取 Cookie、签名参数和指纹，并保存到本地 SQLite 的 `account_runtime` 表。`list_accounts` 只显示 `runtime_status` 和 `runtime_saved_at`，不会返回凭证内容；数据库已排除在 Git 之外，不要分享该文件。

保存成功后，搜索、上传图片、评论和定时调度均直接使用本地凭证，不再访问浏览器，浏览器可以关闭。登录失效或凭证不可用时，运行记录会返回错误，账号进入 `authentication_required` 状态并暂停调度；重新打开对应浏览器登录后，再次调用 `refresh_account_runtime` 即可恢复。遇到二次验证则进入 `verification_required`，应先完成验证再刷新凭证。

### AdsPower

在 `.env` 中配置本地 API：

```bash
ADSPOWER_PORT='50325'
ADSPOWER_API_KEY=''
```

绑定示例：

```json
{
  "name": "账号 A",
  "browser_type": "adspower",
  "profile_no": "11",
  "keywords": ["AI Claude", "Claude Code"],
  "comment_texts": ["文案 A"],
  "image_paths": ["/absolute/path/to/a.png"]
}
```

AdsPower 的代理配置会同时用于搜索、签名和图片上传、评论请求，避免浏览器与 API 出口不一致。

### 本机 Chrome / WebBridge

```json
{
  "name": "账号 B",
  "browser_type": "webbridge",
  "keywords": ["Claude Code"],
  "comment_texts": ["文案 B"],
  "image_paths": ["/absolute/path/to/b.png"]
}
```

WebBridge 使用当前已连接的 Chrome 登录会话，不需要额外调试端口。

### Chrome / Edge CDP

先关闭对应浏览器的全部进程，再使用调试端口启动：

```bash
# Chrome
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222

# Edge
"/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  --remote-debugging-port=9223
```

账号配置：

```json
{
  "name": "Edge 账号",
  "browser_type": "edge",
  "cdp_url": "http://127.0.0.1:9223",
  "proxy_url": "http://127.0.0.1:8080",
  "keywords": ["Claude"],
  "comment_texts": ["Edge 独立文案"]
}
```

`proxy_url` 必须与该浏览器的真实网络出口一致；只修改 API 代理并不能改变浏览器出口。

### Firefox BiDi

```bash
firefox --remote-debugging-port 9224
```

```json
{
  "name": "Firefox 账号",
  "browser_type": "firefox",
  "cdp_url": "ws://127.0.0.1:9224/session",
  "keywords": ["Claude"],
  "comment_texts": ["Firefox 独立文案"]
}
```

Firefox 使用 WebDriver BiDi，不使用 Chromium CDP。

## 高赞低评与定向评论

多账号模式先按最多点赞获取候选池，再计算：

```text
score = digg_count / (comment_count + 1)
```

账号也可设置 `content_strategy="latest"` 使用截评策略：搜索最近 24 小时内内容（`sort_type=2`、`publish_time=1`），保留接口的最新发布顺序，不再按互动比值重排。点赞下限、评论上限和账号级去重仍然生效。最新搜索无候选时会继续遍历该账号的剩余关键词，并回退到高赞低评搜索；全部搜索仍无候选时记录 `no_candidates`，不重复评论旧作品。

默认配置：

```text
candidate_pool_size = 20
min_digg_count = 100
max_comment_count = 100
per_hour_limit = 5
per_day_limit = 20
batch_size = 1
batch_interval_seconds = 15
```

`batch_size` 是每轮最多评论的作品数（1–10），`batch_interval_seconds` 是同一轮作品之间的等待秒数（0–300）。实际批量大小会同时受全局每小时、账号每小时和账号每日剩余额度限制，不会因批量而突破限额。不同作品评论成功后会分别记录到 SQLite；任一作品失败会立即停止本轮后续评论，遇到二次验证会暂停该账号的调度。以上数值均可通过 `upsert_account` 和 `configure_scheduler` 修改，无需改代码。

返回的每个候选作品包含作品链接、标题、作者、点赞数、评论数和得分。搜索候选会随时间变化；已确认目标后可跳过搜索：

```json
{
  "account_id": "账号ID",
  "aweme_id": "作品ID",
  "dry_run": false,
  "confirm": true
}
```

## 图片评论

支持：

- 纯文字评论
- 纯图片评论
- 文字加图片评论
- 多账号图片轮换
- 定向图片评论

单账号示例：

```json
{
  "query": "AI Claude",
  "comment_text": "这家claude是纯血的,0注入",
  "image_path": "/absolute/path/to/image.png",
  "limit": 1,
  "dry_run": false,
  "confirm": true
}
```

当前网页每张评论选择一张图片：

- 格式：`png`、`jpeg`、`webp`、`bmp`
- 大小：不超过 `10MB`
- 宽高：均不超过 `10000` 像素

上传链路与创作者发布和私信图片不同：

```text
GET /aweme/v1/web/comment/upload/auth/
→ ImageX ApplyImageUpload
→ TOS 字节上传
→ ImageX CommitImageUpload
→ /aweme/v1/web/comment/publish
```

发布字段为 `image_uri_list`、`image_widths`、`image_heights`、`image_formats`。真实结果中的 `image_upload` 返回实际上传 URI、宽高和格式；预览不会上传图片。

## 定时调度

调度器是独立后台进程，不依赖 stdio MCP 持续在线；账号凭证保存成功后也不依赖浏览器在线。默认配置：

```text
enabled = false
dry_run = true
global_per_hour = 20
min_interval_seconds = 180
poll_seconds = 15
```

启动预览调度：

```json
{
  "action": "start",
  "dry_run": true,
  "global_per_hour": 20,
  "min_interval_seconds": 180
}
```

启动真实评论调度：

```json
{
  "action": "start",
  "dry_run": false,
  "global_per_hour": 20,
  "min_interval_seconds": 180,
  "confirm": true
}
```

停止：

```json
{
  "action": "stop"
}
```

调度器优先选择最久未执行且状态正常的账号，串行执行以避免突发并发。出现二次身份验证时，账号进入 `verification_required` 并暂停后续自动执行；人工处理后更新账号恢复。频率配置不保证降低风控概率。

## 数据与日志

```text
.kimi-code/douyin.db       SQLite 账号、策略、去重、运行历史与调度配置
.kimi-code/scheduler.log   调度日志
.kimi-code/scheduler.pid   调度进程状态
```

数据库不保存 Cookie、浏览器私钥或 AdsPower API Key。本地配置、数据库和调度状态均已加入 `.gitignore`。

## 主要返回数据

搜索预览可能包含：

```json
{
  "status": "preview",
  "aweme_id": "作品ID",
  "digg_count": 78006,
  "comment_count": 17,
  "score": 4333.67
}
```

真实图片评论可能包含：

```json
{
  "status": "completed",
  "comment_status": "published",
  "image_upload": {
    "image_uri_list": "实际上传URI",
    "image_widths": 3432,
    "image_heights": 1766,
    "image_formats": "png"
  }
}
```

账号查询返回 `comments_last_hour`、`comments_today`、最近运行状态及错误；历史查询返回 `run_id`、候选数、选中作品和起止时间。

## 项目结构

```text
mcp_server.py                 MCP stdio 启动入口
dy_apis/
├── douyin_api.py             搜索、文字/图片评论与私信接口
└── douyin_comment_media.py   评论图片 STS、ImageX 上传与字段转换
dy_mcp/
├── server.py                 7 个 MCP 工具
├── workflow.py               单账号执行流程
├── engine.py                 多账号筛选、独立去重与风控熔断
├── adspower.py               AdsPower MCP、CDP 与代理采集
├── browser_runtime.py        WebBridge、Chromium CDP、Firefox BiDi
├── store.py                  SQLite 配置、限额、去重与历史
├── scheduler.py              独立定时调度进程
├── worker.py                 账号独立工作进程
├── session.py                单账号会话
├── proxy_pool.py             稳定代理配置
└── install.py                多 Agent 安装器
tests/                        离线单元与流程测试
```

## 测试与部署检查

```bash
.venv/bin/python -m pytest -q \
  tests/test_comment_media.py \
  tests/test_engagement_workflow.py \
  tests/test_multiaccount.py \
  tests/test_browser_runtime.py \
  tests/test_adspower.py \
  tests/test_mcp_proxy_pool.py \
  tests/test_mcp_installer.py \
  tests/test_dtrait_profile.py::test_fingerprint_platform_env_overrides \
  tests/test_search_filters.py \
  tests/test_write_dtrait.py
```

本地部署：

```bash
.venv/bin/python -m dy_mcp.install --agent kimi
```

重新启动 Agent 后即可使用新工具。真实浏览器验证应先预览，再对明确账号、作品、文字和图片执行一次真实评论。

Docker 启动入口同样是 `mcp_server.py`。容器内 MCP 使用 stdio；AdsPower、WebBridge 和本地浏览器调试服务需要在容器外部单独提供网络连接。

## 上游致谢

本项目是 **[cv-cat/Douyin_Spider](https://github.com/cv-cat/Douyin_Spider)** 的 fork。感谢原作者及贡献者开放数据采集、认证、签名、评论和私信等基础实现。

当前 `feature/mcp-engagement` 分支由 **[honestTai](https://github.com/honestTai)** 深度定制，新增多 Agent 接入、多账号独立执行、AdsPower 与本地浏览器环境、SQLite、图片评论、作品级去重和定时调度。原项目相关权利与使用要求仍归原项目及相应权利人所有。

本项目仅供学习与技术研究。使用者需要自行确认账号授权、内容合规、平台规则及适用法律，不得用于发布不良信息、垃圾互动或骚扰他人。
