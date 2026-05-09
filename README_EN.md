# nonebot-plugin-hermes

[中文文档](https://github.com/gsskk/nonebot-plugin-hermes/blob/main/README.md) | English

A NoneBot2 plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent), enabling multi-platform AI chatbots via Hermes API Server.

## Supported Platforms

Through the NoneBot adapter mechanism, this plugin automatically supports:

- ✅ OneBot v11 (NapCatQQ, LLOneBot, go-cqhttp, etc.)
- ✅ OneBot v12
- ✅ QQ Official Bot
- ✅ Kook
- ✅ Discord
- ✅ Telegram
- ✅ Feishu (Lark)
- ✅ Other platforms supported by `nonebot-plugin-alconna`

## How it works

```
User Message → NoneBot Adapter → nonebot-plugin-hermes
  → POST /v1/chat/completions (Hermes API Server)
  → Parse Reply → UniMessage.send() → NoneBot Adapter → User
```

## Features

- ✅ Private / Group chat conversations
- ✅ Multi-turn context memory (Based on Hermes Session)
- ✅ Group chat trigger modes: @mention / keyword / all
- ✅ **Quoted content extraction**: Automatically extracts text and images from replied messages as AI context
- ✅ **Passive Perception (Chat Awareness)**: Silently records recent group conversations to provide full context for the next trigger
- ✅ Image reception (sent to AI via vision)
- ✅ Image sending (parses markdown images in AI replies)
- ✅ Session lifecycle managed by Hermes Agent
- ✅ Allowlist (Group/User level)
- ✅ Built-in commands (`/clear`, `/ping`, `/help`, `/hermes-status`)
- 🧪 **Active group sessions (M1, experimental)**: After being @-mentioned, the bot listens to the group for 5 minutes and lets Hermes structurally decide whether to chime in
- 🧪 **Reverse channel (M1, experimental)**: Embeds a local MCP server so Hermes can proactively push messages into the chat (delayed replies / async notifications)

## Quick Start

### 1. Prerequisites

- Hermes Agent installed and running, with API Server enabled
- NoneBot2 and the corresponding platform adapter installed

### 2. Enable Hermes API Server

In `~/.hermes/.env`:

```bash
# Enable API Server and specify port
API_SERVER_ENABLED=true
API_SERVER_PORT=8642
# If NoneBot and Hermes are on different machines, listen on all interfaces:
# API_SERVER_HOST=0.0.0.0
```

Set the API Key (**Required**, for session persistence):

```bash
# Generate a key
python3 -c "import secrets; print(secrets.token_hex(32))"
# Or openssl rand -hex 32

# Write to Hermes environment config
echo 'API_SERVER_KEY=your-generated-key' | tee -a ~/.hermes/.env
```

> **Note**: Failing to set `API_SERVER_KEY` will result in session continuation being rejected, meaning the context cannot be maintained across conversations.

Start Hermes Gateway:

```bash
hermes gateway
```

### 3. Install Plugin

**Option A: Using nb-cli (Recommended)**

```bash
nb plugin install nonebot-plugin-hermes
```

**Option B: Using pip / uv**

```bash
pip install nonebot-plugin-hermes
# Or uv add nonebot-plugin-hermes
```

Add the plugin to `pyproject.toml` (done automatically if using nb-cli):

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_hermes"]
```

**Full setup for a new NoneBot Project**:

```bash
pip install nb-cli
nb create          # Create project, choose fastapi driver
nb plugin install nonebot-adapter-onebot  # Install platform adapter, e.g., OneBot
nb plugin install nonebot-plugin-hermes   # Install Hermes plugin
```

### 4. Configuration

Copy the example config:

```bash
cp .env.example .env
```

Edit `.env`, main configurations:

```env
# OneBot Forward WebSocket
ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]

# Hermes API
HERMES_API_URL=http://127.0.0.1:8642
HERMES_API_KEY=

