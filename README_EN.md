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
- 🧪 **Historical image recall (0.3+, experimental)**: SQLite-backed message log + filesystem image-byte cache + `get_message_images` MCP tool. Lets Hermes precisely fetch a past image by message id when the user says things like "上图" / "the image just now"
- 🧪 **OneBot v11 Notice triggers (0.3.3+, experimental)**: Poke (戳一戳) as a second @-equivalent trigger; on group-join Hermes self-decides whether to greet (noop is valid — no template welcomes)
- 🧪 **Message segment perception (0.3.4+, experimental)**: Voice/Video/QQ face/sticker placeholders surface to LLM context; stickers automatically skip the vision API. OneBot v11 NapCat ack-emoji on explicit @ (`HERMES_ACK_FEEDBACK_ENABLED=true`)
- ✅ **Merge-forward handling (0.4.0+)**: incoming merge-forward (合并转发) messages are expanded into a length-capped summary; the bot's own long replies are sent as a merge-forward in OneBot v11 groups instead of being truncated

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
HERMES_ACTIVE_SESSION_ENABLED=true
HERMES_MCP_ENABLED=true
```

> Enabling `HERMES_ACTIVE_SESSION_ENABLED` auto-implies passive perception (the message buffer is its dependency); you don't need to set `HERMES_PERCEPTION_ENABLED` separately. That flag only matters with active=false in groups — it lets the bot inject prior bystander chatter as context the moment it gets @-mentioned.

After restart the bot will:

- Listen on `127.0.0.1:8643` exposing MCP tools: `push_message` / `list_active_sessions` / `get_recent_messages` / `get_message_images`
- Enter reactive mode after each @-mention; for the next 5 minutes it makes a `should_reply` decision on every group message (the window slides on each reply)
- Persist every group message into SQLite (path managed by `nonebot-plugin-localstore`, default `~/.local/share/nonebot2/nonebot_plugin_hermes/messages.db`) and assign a stable msg_id; each line in the `<recent_messages>` prompt block now gets an `[m:<id>]` prefix that Hermes uses to call `get_message_images` for historical image bytes

> ⚠️ **Security note — `HERMES_MCP_HOST` defaults to `127.0.0.1` (loopback).** Binding to a public or LAN address technically works, but the security trade-off is real: the `push_message` tool lets the bot send arbitrary messages into your groups, and the only defense in front of it is the Bearer token (sent over plain HTTP, and shared with `HERMES_API_KEY`). Before exposing the port, put a reverse proxy with TLS in front and add source-IP ACLs — otherwise any process that can reach the port and obtains the token can impersonate the bot.

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

## Historical image recall (0.3+, experimental)

Starting in 0.3, when perception and the reverse channel are both enabled the bot turns on a "precise per-msg-id historical image recall" path. Typical scenario:

```
T0    User A:  [image]                    ← caption-less; bot sees [图片] placeholder
T+5s  User B:  @bot please rate the image just sent
                ↓
                Hermes sees [m:1234] A: [图片] in the prompt
                Hermes calls get_recent_messages → knows m:1234 has image_count=1
                Hermes calls get_message_images([1234]) → fetches bytes
                Hermes's next LLM turn actually sees that image, replies correctly
