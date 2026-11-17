<div align="center">
  <a href="https://github.com/honestTai/DouYin_Spider/tree/feature/mcp-engagement">
    <img width="180" src="./author/logo.jpg" alt="DouYin Engagement MCP">
  </a>

  # DouYin Engagement MCP

  ### 让 Agent 按关键词找到抖音作品，在确认后完成评论与作者私信

  **一个可接入 Kimi Code、Codex、Claude Code 及其他 MCP 客户端的定制工具。**

  [![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
  [![MCP](https://img.shields.io/badge/MCP-stdio-6c5ce7)](https://modelcontextprotocol.io/)
  [![Agents](https://img.shields.io/badge/Agents-Kimi%20%C2%B7%20Codex%20%C2%B7%20Claude-success)](#-安装到-agent)

  **[快速开始](#-快速开始) · [能力](#-能力) · [安装到 Agent](#-安装到-agent) · [使用说明](#-使用说明)**

</div>

> 本项目基于抖音 Web 私有接口，不是抖音官方开放 API。默认仅预览，真实评论和私信需要显式确认。请勿用于垃圾评论、骚扰私信、违法内容或绕过平台管理。

## ❤️ Sponsor

| Sponsor | What it is |
| :--- | :--- |
| [HRouter](https://hrouter.net/home) | **[HRouter](https://hrouter.net/home)**：面向 AI 编码与应用开发的模型接入、API Key 管理和用量跟踪服务，也是本项目维护者正在建设的产品。 |

## ✨ 为什么使用它

**Agent 原生接入。** 通过标准 MCP stdio 服务，让 Agent 直接理解并调用一个边界清晰的业务工具，不需要复制接口代码或手动拼接请求。

**先预览，再执行。** 默认只返回候选作品。只有同时设置 `dry_run=false` 和 `confirm=true`，才会真正发布评论和私信。

**单一职责。** 本定制分支只突出“搜索相关作品 → 评论 → 私信作者”流程，不把直播、创作者发布等其他能力暴露给 Agent。

**会话级代理。** 同一 Cookie 固定使用同一个代理，业务请求及签名辅助请求共享出口，避免执行过程中频繁更换 IP。

## 🧭 工作流程

```mermaid
flowchart LR
    A[输入关键词与文案] --> B[搜索相关作品]
    B --> C[返回候选作品预览]
    C --> D{确认执行}
    D -->|否| E[结束，不产生写操作]
    D -->|是| F[发布作品评论]
    F --> G[私信作品作者]
    G --> H[返回分项执行状态]
```

## 🧩 能力

| 能力 | 实现方式 |
| :--- | :--- |
| 相关作品搜索 | 按关键词、排序方式和发布时间查找候选作品 |
| 发布评论 | 对候选作品逐个发布指定评论文本 |
| 作者私信 | 创建会话并向作品作者发送指定文本 |
| 执行保护 | 默认预览、显式确认、单次数量限制、失败即停 |
| 状态反馈 | 分别返回评论与私信状态，区分失败、部分完成和全部完成 |
| 代理池 | JSON 数组或逗号分隔配置；同一登录会话稳定分配代理 |
| 多 Agent 安装 | 一个安装器支持 Kimi Code、Codex、Claude Code 和通用 JSON |
| 独立启动入口 | 不依赖调用方当前目录，固定从项目根目录加载配置 |

## 🚀 快速开始

### 1. 获取分支并创建环境

```bash
git clone -b feature/mcp-engagement https://github.com/honestTai/DouYin_Spider.git
cd DouYin_Spider
python3.10 -m venv .venv
```

macOS / Linux 后续命令使用 `.venv/bin/python`；Windows 请替换为 `.venv\Scripts\python.exe`。

### 2. 安装依赖

```bash
.venv/bin/python -m pip install --use-deprecated=legacy-resolver -r requirements.txt
.venv/bin/python -m pip install 'protobuf>=5.27'
```

上游依赖 `blackboxprotobuf` 声明固定使用 `protobuf==3.10`，而项目生成的 Protobuf 代码需要 5.27 以上版本。上述顺序保留项目当前的兼容安装方式，并在最后恢复所需的 Protobuf 版本。

### 3. 配置登录与代理

```bash
cp .env.example .env
```

至少在 `.env` 中配置：

```dotenv
DY_COOKIES='你的完整登录 Cookie'
DY_TICKET=''
DY_TS_SIGN=''
DY_CLIENT_CERT=''
DY_PRIVATE_KEY=''
DY_DTRAIT_BLOB=''
DY_DTRAIT_PROFILE=''
DY_PROXY_POOL=''
```

Cookie 必须来自已登录的 `www.douyin.com`，并包含 `UIFID`。评论和私信属于写接口，通常还需要与当前 Cookie 同一次登录会话的 `ticket/ts_sign` 和 dtrait 设备素材，不能混用不同会话的旧凭据。

代理池为可选项：

```dotenv
DY_PROXY_POOL='["http://user:pass@proxy-one:8080", "http://user:pass@proxy-two:8080"]'
```

`.env` 已加入 Git 忽略。不要把 Cookie、私钥或代理密码提交到仓库，也不要直接粘贴到 Agent 对话中。

## 🔌 安装到 Agent

在项目根目录使用虚拟环境 Python 执行安装器。安装器只写启动配置，不复制登录凭据。

| Agent | 安装命令 | 配置范围 |
| :--- | :--- | :--- |
| Kimi Code | `.venv/bin/python -m dy_mcp.install --agent kimi` | 当前项目 `.kimi-code/mcp.json` |
| Codex | `.venv/bin/python -m dy_mcp.install --agent codex` | Codex 用户级 MCP 配置 |
| Claude Code | `.venv/bin/python -m dy_mcp.install --agent claude` | 当前项目的 local 配置 |

一次安装全部：

```bash
.venv/bin/python -m dy_mcp.install --agent all
```

某个 Agent CLI 不存在时，`all` 会继续安装其他 Agent，最后以非零状态报告未完成的安装。

其他 MCP 客户端可以输出通用 JSON：

```bash
.venv/bin/python -m dy_mcp.install --agent json
```

安装后重新启动 Agent 或新开会话：

- **Kimi Code**：输入 `/mcp` 查看连接状态。
- **Codex**：执行 `codex mcp list`，或在 TUI 中输入 `/mcp`。
- **Claude Code**：执行 `claude mcp list`；如果提示项目信任或服务器审批，先核对启动命令再确认。

也可以直接验证 stdio 服务：

```bash
.venv/bin/python mcp_server.py
```

该命令通过标准输入输出通信，正常启动后等待 MCP 客户端连接，不会主动执行评论或私信。

## 🛠️ 使用说明

MCP 服务只暴露一个工具：`run_engagement`。

### 参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `query` | 必填 | 搜索关键词 |
| `comment_text` | 必填 | 发布到每个候选作品的评论文本 |
| `message_text` | 必填 | 发送给每个作品作者的私信文本 |
| `limit` | `3` | 最多处理作品数，范围 1–20 |
| `dry_run` | `true` | 是否只搜索和预览 |
| `confirm` | `false` | 真实执行确认 |
| `sort_type` | `0` | `0` 综合、`1` 最多点赞、`2` 最新发布 |
| `publish_time` | `0` | `0` 不限、`1` 一天内、`7` 一周内、`180` 半年内 |
| `interval_seconds` | `3.0` | 每个作品之间的等待秒数，范围 0–60 |

### 第一步：只预览

直接对 Agent 说：

```text
使用 douyin-engagement 搜索“榴莲”相关作品，limit=1，dry_run=true。
评论文案为“这个内容很有帮助”，私信文案为“你好，想请教一下相关问题”。
只返回预览，不实际评论或私信。
```

等价的工具参数：

```json
{
  "query": "榴莲",
  "comment_text": "这个内容很有帮助",
  "message_text": "你好，想请教一下相关问题",
  "limit": 1,
  "dry_run": true
}
```

### 第二步：确认执行

核对候选作品和文案后，在同一会话中要求 Agent 使用相同参数，并明确修改：

```json
{
  "dry_run": false,
  "confirm": true
}
```

建议第一次真实执行保持 `limit=1`，确认账号凭据、代理和目标均符合预期后再考虑扩大范围。

### 执行结果

- `comment_status`：`pending`、`published` 或 `failed`。
- `message_status`：`pending`、`sent` 或 `failed`。
- `completed`：本次请求的作品均已完成评论和私信。
- `partial`：已有部分写操作成功，但流程中途失败。
- `failed`：没有写操作成功。
- `stopped_on_error`：是否因任一作品失败而停止后续处理。

## 🗂️ 定制部分结构

```text
mcp_server.py                 # 与调用目录无关的 stdio 启动入口
dy_mcp/
├── server.py                 # MCP 工具定义
├── workflow.py               # 搜索、评论、私信流程
├── session.py                # 登录会话与项目级 .env 加载
├── proxy_pool.py             # 会话固定代理分配
└── install.py                # 多 Agent 安装器
tests/
├── test_engagement_workflow.py
├── test_mcp_proxy_pool.py
└── test_mcp_installer.py
```

原项目的数据采集、直播、创作者发布等代码仍保留在仓库中，但不会通过本 MCP 服务暴露。上游 `main.py` 当前包含主动私信示例，不要把它当作本 MCP 的启动入口。

## 🧪 开发验证

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest -q \
  tests/test_engagement_workflow.py \
  tests/test_mcp_proxy_pool.py \
  tests/test_mcp_installer.py
```

真实接口验证应先使用预览模式，再在测试账号和明确目标上以 `limit=1` 执行。离线测试不会验证抖音当前的风控策略、账号状态或线上接口可用性。

## 📄 来源与使用边界

本仓库是 **[cv-cat/Douyin_Spider](https://github.com/cv-cat/Douyin_Spider)** 的 fork，感谢原作者及贡献者开放数据采集、认证、签名、评论和私信等基础实现。

`feature/mcp-engagement` 是由 **[honestTai](https://github.com/honestTai)** 定制的 MCP 分支，新增跨 Agent 安装、预览确认、流程状态反馈和会话级代理管理。原项目相关权利与使用要求仍归原项目及相应权利人所有。

本项目仅供学习与技术研究。使用者需要自行确认账号授权、内容合规、平台规则及适用法律，不得用于发布不良信息、垃圾互动或骚扰他人。

## 🧰 More from honestTai

| Project | What it does |
| :--- | :--- |
| [**geo-console**](https://github.com/honestTai/geo-console) | 面向品牌团队的证据驱动 GEO 工作台 |
| [**HRouter Desktop**](https://github.com/honestTai/HRouter-Desktop) | 本地优先的 AI 编码 Agent、模型与路由管理工作台 |
| [**hrouter-market-pulse**](https://github.com/honestTai/hrouter-market-pulse) | A 股、港股和美股研究工作台与 Codex 插件 |
| [**seehtml-ai**](https://github.com/honestTai/seehtml-ai) | 从想法到 HTML、演示文稿或视频的本地创作工具 |

[查看全部公开项目 →](https://github.com/honestTai)

---

<div align="center">

Made by **[honestTai](https://github.com/honestTai)** · Based on **[cv-cat/Douyin_Spider](https://github.com/cv-cat/Douyin_Spider)**

如果这个项目对你有帮助，欢迎 Star、Fork，或在 Issues 中分享建议。

</div>

## 📈 Project activity

<a href="https://www.star-history.com/#honestTai/DouYin_Spider&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=honestTai/DouYin_Spider&type=Date&theme=dark">
    <img src="https://api.star-history.com/svg?repos=honestTai/DouYin_Spider&type=Date" alt="Star history of DouYin_Spider fork">
  </picture>
</a>