# Group chat trigger
HERMES_GROUP_TRIGGER=at
```

### 5. Run

```bash
nb run
```

## Available AI Tools

This plugin communicates via the Hermes `api_server` platform, which uses the `hermes-api-server` toolset by default:

| Tool Category | Included Tools |
|---------|-----------|
| Web Search & Extraction | `web_search`, `web_extract` |
| Terminal & Process | `terminal`, `process` |
| File Operations | `read_file`, `write_file`, `patch`, `search_files` |
| Vision & Image Generation | `vision_analyze`, `image_generate` |
| Browser Automation | `browser_navigate`, `browser_snapshot`, etc. |
| Planning & Memory | `todo`, `memory`, `session_search` |
| Code Execution & Delegation | `execute_code`, `delegate_task` |
| Cron Jobs | `cronjob` |
| Smart Home (HA) | `ha_list_entities`, `ha_get_state`, etc. |

### 🔒 Security Best Practice: Restricting API Server Toolsets

The default `hermes-api-server` toolset includes powerful tools like `terminal` and `execute_code`. **For deployments facing external users, especially in public group chats, it is strictly required to restrict the toolsets and disable file access (`file` tool) to prevent sensitive data leaks or backdoor injections.**

Configure `platform_toolsets` in `~/.hermes/config.yaml`:

```yaml
platform_toolsets:
  # Keep defaults for other platforms
  cli: [hermes-cli]
  telegram: [hermes-telegram]

  # API Server toolset based on deployment scenario (see recommendations below)
  api_server: [web]
```

Recommended deployment security levels:

| Deployment Scenario | Configuration | Toolsets Included | Description |
| :--- | :--- | :--- | :--- |
| **🔴 Public Groups (Minimal)** | `[web]` | Only Web Search | **The safest configuration for public bots.** Prevents file access, while avoiding high API costs and account ban risks from image generation. |
| **🟠 Public Groups (Media)** | `[safe]` | Web + Vision + Image Gen | Built-in alias for `[web, vision, image_gen]`. Adds visual capabilities, but beware of API cost abuse or policy violations. |
| **🟡 Internal/Trusted Groups** | `[web, vision, image_gen, memory, session_search]` | Web + Media + Memory | Suitable for private internal or friend groups. Enables image features and cross-session memory but still blocks file operations. |
| **🟢 Admin Direct Message** | `[web, file, vision, image_gen, skills, todo, memory, session_search]` | Includes File I/O, Skills Management, etc. | Suitable for personal use by the bot owner. Allows file read/write. Use blocklists to disable it in other groups. |
| **💀 Dev Environment (Full Trust)** | `[hermes-api-server]` | All tools including Terminal and Code Execution | (Default) Only for developers operating in isolated and secure environments. |

> [!WARNING]
> **Privacy Risk Warning for `memory` and `session_search`:**
> Hermes Agent uses a unified, global database for all memories and sessions (there is no tenant isolation). If you enable these tools on a bot shared across multiple groups, **users in Group A can search for and read conversation histories from Group B, or even your private direct messages**. If cross-group privacy is a concern, do not include `memory` or `session_search`. Standard multi-turn conversation context is maintained by temporary sessions and is unaffected by disabling these tools.

### 🆔 User Identity & Metadata Injection

This plugin automatically injects the following metadata into the Hermes API, enabling environment awareness for the backend LLM:

*   **User Identifier** (`user_id`): The user's platform ID (e.g., QQ number).
*   **Group Identifier** (`group_id`): The source group ID (empty for private chats).
*   **Adapter Name** (`adapter_name`): The source platform (e.g., `OneBot V11`, `Discord`, `Telegram`).
*   **Private Chat Status** (`is_private`): Whether the current context is a private chat.

Backend prompts can leverage this information for personalized greetings or platform-specific logic.

## Active Sessions + Reverse Channel (M1, experimental)

When enabled, an @-mention puts the bot into a 5-minute "active window" — during which it hears every message in the group (no @ needed) and Hermes Agent uses a structured decision (`should_reply` / `should_exit_active`) to choose whether to speak. The plugin also runs a local MCP server so Hermes can proactively push messages into the chat (delayed replies, async notifications, etc.).

### Enable

In `.env`:

```env
HERMES_PERCEPTION_ENABLED=true     # active sessions need the message buffer for context
HERMES_ACTIVE_SESSION_ENABLED=true
HERMES_MCP_ENABLED=true
```

After restart the bot will:

- Listen on `127.0.0.1:8643` exposing MCP tools: `push_message` / `list_active_sessions` / `get_recent_messages`
- Enter reactive mode after each @-mention; for the next 5 minutes it makes a `should_reply` decision on every group message (the window slides on each reply)

> ⚠️ The MCP server is loopback-only. **Do not** change `HERMES_MCP_HOST` to a public address — anyone reaching that port can push messages into your groups.

### Tell Hermes Agent about the plugin

The plugin ships a `SKILL.md` (reactive decision contract + reverse-channel usage). From the bot project directory, run any of the following (all install SKILL.md into `~/.hermes/skills/nonebot-bridge/`):

```bash
# If you manage deps with uv
uv run hermes-install-skill

# Or with a plain venv
.venv/bin/hermes-install-skill

