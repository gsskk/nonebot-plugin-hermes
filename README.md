# OneBot Bridge for Hermes Agent

将 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 通过 [OneBot v11](https://11.onebot.dev/) 协议对接 QQ 机器人，**无需修改 Hermes 源码**。

## 工作原理

```
QQ 用户 ↔ OneBot 框架 (NapCatQQ 等) ↔ [onebot_bridge.py] ↔ Hermes API Server ↔ AI Agent
```

Bridge 充当翻译官：
- **左侧**：通过 WebSocket 与 OneBot 框架通信（接收/发送 QQ 消息）
- **右侧**：通过 HTTP 调用 Hermes 的 OpenAI 兼容 API（`/v1/chat/completions`）

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

- 已安装并运行 [Hermes Agent](https://github.com/NousResearch/hermes-agent)，且 API Server 已启用
- 已安装 OneBot v11 兼容框架（如 [NapCatQQ](https://github.com/NapNeko/NapCatQQ)）并配置了正向 WebSocket

### 2. 启用 Hermes API Server

在 `~/.hermes/config.yaml` 中确保：

```yaml
platforms:
  api_server:
    enabled: true
    extra:
      port: 8642
      # key: "your-api-key"  # 可选，建议设置
```

### 3. 安装 Bridge

```bash
cd plugins/onebot-bridge
pip install -r requirements.txt
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 OneBot WebSocket 地址等
```

### 4. 配置 Bridge

编辑 `config.yaml`：

```yaml
onebot:
  ws_url: "ws://127.0.0.1:3001"   # OneBot 正向 WS 地址
  access_token: ""                  # OneBot access_token（如有）

hermes:
  api_url: "http://127.0.0.1:8642" # Hermes API Server 地址
  api_key: ""                       # Hermes API Key（如有）

bot:
  group_trigger: "at"               # 群聊触发: at / all / keyword
  private_trigger: "all"            # 私聊触发: all / allowlist
```

### 5. 运行

```bash
python onebot_bridge.py
```

后台运行（推荐）：

```bash
nohup python onebot_bridge.py > bridge.log 2>&1 &
```

或使用 systemd / pm2 等进程管理器。

## 配置详解

参见 [config.example.yaml](config.example.yaml) 中的注释说明。

## 限制

由于 Bridge 通过 HTTP API 与 Hermes 通信（而非原生 Gateway Adapter），以下功能不可用：

- ❌ 危险命令审批按钮（Approval inline keyboard）
- ❌ Cron 定时推送消息
- ❌ 中断正在运行的 Agent
- ❌ "正在输入" 状态显示
- ❌ 语音消息发送

## License

MIT