```

Implementation details:

- **Persistence**: messages go to SQLite at a path managed by `nonebot-plugin-localstore` (default `~/.local/share/nonebot2/nonebot_plugin_hermes/messages.db`, can be redirected via `LOCALSTORE_*` env vars); the autoincrement id becomes the N in the `[m:<id>]` prefix
- **Byte cache**: perception kicks off an async HTTP fetch on each image URL, persisting bytes to the localstore-managed cache dir (default `~/.cache/nonebot2/nonebot_plugin_hermes/images/<sha256>.<ext>`). LRU eviction by atime, default 200MB quota
- **Graceful degradation**: short-lived CDN URLs expired / cache evicted / message past 30-day retention → the MCP tool returns `available: false` and Hermes tells the user the image is gone, no crash
- **Retention window**: 30 days OR 100k rows (whichever comes first); hourly cron at :37 runs vacuum

If your Hermes backend model is weak and unreliably parses the `[m:<id>]` convention, behavior degrades to today's "can't see the image you mentioned" — no regression.

## Commands

| Command | Description |
|------|------|
| `/clear` | Reset conversation, start a new session |
| `/ping` | Check Hermes Agent connection status |
| `/help` | Show help information |
| `/hermes-status` | Print M1 runtime state (MCP / active sessions / buffer / registry). **Requires `adapter:user_id` to be listed in `HERMES_ADMIN_USERS`**; non-admin invocations are silently ignored and the command does not appear in `/help` for them |

### Command-line tools

| Command | Description |
|------|------|
| `hermes-install-skill --force` | Installs `SKILL.md` into `~/.hermes/skills/nonebot-bridge/` (`--force` is required to overwrite an existing install) |
| `hermes-purge-media` | Purges inline base64 image bytes from the message database. Reports only by default; `--apply` writes back, `--vacuum` shrinks the file |

`hermes-purge-media` cleans up a legacy artifact: earlier versions stored the whole
`data:image/…;base64,…` payload that api_server inlines into agent replies straight into the
message database, reaching megabytes for a single row. The current version blocks this on both
the write and the render side; this command only clears out the bytes already stored.

```bash
hermes-purge-media                    # report only: hits per group, largest row, reclaimable bytes
hermes-purge-media --apply --vacuum   # purge and shrink the file
```

Messages are never deleted — the image payload is replaced with a `[图片]` placeholder. Idempotent,
safe to re-run. `--vacuum` needs an exclusive lock; stop the bot first if it can't acquire one.

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
| `HERMES_ADMIN_USERS` | `[]` | Admin allowlist as `["telegram:<user_id>", "onebotv11:<user_id>"]`. **Empty = deny by default**; sensitive commands like `/hermes-status` only run if the caller's `adapter:user_id` is in this list |
| `HERMES_SESSION_SHARE_GROUP` | `false` | Share session within group |
| `HERMES_MAX_LENGTH` | `4000` | Max reply length (truncated if exceeded) |
| `HERMES_IGNORE_PREFIX` | `["."]` | Ignore messages starting with these chars |
| `HERMES_PERCEPTION_ENABLED` | `false` | In groups with active_session=false, inject bystander history into the LLM on @-mention. **Auto-implied when `HERMES_ACTIVE_SESSION_ENABLED=true`; this flag is then a no-op**. Never injected in private chats (Hermes session already covers it) |
| `HERMES_PERCEPTION_BUFFER` | `10` | Number of messages to buffer for perception |
| `HERMES_PERCEPTION_TEXT_LENGTH` | `200` | Max text length per historical message |
| `HERMES_PERCEPTION_IMAGE_MODE` | `placeholder` | ⚠️ **Deprecated since 0.3** — historical image recall moved to the `get_message_images` MCP tool. This knob now only controls whether a `[图片]` placeholder appears in history text (`none` = no placeholder; anything else = add placeholder). `inline_labeled` is superseded; setting it is equivalent to `placeholder` |
| `HERMES_ACTIVE_SESSION_ENABLED` | `false` | Enable active group sessions (M1). When `false` the plugin behaves as in v0.1.6 |
| `HERMES_ACTIVE_SESSION_TTL_SEC` | `300` | Active-window TTL in seconds; sliding renewal on each reply |
| `HERMES_ACTIVE_SWEEP_INTERVAL_SEC` | `30` | Cron sweep interval for expired active sessions |
| `HERMES_POKE_TRIGGER_ENABLED` | `false` | OneBot v11: being poked triggers a turn (private & group, equivalent to being @-mentioned). Other adapters silently no-op |
| `HERMES_GREET_ON_JOIN` | `false` | OneBot v11: when someone joins a group and `HERMES_ACTIVE_SESSION_ENABLED=true`, fire one reactive turn so Hermes can self-decide whether to welcome via decision_protocol (`noop` is valid). When active is off, nothing fires |
| `HERMES_ACK_FEEDBACK_ENABLED` | `false` | Show an ack receipt on the user's message (B-0 ships OneBot v11 NapCat emoji). B-0.5 will extend to Telegram/Discord typing in private chats |
| `HERMES_ACK_EMOJI_ID` | `341` | B-0 OneBot v11 face id to attach (default 341 = /打招呼 hi-wave; `373` /忙 = animal typing; `129` /挥手 = classic wave) |
| `HERMES_BUFFER_PER_GROUP_CAP` | `200` | ⚠️ **No-op since 0.3** — MessageBuffer is now SQLite-backed; message eviction is governed by `HERMES_STORAGE_MESSAGE_*` instead. Will be removed in the next major version |
| `HERMES_BUFFER_TOTAL_GROUPS_CAP` | `50` | ⚠️ **No-op since 0.3** — see above |
| `HERMES_MCP_ENABLED` | `false` | Start the embedded FastMCP server (M1 reverse channel) |
| `HERMES_MCP_HOST` | `127.0.0.1` | MCP server bind address. Read the security note in "Active Sessions + Reverse Channel" before exposing publicly |
| `HERMES_MCP_PORT` | `8643` | MCP server bind port |
| `HERMES_MCP_RECENT_LIMIT_MAX` | `50` | Max items the `get_recent_messages` tool returns per call |
| `HERMES_STORAGE_DB_PATH` | (empty) | SQLite message log path. Empty falls back to `nonebot-plugin-localstore`'s plugin_data_dir (typically `~/.local/share/nonebot2/nonebot_plugin_hermes/messages.db`); can also be redirected by `LOCALSTORE_*` env vars |
| `HERMES_STORAGE_MESSAGE_RETENTION_DAYS` | `30` | Message log retention days; vacuum cron deletes anything older |
| `HERMES_STORAGE_MESSAGE_MAX_ROWS` | `100000` | Hard row cap; vacuum cron deletes oldest by ts when exceeded |
| `HERMES_IMAGE_CACHE_DIR` | (empty) | Image byte cache directory. Empty falls back to localstore's plugin_cache_dir (typically `~/.cache/nonebot2/nonebot_plugin_hermes/images/`) |
| `HERMES_IMAGE_CACHE_QUOTA_MB` | `200` | Image cache total size cap (MB); LRU-by-atime eviction during vacuum |
| `HERMES_IMAGE_FETCH_TIMEOUT_S` | `10` | Per-image HTTP fetch timeout, seconds |
| `HERMES_IMAGE_FETCH_MAX_ATTEMPTS` | `2` | Total HTTP attempts per image (1=no retry, 2=one retry, …) |

### Busy notice (a visible signal when an explicit mention is dropped by plumbing)

When the `_refire` chain hits `MAX_REFIRE_DEPTH=3` (≥ 4 explicit mentions queued in the same group within a short window while upstream Hermes can't keep up), the newest explicit mention gets dropped by the plumbing. The plugin then attaches `HERMES_BUSY_EMOJI_ID` (default 97 = the classic QQ face /擦汗, wiping sweat) to that original message and **does not clear it**, as a visual "I saw you, but I really can't keep up" signal.

Different semantics from the ack-feedback emoji (`HERMES_ACK_EMOJI_ID`, default 341 /打招呼):
- ack-feedback: stays for the duration of `chat()`, cleared on completion — "working on it"
- busy notice: attached when the depth cap is hit, **never cleared** — "can't get to it"

The two defaults are deliberately picked to look clearly distinct; verify the emoji_id table of your OneBot implementation before changing them.

Only the OneBot v11 group path is covered; other adapters (Telegram / Discord) or a missing msg_id degrade to a WARN log with no text fallback, to avoid adding noise in a burst context.

One related failure path does have a user-visible fallback: when upstream Hermes returns 5xx or the network drops, an explicit mention on the refire path replies with `HERMES_TRANSPORT_ERROR_FALLBACK_TEXT` (default "嗯…我这边遇到点状况,稍后再问一次"). Set it to an empty string to disable the text fallback.

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
