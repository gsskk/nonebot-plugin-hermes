# nonebot-plugin-hermes

中文文档 | [English](https://github.com/gsskk/nonebot-plugin-hermes/blob/main/README_EN.md)

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 的 NoneBot2 插件，通过 Hermes API Server 实现多平台 AI 聊天机器人。

## 支持的平台

通过 NoneBot adapter 机制，本插件自动支持：

- ✅ OneBot v11（NapCatQQ、LLOneBot、go-cqhttp 等）
- ✅ OneBot v12
- ✅ QQ Official Bot
- ✅ Kook（开黑啦）
- ✅ Discord
- ✅ Telegram
- ✅ 飞书
- ✅ 其他 `nonebot-plugin-alconna` 支持的平台

## 工作原理

```
用户消息 → NoneBot Adapter → nonebot-plugin-hermes
  → POST /v1/chat/completions (Hermes API Server)
  → 解析回复 → UniMessage.send() → NoneBot Adapter → 用户
```

## 功能

- ✅ 私聊 / 群聊对话
- ✅ 多轮上下文记忆（基于 Hermes Session）
- ✅ 群聊 @触发 / 关键词触发 / 全部触发
- ✅ **引用消息提取**：自动提取被回复消息中的文本和图片作为 AI 上下文
- ✅ **被动感知 (Chat Awareness)**：在群聊中默默记录最近对话，为下次触发提供完整背景
- ✅ 图片接收（通过 vision 发给 AI）
- ✅ 图片发送（解析 AI 回复中的 markdown 图片）
- ✅ 会话生命周期由 Hermes Agent 管理
- ✅ 白名单（群/用户级别）
- ✅ 内置命令（`/clear` `/ping` `/help` `/hermes-status`）
- 🧪 **群活跃态 (M1, 实验性)**：@bot 后 5 分钟内主动监听群对话，由 Hermes 通过结构化决策判断是否插话
- 🧪 **反向通道 (M1, 实验性)**：内嵌本地 MCP server，让 Hermes 主动 push 消息进群（延迟回复 / 异步通知）

## 快速开始

### 1. 前置条件

- 已安装并运行 Hermes Agent，且 API Server 已启用
- 已安装 NoneBot2 和对应平台的 adapter

### 2. 启用 Hermes API Server

在 `~/.hermes/.env` 中添加配置：

```bash
# 启用 API Server 并指定端口
API_SERVER_ENABLED=true
API_SERVER_PORT=8642
# 如果 NoneBot 和 Hermes 不在同一台机器上，需要监听所有 IP：
# API_SERVER_HOST=0.0.0.0
```

设置 API Key（**必须**，用于会话保持）：

```bash
# 生成密钥
python3 -c "import secrets; print(secrets.token_hex(32))"
# 或 openssl rand -hex 32

# 写入 Hermes 环境配置
echo 'API_SERVER_KEY=your-generated-key' | tee -a ~/.hermes/.env
```

> **Note**: 不设置 `API_SERVER_KEY` 会导致 Session 续接被拒绝，每次对话无法保持上下文。

启动 Hermes Gateway：

```bash
hermes gateway
```

### 3. 安装插件

**方式 A：使用 nb-cli 安装（推荐）**

```bash
nb plugin install nonebot-plugin-hermes
```

**方式 B：使用 pip / uv 安装**

```bash
pip install nonebot-plugin-hermes
# 或 uv add nonebot-plugin-hermes
```

在 `pyproject.toml` 中添加插件（如果是 nb-cli 安装会自动添加）：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_hermes"]
```

**新建 NoneBot 项目的完整步骤**：

```bash
pip install nb-cli
nb create          # 创建项目，选择 fastapi 驱动器
nb plugin install nonebot-adapter-onebot  # 安装对应平台的适配器，例如 OneBot
nb plugin install nonebot-plugin-hermes   # 安装 Hermes 插件
```

### 4. 配置

复制示例配置：

```bash
cp .env.example .env
```

编辑 `.env`，主要配置：

```env
# OneBot 正向 WebSocket
ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]

# Hermes API
HERMES_API_URL=http://127.0.0.1:8642
HERMES_API_KEY=

# 群聊触发
HERMES_GROUP_TRIGGER=at
```

### 5. 运行

```bash
nb run
```

## 可用的 AI 工具

本插件通过 Hermes 的 `api_server` 平台通信，默认使用 `hermes-api-server` 工具集：

| 工具类别 | 包含的工具 |
|---------|-----------|
| Web 搜索与提取 | `web_search`, `web_extract` |
| 终端与进程 | `terminal`, `process` |
| 文件操作 | `read_file`, `write_file`, `patch`, `search_files` |
| 视觉与图片生成 | `vision_analyze`, `image_generate` |
| 浏览器自动化 | `browser_navigate`, `browser_snapshot` 等 |
| 规划与记忆 | `todo`, `memory`, `session_search` |
| 代码执行与委托 | `execute_code`, `delegate_task` |
| 定时任务 | `cronjob` |
| 智能家居 | `ha_list_entities`, `ha_get_state` 等 |

### 🔒 安全最佳实践：限制 API Server 工具集

默认的 `hermes-api-server` 工具集包含 `terminal`、`execute_code` 等危险工具。**针对不同的部署环境，强烈建议配置不同的受限工具集，特别是在公共群聊中，必须禁止文件读写（`file` 工具）以防敏感信息泄露或被植入后门。**

在 `~/.hermes/config.yaml` 中配置 `platform_toolsets`：

```yaml
platform_toolsets:
  # 其他平台保持默认
  cli: [hermes-cli]
  telegram: [hermes-telegram]

  # API Server 根据部署场景选择工具集 (见下方推荐)
  api_server: [web]
