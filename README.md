# nonebot-plugin-hermes

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
- ✅ 图片接收（通过 vision 发给 AI）
- ✅ 图片发送（解析 AI 回复中的 markdown 图片）
- ✅ 会话超时自动重置
- ✅ 白名单（群/用户级别）
- ✅ 内置命令（`/clear` `/ping` `/help`）

## 快速开始

### 1. 前置条件

- 已安装并运行 Hermes Agent，且 API Server 已启用
- 已安装 NoneBot2 和对应平台的 adapter

### 2. 启用 Hermes API Server

在 `~/.hermes/config.yaml` 中：

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      port: 8642
```

设置 API Key（**必须**，用于会话保持）：

```bash
# 生成密钥
python -c "import secrets; print(secrets.token_hex(32))"
# 或 openssl rand -hex 32

# 写入 Hermes 环境配置
echo 'API_SERVER_KEY=your-generated-key' >> ~/.hermes/.env
```

> **Note**: 不设置 `API_SERVER_KEY` 会导致 Session 续接被拒绝，每次对话无法保持上下文。

启动 Hermes Gateway：

```bash
hermes gateway
```

### 3. 安装插件

**方式 A：已有 NoneBot 项目**

```bash
pip install -e /path/to/nonebot-plugin-hermes
# 或 uv add /path/to/nonebot-plugin-hermes
```

在 `pyproject.toml` 中添加插件：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_hermes"]
```

**方式 B：新建 NoneBot 项目**

```bash
pip install nb-cli
nb create          # 创建项目，选择 fastapi 驱动器
nb plugin install nonebot-adapter-onebot  # 安装 OneBot 适配器
pip install -e /path/to/nonebot-plugin-hermes
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

默认的 `hermes-api-server` 工具集包含 `terminal`、`execute_code` 等可执行服务器命令的工具。**对于面向外部用户的部署，强烈建议限制工具集**。

在 `~/.hermes/config.yaml` 中配置 `platform_toolsets`：

```yaml
platform_toolsets:
  # 其他平台保持默认
  cli: [hermes-cli]
  telegram: [hermes-telegram]

  # API Server 使用受限工具集（按需选择）
  api_server: [web, file, vision, image_gen, skills, todo, memory, session_search]
```

可选的安全级别：

| 级别 | 配置 | 说明 |
|------|------|------|
| 🔴 最小权限 | `[safe]` | 仅 web + vision + image_gen，无文件/终端 |
| 🟡 推荐 | `[web, file, vision, image_gen, skills, todo, memory, session_search]` | 有文件读写但无命令执行 |
| 🟢 完全信任 | `[hermes-api-server]`（默认） | 包含终端、代码执行等全部工具 |

> **Tip**: 运行 `hermes chat --list-toolsets` 查看所有可用工具集。



## 命令

| 命令 | 说明 |
|------|------|
| `/clear` | 重置对话，开始新会话 |
| `/ping` | 检查 Hermes Agent 连接状态 |
| `/help` | 显示帮助信息 |

## 配置项

所有配置项通过 `.env` 文件设置，参见 [.env.example](.env.example) 中的详细注释。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HERMES_API_URL` | `http://127.0.0.1:8642` | Hermes API Server 地址 |
| `HERMES_API_KEY` | (空) | API 密钥 |
| `HERMES_GROUP_TRIGGER` | `at` | 群聊触发: at / all / keyword |
| `HERMES_PRIVATE_TRIGGER` | `all` | 私聊触发: all / allowlist |
| `HERMES_SESSION_EXPIRE` | `3600` | 会话超时（秒） |
| `HERMES_SESSION_SHARE_GROUP` | `false` | 群内共享 session |

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
