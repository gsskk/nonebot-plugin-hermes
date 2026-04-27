# OneBot Bridge for Hermes Agent

将 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 通过 [OneBot v11](https://11.onebot.dev/) 协议对接 QQ 机器人，**无需修改 Hermes 源码**。

## 工作原理

```
QQ 用户 ↔ OneBot 框架 (NapCatQQ 等) ↔ [onebot_bridge.py] ↔ Hermes API Server ↔ AI Agent
```

Bridge 是一个独立运行的 Python 脚本，充当 OneBot 和 Hermes 之间的翻译官：
- **左侧**：通过 WebSocket 连接 OneBot 框架，接收/发送 QQ 消息
- **右侧**：通过 HTTP 调用 Hermes 内置的 OpenAI 兼容 API（`/v1/chat/completions`）

> **注意**：Bridge 需要作为独立进程运行，不是 Hermes 的内置插件。你需要同时运行 Hermes Gateway（启用 `api_server`）和本 Bridge 脚本。

## 支持的功能

- ✅ 私聊 / 群聊对话
- ✅ 多轮上下文记忆（基于 Hermes Session）
- ✅ 群聊 @触发 / 关键词触发 / 全部触发
- ✅ 图片接收（通过 vision 发给 AI）
- ✅ 图片发送（解析 AI 回复中的 markdown 图片）
- ✅ 自动重连（指数退避）
- ✅ 白名单（群/用户级别）
- ✅ Bridge 内置命令（`/new` `/ping` `/help`）

## 快速开始

### 1. 前置条件

- 已安装并运行 [Hermes Agent](https://github.com/NousResearch/hermes-agent)
- 已安装 OneBot v11 兼容框架（如 [NapCatQQ](https://github.com/NapNeko/NapCatQQ)）并配置了**正向 WebSocket**

### 2. 启用 Hermes API Server

在 `~/.hermes/config.yaml` 中添加：

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      port: 8642
      # key: "your-api-key"  # 可选，设置后 Bridge 也需要配置相同的 key
```

然后启动（或重启）Hermes Gateway：

```bash
hermes gateway
```

### 3. 可用的 AI 工具

Bridge 通过 `api_server` 平台与 Hermes 通信。该平台默认使用 `hermes-api-server` 工具集，包含以下工具：

| 工具类别 | 包含的工具 |
|---------|-----------|
| Web 搜索与提取 | `web_search`, `web_extract` |
| 终端与进程 | `terminal`, `process` |
| 文件操作 | `read_file`, `write_file`, `patch`, `search_files` |
| 视觉与图片生成 | `vision_analyze`, `image_generate` |
| 技能管理 | `skills_list`, `skill_view`, `skill_manage` |
| 浏览器自动化 | `browser_navigate`, `browser_snapshot`, `browser_click` 等 |
| 规划与记忆 | `todo`, `memory`, `session_search` |
| 代码执行与委托 | `execute_code`, `delegate_task` |
| 定时任务 | `cronjob` |
| 智能家居 | `ha_list_entities`, `ha_get_state` 等 |

如需自定义工具集，可在 `~/.hermes/config.yaml` 中手动配置：

```yaml
platform_toolsets:
  api_server:
    - web
    - terminal
    - file
    - vision
    - browser
    - todo
    - memory
    # ... 按需增减
```

> **注意**：`clarify`（追问用户）、`send_message`（跨平台发消息）、`text_to_speech`（语音合成）在 API Server 模式下不可用，因为它们需要交互式 UI 通道。

### 4. 安装 Bridge

```bash
cd onebot-bridge
uv sync                         # 安装依赖（使用 uv）
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 OneBot WebSocket 地址等
```

### 5. 配置 Bridge

编辑 `config.yaml`：

```yaml
onebot:
  ws_url: "ws://127.0.0.1:3001"   # OneBot 正向 WS 地址
  access_token: ""                  # OneBot access_token（如有）

hermes:
  api_url: "http://127.0.0.1:8642" # Hermes API Server 地址
  api_key: ""                       # 对应 api_server.extra.key（如有）

bot:
  group_trigger: "at"               # 群聊触发: at / all / keyword
  private_trigger: "all"            # 私聊触发: all / allowlist
```

### 6. 运行

```bash
uv run python onebot_bridge.py
```

后台运行（推荐使用 systemd）：

```bash
# 安装 systemd 服务
sudo cp onebot-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable onebot-bridge
sudo systemctl start onebot-bridge

# 查看日志
journalctl -u onebot-bridge -f

# 重启 / 停止
sudo systemctl restart onebot-bridge
sudo systemctl stop onebot-bridge
```

## 配置详解

参见 [config.example.yaml](config.example.yaml) 中的注释说明。

## 限制

由于 Bridge 通过 HTTP API 与 Hermes 通信（而非原生 Gateway Adapter），以下功能不可用：

- ❌ 追问用户（`clarify` 工具，需要交互式 UI）
- ❌ 跨平台发消息（`send_message` 工具）
- ❌ 语音合成发送（`text_to_speech` 工具）
- ❌ 危险命令审批按钮（Approval inline keyboard）
- ❌ Cron 定时主动推送消息到 QQ
- ❌ 中断正在运行的 Agent
- ❌ "正在输入" 状态显示

## License

MIT