```

推荐的部署安全级别：

| 部署场景 | 推荐配置 | 包含的工具集 | 说明 |
| :--- | :--- | :--- | :--- |
| **🔴 公共群聊 (极简防刷)** | `[web]` | 仅 `web` (联网搜索) | **对外公开机器人的最稳妥配置。** 杜绝文件操作，同时避免画图/识图带来的高昂 API 费用和合规封号风险。 |
| **🟠 公共群聊 (含多媒体)** | `[safe]` | 搜索 + 识图 + 画图 | 等同于 `[web, vision, image_gen]`。增加了视觉能力，但需注意防范 API 被刷或恶意图片封号的风险。 |
| **🟡 内部/信任群聊 (受限读写)** | `[web, vision, image_gen, memory, session_search]` | 搜索 + 多媒体 + 记忆 | 适合公司内部群或好友群。允许发图画图、保留跨会话记忆，但依然严格禁止文件读写。 |
| **🟢 站长私聊 (高级管理)** | `[web, file, vision, image_gen, skills, todo, memory, session_search]` | 包含文件读写、技能管理等 | 适合机器人主人的私聊。有文件读写能力，可通过群白名单机制将其他群屏蔽。 |
| **💀 危险/开发环境 (完全信任)** | `[hermes-api-server]` | 包含终端、代码执行等全部工具 | （默认）仅限开发者自己在安全的隔离环境使用。 |

> [!WARNING]
> **关于 `memory` 和 `session_search` 的跨群隐私泄露风险：**
> Hermes Agent 的底层数据库是全局共享的（无平台/群组隔离）。如果在多群共用的 Agent 上开启这两个工具，**A群的成员可以搜到B群的聊天记录，甚至你的私人终端/私聊记录**。若看重隐私隔离，多群共用时请勿包含 `memory` 和 `session_search`。普通的上下文多轮对话由临时 Session 维护，不受关闭这两个工具的影响。

### 🆔 用户身份与元数据注入

本插件会自动向 Hermes API 注入以下元数据，使后端 LLM 具备环境感知能力：

*   **用户标识** (`user_id`): 用户的平台 ID（如 QQ 号）。
*   **群组标识** (`group_id`): 消息来源群号（私聊则为空）。
*   **适配器名称** (`adapter_name`): 消息来源平台（如 `OneBot V11`, `Discord`, `Telegram` 等）。
*   **私聊状态** (`is_private`): 当前是否为私聊环境。

后端 Prompt 可以通过这些信息实现个性化称呼或针对特定平台的功能逻辑。

## 群活跃态 + 反向通道（M1，实验性）

启用后，bot 在被 @ 之后会进入 5 分钟"活跃窗口"——期间能听到所有群消息（无需再 @），由 Hermes Agent 通过结构化决策（`should_reply` / `should_exit_active`）自行判断是否插话。同时插件起一个本地 MCP server，让 Hermes 可以主动 push 消息进群（延迟回复、异步通知等）。

### 启用

在 `.env` 中：

```env
HERMES_PERCEPTION_ENABLED=true     # 活跃态依赖消息缓冲做上下文
HERMES_ACTIVE_SESSION_ENABLED=true
HERMES_MCP_ENABLED=true
```

重启后 bot 会：

- 监听 `127.0.0.1:8643` 暴露 MCP 工具：`push_message` / `list_active_sessions` / `get_recent_messages`
- 在 @bot 触发后进入 reactive 模式，5 分钟内对群消息做 should_reply 决策（每次插话续期）

> ⚠️ **安全注意 ——`HERMES_MCP_HOST` 默认 `127.0.0.1`(loopback)。** 改成监听公网 / 局域网地址在技术上完全可行,但安全后果是:`push_message` 工具能让 bot 往群里发任意内容,而当前防御仅有 Bearer token(明文 HTTP 传输,且与 `HERMES_API_KEY` 同钥匙)。改之前请配套上反向代理(TLS 终结) + 来源 IP ACL,否则任何能 reach 该端口的进程一旦拿到 token 就可以冒名发送。

### 把插件能力告诉 Hermes Agent

插件自带一份 `SKILL.md`（reactive 决策契约 + 反向通道用法）。在 bot 项目目录下任选一种执行（都是把 SKILL.md 装到 `~/.hermes/skills/nonebot-bridge/`）：

```bash
# 用 uv 管理依赖
uv run hermes-install-skill

# 或者 bot 项目用普通 venv
.venv/bin/hermes-install-skill

# 或者已激活虚拟环境
hermes-install-skill