# Or with the venv already activated
hermes-install-skill

# Fallback module entry (any env that can import nonebot-plugin-hermes)
python -m hermes_install_skill
```

Then register the plugin's MCP server in `~/.hermes/config.yaml`, replacing `<HERMES_API_KEY>` with the same key you generated earlier (used for two-way auth):

```yaml
mcp_servers:
  nonebot-bridge:
    url: http://127.0.0.1:8643/mcp
    headers: { Authorization: "Bearer <HERMES_API_KEY>" }
```

When the plugin's `SKILL.md` later changes, re-run with `--force` using any of the entries above, e.g. `uv run hermes-install-skill --force` or `.venv/bin/hermes-install-skill --force`.

## Commands

| Command | Description |
|------|------|
| `/clear` | Reset conversation, start a new session |
| `/ping` | Check Hermes Agent connection status |
| `/help` | Show help information |
| `/hermes-status` | Print M1 runtime state (MCP / active sessions / buffer / registry) |

## Configuration Options

All configuration options are set via the `.env` file, see detailed comments in [.env.example](.env.example).

| Option | Default | Description |
|--------|--------|------|
| `HERMES_API_URL` | `http://127.0.0.1:8642` | Hermes API Server URL |
| `HERMES_API_KEY` | (Empty) | API Key (Recommended for session persistence) |
| `HERMES_API_TIMEOUT` | `300` | API request timeout (seconds) |
| `HERMES_GROUP_TRIGGER` | `at` | Group trigger mode: `at` / `all` / `keyword` |
| `HERMES_KEYWORDS` | `["/ai"]` | Trigger keywords for `keyword` mode |
| `HERMES_PRIVATE_TRIGGER` | `all` | Private trigger mode: `all` / `allowlist` |
| `HERMES_ALLOW_USERS` | `[]` | Allowed user IDs for `allowlist` mode |
| `HERMES_ALLOW_GROUPS` | `[]` | Allowed group IDs (empty for all) |
| `HERMES_SESSION_SHARE_GROUP` | `false` | Share session within group |
| `HERMES_MAX_LENGTH` | `4000` | Max reply length (truncated if exceeded) |
| `HERMES_IGNORE_PREFIX` | `["."]` | Ignore messages starting with these chars |
| `HERMES_PERCEPTION_ENABLED` | `false` | Enable passive perception |
| `HERMES_PERCEPTION_BUFFER` | `10` | Number of messages to buffer for perception |
| `HERMES_PERCEPTION_TEXT_LENGTH` | `200` | Max text length per historical message |
| `HERMES_PERCEPTION_IMAGE_MODE` | `placeholder` | Image mode: `placeholder` (text-only refs, recommended) / `inline_labeled` (sent in multimodal with strong labels, for cross-image questions) / `none` |
| `HERMES_ACTIVE_SESSION_ENABLED` | `false` | Enable active group sessions (M1). When `false` the plugin behaves as in v0.1.6 |
| `HERMES_ACTIVE_SESSION_TTL_SEC` | `300` | Active-window TTL in seconds; sliding renewal on each reply |
| `HERMES_ACTIVE_SWEEP_INTERVAL_SEC` | `30` | Cron sweep interval for expired active sessions |
| `HERMES_BUFFER_PER_GROUP_CAP` | `200` | MessageBuffer per-group recent-message cap |
| `HERMES_BUFFER_TOTAL_GROUPS_CAP` | `50` | MessageBuffer total cross-group capacity (LRU eviction) |
| `HERMES_MCP_ENABLED` | `false` | Start the embedded FastMCP server (M1 reverse channel) |
| `HERMES_MCP_HOST` | `127.0.0.1` | MCP server bind address (**do not change to non-loopback**) |
| `HERMES_MCP_PORT` | `8643` | MCP server bind port |
| `HERMES_MCP_RECENT_LIMIT_MAX` | `50` | Max items the `get_recent_messages` tool returns per call |
| `HERMES_STRUCTURED_PATH` | `prompt` | Reactive structured-output path: `prompt` (JSON5 parse) / `tools` (OpenAI tool_choice) |

## Limitations

Since communication with Hermes is via HTTP API (rather than a native Gateway Adapter), the following features are not available:

- ❌ Ask the user for clarification (`clarify` tool)
- ❌ Send cross-platform messages (`send_message` tool)
- ❌ Speech synthesis / Voice sending (`text_to_speech` tool)
- ❌ Dangerous command approval buttons
- ❌ Active push via Cron jobs
- ❌ Interrupting a running Agent

## License

MIT