# 备用入口（任何能 import nonebot-plugin-hermes 的环境）
python -m hermes_install_skill
```

然后在 `~/.hermes/config.yaml` 注册插件 MCP server，把 `<HERMES_API_KEY>` 替换为你前面生成的同一把密钥（用于双向鉴权）：

```yaml
mcp_servers:
  nonebot-bridge:
    url: http://127.0.0.1:8643/mcp
    headers: { Authorization: "Bearer <HERMES_API_KEY>" }
```

后续插件 SKILL.md 升级时,用上面同样的入口加 `--force` 重装,例如 `uv run hermes-install-skill --force` 或 `.venv/bin/hermes-install-skill --force`。

## 命令

| 命令 | 说明 |
|------|------|
| `/clear` | 重置对话，开始新会话 |
| `/ping` | 检查 Hermes Agent 连接状态 |
| `/help` | 显示帮助信息 |
| `/hermes-status` | 打印 M1 运行时状态（MCP / 活跃 sessions / buffer / registry）。**需在 `HERMES_ADMIN_USERS` 显式授权 `adapter:user_id`** |

## 配置项

所有配置项通过 `.env` 文件设置，参见 [.env.example](.env.example) 中的详细注释。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HERMES_API_URL` | `http://127.0.0.1:8642` | Hermes API Server 地址 |
| `HERMES_API_KEY` | (空) | API 密钥（建议设置以启用会话持久化） |
| `HERMES_API_TIMEOUT` | `300` | API 请求超时时间（秒） |
| `HERMES_GROUP_TRIGGER` | `at` | 群聊触发方式: `at` / `all` / `keyword` |
| `HERMES_KEYWORDS` | `["/ai"]` | `keyword` 模式下的触发关键词 |
| `HERMES_PRIVATE_TRIGGER` | `all` | 私聊触发方式: `all` / `allowlist` |
| `HERMES_ALLOW_USERS` | `[]` | 允许私聊的用户 ID 列表 (`allowlist` 模式) |
| `HERMES_ALLOW_GROUPS` | `[]` | 允许响应的群组 ID 列表（空为全部允许） |
| `HERMES_ADMIN_USERS` | `[]` | 管理员白名单,格式 `["telegram:<user_id>", "onebotv11:<user_id>"]`。**默认空集 = deny by default**;`/hermes-status` 等敏感命令必须命中此列表才执行 |
| `HERMES_SESSION_SHARE_GROUP` | `false` | 群内是否共享同一个 session |
| `HERMES_MAX_LENGTH` | `4000` | 单条回复最大长度（超出后截断） |
| `HERMES_IGNORE_PREFIX` | `["."]` | 以这些字符开头的消息不触发回复 |
| `HERMES_PERCEPTION_ENABLED` | `false` | 是否开启被动感知 |
| `HERMES_PERCEPTION_BUFFER` | `10` | 被动感知缓存的历史消息数量 |
| `HERMES_PERCEPTION_TEXT_LENGTH` | `200` | 被动感知单条历史消息最大长度 |
| `HERMES_PERCEPTION_IMAGE_MODE` | `placeholder` | 历史图片模式: `placeholder`(纯文本占位,推荐) / `inline_labeled`(带标签随多模态发送,适合跨图诉求) / `none`(不提) |
| `HERMES_ACTIVE_SESSION_ENABLED` | `false` | 启用群活跃态（M1）。`false` 时退化为 v0.1.6 等价行为 |
| `HERMES_ACTIVE_SESSION_TTL_SEC` | `300` | 活跃窗口 TTL（秒），每次插话滑动续期 |
| `HERMES_ACTIVE_SWEEP_INTERVAL_SEC` | `30` | 活跃态过期清扫 cron 频率（秒） |
| `HERMES_BUFFER_PER_GROUP_CAP` | `200` | MessageBuffer 每群最近消息上限 |
| `HERMES_BUFFER_TOTAL_GROUPS_CAP` | `50` | MessageBuffer 跨群总容量（LRU 驱逐） |
| `HERMES_MCP_ENABLED` | `false` | 启动内嵌 FastMCP server（M1 反向通道） |
| `HERMES_MCP_HOST` | `127.0.0.1` | MCP server 绑定地址。改成公开地址前请阅读上文「群活跃态 + 反向通道」节的安全注意 |
| `HERMES_MCP_PORT` | `8643` | MCP server 绑定端口 |
| `HERMES_MCP_RECENT_LIMIT_MAX` | `50` | `get_recent_messages` 工具单次最大返回条数 |
| `HERMES_STRUCTURED_PATH` | `prompt` | reactive 结构化输出路径: `prompt`（JSON5 解析） / `tools`（OpenAI tool_choice） |

## 限制

由于通过 HTTP API 与 Hermes 通信（而非原生 Gateway Adapter），以下功能不可用：

- ❌ 追问用户（`clarify` 工具）
- ❌ 跨平台发消息（`send_message` 工具）
- ❌ 语音合成发送（`text_to_speech` 工具）
- ❌ 危险命令审批按钮
- ❌ Cron 定时主动推送
- ❌ 中断正在运行的 Agent

## License

MIT
