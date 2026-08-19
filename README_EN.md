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

### 🔄 Session Rotation (0.4.5+)

The plugin keeps a conversation continuous through the `X-Hermes-Session-Id` request header, whose
key is derived from `{adapter}+{private|group}+{ids}` (`/clear` bumps a `-gN` suffix). That id is
not permanent: when Hermes auto-compresses the context it **rotates the session** — the old id is
closed with `end_reason='compression'`, a continuation child is created, and the new id comes back
in the **response header** `X-Hermes-Session-Id`.

Since 0.4.5 the plugin adopts that value and persists the `internal_id → session key` mapping to
`session_keys.db`, next to the message database (the `/clear` generation is persisted too, so a
restart no longer resurrects a cleared session).

0.1.0 through 0.4.4 never read that response header, which pinned every turn back onto the closed
parent session: reads still followed the compression tip, but every write failed, and each further
compression forked yet another sibling snapshot off the same parent. Once more than one live child
exists, Hermes' `find_live_compression_child()` treats the lineage as ambiguous and fails closed —
that session can never be written to again. Older Hermes builds tolerated appends to a closed
session, so this stayed silent for a long time; after the upstream 2026-07-23
`fix(compression): recover rotated session lineage` it became a hard failure and the logs fill with
`Session '…' is closed by compression`. Use `hermes-repair-sessions` to fix existing damage.

### 🧠 Long-term Memory Scope (0.5.0+, off by default, not recommended yet)

> **⚠️ Not recommended for now.** The api_server path does not pass user identity through to the
> memory layer, so all group members collapse into a single memory peer — the benefit today is
> limited, while Honcho's background derivation, retrieval and embeddings add ongoing extra token
> cost. Enable it once upstream supports inbound user identity and the ingest cleanup lands — see
> the disable/re-enable section in [`honcho/`](honcho/).

Hermes' long-term memory provider (currently Honcho) does **not** separate groups on its own. When
the plugin doesn't tell it which conversation a turn belongs to, it names the memory scope with its
own fallback strategy — and both fallbacks are bad:

- global / per-directory strategy → **every group writes into one shared memory**, so what the bot
  learns in group A leaks into group B;
- per-session strategy → the memory is keyed on the Hermes session id, which **rotates on every
  automatic compression** (see the section above), so memory restarts from scratch each time.

With this feature on, the plugin sends an explicit `X-Hermes-Session-Key` header. It is a second,
independent dimension next to `X-Hermes-Session-Id`: the latter decides which transcript a turn
continues and rotates on `/clear` and compression; the former decides who the memory belongs to and
stays constant across both.

```dotenv
HERMES_HONCHO_ENABLED=true
# Group memory granularity: false = one memory per group (members share it), true = per member
HERMES_GROUP_SESSIONS_PER_USER=false
```

A deployment example (compose file + config, with cost notes and verification steps) lives in [`honcho/`](honcho/).

**Prerequisites** (miss any one and the feature silently does nothing, or only half-works):

1. A memory provider configured on the Hermes side (`hermes memory setup`). Honcho itself is either
   Honcho Cloud (usage-billed) or a self-hosted Postgres + pgvector + FastAPI stack — not just a flag.
2. `HERMES_API_KEY` set in the plugin. Upstream requires auth for this header; without a key the
   plugin omits the header and warns at startup.
3. **No `peerName` key** in `~/.hermes/honcho.json` on the Hermes side. When it is set, every group
   shares one memory peer, so the derived layer (representation / peer card) is shared across groups
   and only the transcript layer ends up isolated. The `hermes memory setup` wizard defaults it to
   your username and won't accept a blank — delete the key afterwards. See
   [`honcho/README.md`](honcho/README.md).

**Cost of switching**: turning it on renames the memory scope, so memory accumulated under the old
scope is no longer visible. The data stays on the Hermes side — turning the switch off restores the
previous behaviour. Also note memory needs time to accumulate; the first week or two feels flat.

The key defaults to `agent:main:nonebot-{adapter}:group:{group_id}`, matching the naming format of
Hermes' native adapters. The `nonebot-` prefix prevents collisions when a native Hermes adapter
writes into the same memory workspace. All three templates (group-shared / group-per-user / DM) can
be overridden via `HERMES_*_SESSION_KEY_FORMAT`, though you rarely need to.

> [!NOTE]
> This switch isolates **memory** only. The `session_search` tool queries the whole state.db without
> a per-group filter (see the toolset warning above); to close that too, drop the tool from
> `platform_toolsets.api_server` on the Hermes side. Terminal/file tool workspaces are likewise
> unaffected by this switch.

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

The plugin ships a `SKILL.md` (reactive decision contract + reverse-channel usage). It must land in
`<HERMES_HOME>/skills/nonebot-bridge/` (default `~/.hermes/skills/nonebot-bridge/`) **on the Hermes
host** — installed on the wrong machine, Hermes never
reads it and the skill has no effect.

When the bot and Hermes share a host, run any of the following from the bot project directory:

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

On a **split** deployment the Hermes host usually has no plugin install, and you do not need one: the
script is stdlib-only, so a clone is enough. It reads `nonebot_plugin_hermes/skill/SKILL.md` by relative
path, so bring the whole repo rather than the single file:

```bash
git clone https://github.com/gsskk/nonebot-plugin-hermes.git
cd nonebot-plugin-hermes
python3 hermes_install_skill.py
```

(Running it on the bot host and copying `~/.hermes/skills/nonebot-bridge/SKILL.md` across works too.)

Then register the plugin's MCP server in `~/.hermes/config.yaml`, replacing `<HERMES_API_KEY>` with the same key you generated earlier (used for two-way auth):

```yaml
mcp_servers:
  nonebot-bridge:
    url: http://127.0.0.1:8643/mcp
    headers: { Authorization: "Bearer <HERMES_API_KEY>" }
```

When the plugin's `SKILL.md` later changes, re-run with `--force` using any of the entries above, e.g. `uv run hermes-install-skill --force` or `.venv/bin/hermes-install-skill --force`.

## Per-group endpoint routing (0.5.1+, off by default)

Route specific groups to their own Hermes **profile**, so each of those groups gets its own toolset,
model and file workspace.

**First check this is what you want:** if you only need the bot to stop mentioning group A's business
in group B, `HERMES_HONCHO_ENABLED` above is enough — single process, no deployment change, no
per-group profile to maintain. This section solves a different problem: **group A can only look things
up, group B may run code**. It happens to isolate memory too (each profile has its own state.db), at
the price of one more `HERMES_HOME` to maintain per endpoint.

### Configuration

```dotenv
# Keys are {adapter}:{group_id}; unlisted groups and all private chats use HERMES_API_URL
HERMES_GROUP_ENDPOINTS='{"onebotv11:12345": {"url": "http://127.0.0.1:8642/p/team-a", "key": "<team-a API_SERVER_KEY>"}}'
```

Both deployment shapes share the same `url` field:

| Shape | On the Hermes side | `url` |
|-------|--------------------|-------|
| Multiplexed (recommended) | `hermes config set gateway.multiplex_profiles true`, then restart the gateway | `http://host:8642/p/<profile>` |
| Separate processes | one api server per profile | `http://host:8643` (its own port) |

An empty `key` falls back to the global `HERMES_API_KEY`; an empty `timeout` falls back to
`HERMES_API_TIMEOUT`.

> [!WARNING]
> **Profile names must be lowercase** (`[a-z0-9][a-z0-9_-]{0,63}`). `hermes profile create TeamA`
> normalizes the name before writing it to disk (`profiles/teama/`), but the URL prefix is **not**
> normalized — upstream only `strip()`s it and compares against the on-disk directory names, so
> `/p/TeamA/` against `profiles/teama/` is a hard **404**. Use `-` or `_` to separate words.

> [!IMPORTANT]
> **When the url points at a named profile, `key` is mandatory** — different from the default
> profile's and at least 16 characters. Three reasons: upstream validates that profile's own
> `API_SERVER_KEY` (the global key always 401s); it doubles as the reverse channel's identity (below);
> and it is **the only alarm for "I forgot to enable `gateway.multiplex_profiles`"** — with
> multiplexing off, upstream **silently ignores** the `/p/<profile>/` prefix and serves the request as
> the default profile, so only a key mismatch turns that into a visible 401 instead of "everything
> looks fine" with zero isolation.

### The original default endpoint does not go away

With multiplexing on, the listener is still owned by the **default profile**: the old prefix-less URL
and the old key keep working, and `API_SERVER_KEY` supplied through systemd `Environment=` / docker
`environment:` still resolves (upstream keeps an `os.environ` fallback for the default profile's
credential read). Only **newly added named profiles** need their key in their own profile `.env`.

### What to do on the Hermes side

Once, on the **default profile** (it is the multiplexer):

```bash
hermes config set gateway.multiplex_profiles true
hermes gateway restart
```

With multiplexing on, do **not** run `hermes gateway start` for a secondary profile. A secondary
profile's own config.yaml should look like this:

```yaml
# ~/.hermes/profiles/team-a/config.yaml — the SECONDARY profile's, not the default's
platforms:
  api_server:
    enabled: false                     # port-binding platforms stay on the default profile

mcp_servers:
  nonebot-team-a:                      # the name is what enables it; url/headers are inert here
    url: http://<bot>:8643/mcp

platform_toolsets:
  api_server: [<this profile's existing toolsets>, nonebot-team-a]   # omit it and the profile
                                                                     # gets no reverse channel
```

And the matching default profile — every MCP connection and token is established there:

```yaml
# ~/.hermes/config.yaml — the DEFAULT profile
mcp_servers:
  nonebot-default:                     # the complement: groups not in the routing table
    url: http://<bot>:8643/mcp
    headers: { Authorization: "Bearer <global HERMES_API_KEY>" }
  nonebot-team-a:                      # groups owned by team-a
    url: http://<bot>:8643/mcp
    headers: { Authorization: "Bearer <team-a's API_SERVER_KEY>" }

platform_toolsets:
  api_server: [<your existing toolsets>, nonebot-default]   # the default profile lists only its own
```

Besides `api_server`, the same disable rule covers `webhook`, `msgraph_webhook`, `wecom_callback`,
`bluebubbles`, `sms`, `whatsapp_cloud`, `line`, and `feishu` when `connection_mode: webhook`.
`hermes profile create --clone` copies the default profile's config.yaml wholesale, so always check
this entry. Leave it on and the gateway startup log repeats `Skipping secondary profile '<name>' due
to port-binding config error` and **every** adapter of that profile stays down — while `/p/<name>/`
keeps working, which is why the warning is easy to dismiss as noise.

The `mcp_servers` / `platform_toolsets` blocks are only needed if you use the reverse channel; the
trade-offs are under "The reverse channel narrows automatically" below. Conversely, if you picked the
"separate processes" shape, leave multiplexing **off**.

The `Next steps` block printed by `hermes profile create` ends with `<name> gateway start`, which is
written for the default one-process-per-profile shape — **do not run it under multiplexing** (do run
`<name> setup`; `<name> chat` is a cheap way to confirm its key works). Upstream does guard against it
and points you at the default profile's `hermes gateway restart`, but that guard is not insurance: it
only fires while the **default gateway is running** (with it stopped, the command happily starts a
separate process and you double-bind once the multiplexer comes back — two pollers on one bot token,
port conflicts), and only when the profile is inside `multiplex_profile_allowlist`; an excluded profile
is waved through.

`hermes config set gateway.multiplex_profiles true` may print `not a recognized config key` and
suggest `gateway.multiplex_profile_allowlist` — **do not follow that suggestion**. The key *is* read at
runtime (`gateway/config.py` has a branch specifically for it, whose comment names this exact
command); the warning is only the upstream CLI's key table missing the nested form. To silence it, use
the equivalent top-level form `hermes config set multiplex_profiles true`, or pass `--force`.
`multiplex_profile_allowlist` is a different setting — which named profiles the multiplexer serves.
**Leaving it unset serves all of them**; setting it to `[]` (or to a malformed value, which fails safe
to `[]`) serves only the default profile and your `/p/team-a/` will 404.

After restarting, confirm the prefix really took effect (the only ground truth):

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer <team-a's own API_SERVER_KEY>" \
  http://<hermes-host>:8642/p/team-a/v1/models
# 200 = live; 401 = prefix silently ignored (served as the default profile, i.e. not enabled);
# 404 = prefix rejected (profile missing, or excluded by the allowlist)
```

Per new endpoint:

```bash
export TEAM_HOME=~/.hermes/profiles/team-a

hermes profile create team-a                       # own state.db / memory / skills / config.yaml
team-a setup                                       # its own LLM provider key — see the WARNING below
echo "API_SERVER_KEY=$(openssl rand -hex 32)" >> $TEAM_HOME/.env   # must differ from the default profile

# what this group is allowed to do — the one thing this feature cannot be replaced for.
# Edit platform_toolsets.api_server in $TEAM_HOME/config.yaml; see the toolset table under
# "Security Best Practice: Restricting API Server Toolsets" above.

HERMES_HOME=$TEAM_HOME hermes-install-skill       # skills are installed per profile

# Reverse channel: only for profiles that need it. **The two deployment shapes differ here** —
# under multiplexing the Bearer must be configured on the DEFAULT profile and the header written
# here has no effect (see "The reverse channel narrows" below). The line below is the
# separate-processes shape:
HERMES_HOME=$TEAM_HOME hermes mcp add nonebot --url http://<bot>:8643/mcp
#   use the API_SERVER_KEY above as the Bearer token
```

**The only value that must match on both sides is that `API_SERVER_KEY`**: on the plugin side it goes
into `HERMES_GROUP_ENDPOINTS[...].key`; on the Hermes side it is both the profile's `API_SERVER_KEY`
and its MCP token. Rotating it means editing two places and covers both directions.

`hermes profile create` also drops a wrapper at `~/.local/bin/<name>` containing
`exec hermes -p <name> "$@"`, which means:

- **the profile name becomes a shell command.** Only `hermes` / `test` / `tmp` / `root` / `sudo` are
  reserved, so names like `web`, `top` or `docker` are accepted and will shadow the real command if
  `~/.local/bin` comes first on PATH — run `command -v <name>` before picking a name.
- hermes subcommands for that profile can then be written as `team-a config set …` /
  `team-a mcp add …` instead of `HERMES_HOME=… hermes …`. But `hermes-install-skill` is **this
  plugin's** own CLI, not a hermes subcommand, so it still needs `HERMES_HOME=`.

> [!WARNING]
> **Under multiplexing a named profile needs its own LLM provider key** — the model vendor's API key
> (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `NOUS_API_KEY` /
> `GEMINI_API_KEY`, …). Without it the agent cannot issue a single inference call. Note that this is
> a different key from the other two in this section:
>
> | Key | Who validates it | Where it lives |
> |---|---|---|
> | LLM provider key (e.g. `ANTHROPIC_API_KEY`) | the model vendor | `profiles/<name>/.env` |
> | `API_SERVER_KEY` | Hermes' own api_server inbound auth | `profiles/<name>/.env` |
> | the plugin's `HERMES_API_KEY` / entry `key` | same as above — it is what the plugin presents | the bot's `.env` |
>
> `hermes profile create` ends with a hint saying it will otherwise "inherit keys from your shell
> environment" — that only holds for single-profile deployments. With multiplexing on, credential
> reads are authoritative to the profile's secret scope and do **not** fall back to `os.environ` (the
> global exemption list only covers deployment-ish vars like PATH / HOME /
> `API_SERVER_HOST|PORT|ENABLED` — no API keys at all). A profile with an empty `.env` cannot run a
> single turn. Run `<name> setup`, or write the key straight into `profiles/<name>/.env`. **The same
> rule covers every credential that profile uses**, not just the LLM one — search
> (`EXA_API_KEY`, …), image generation and memory-provider keys all have to be in its own `.env`.

### The reverse channel narrows automatically

The reverse channel (`push_message` / `get_recent_messages` / `get_message_images` /
`list_active_sessions`) has **no second token table**: whichever endpoint's key a caller presents, it
may only act on that endpoint's groups; the global `HERMES_API_KEY` may only act on the
**complement** (groups not in the routing table, or whose entry has no key of its own); anything else
is a 401. With no routing table the complement is every group, i.e. exactly 0.5.0 behaviour.

In other words: **a group you want protected must be in the routing table and point at a named
profile**. Groups left in the complement are still readable and pushable by the holder of the
complement key (the default profile).

> [!IMPORTANT]
> **Under multiplexing you can control *which* profile has the reverse channel, but not *which token*
> it presents.** Upstream splits this into two layers:
>
> | Layer | Whose config | When |
> |---|---|---|
> | **Connection** (does the process hold this MCP client) | the **default** profile's `config.yaml` | once at gateway startup, process-global registry |
> | **Availability** (does the agent get those tools) | the **routed** profile's `config.yaml` | every request |
>
> So, under multiplexing:
>
> - **the Bearer must be configured on the default profile.** A `url` / `headers` written by
>   `hermes mcp add` inside a named profile never takes effect — a same-named server reuses the one
>   connection the default profile established.
> - conversely, **whether a profile gets the reverse channel is its own call**: listing the server name
>   in its `platform_toolsets.api_server` turns it on; the special `no_mcp` sentinel turns off all MCP
>   tools for that profile; writing neither leaves its MCP name set empty, which also yields nothing.
>   This layer is read per request — no restart needed.
> - with the most obvious setup (one `nonebot` server on the default profile) **the scope does not vary
>   per profile**: the plugin only ever sees that one shared token, usually the global
>   `HERMES_API_KEY` (scope = the complement), so no agent can push into a routed group — refused and
>   logged (fail-closed, but those groups effectively have no reverse channel).
>
> **You can still get per-endpoint tokens under multiplexing.** MCP tool names are namespaced by server
> name (`mcp__<server>__<tool>`), so the same URL may be connected more than once under different names:
>
> ```yaml
> # ~/.hermes/config.yaml (default profile — it owns every connection and token)
> mcp_servers:
>   nonebot-default:
>     url: http://<bot>:8643/mcp
>     headers: { Authorization: "Bearer <global HERMES_API_KEY>" }
>   nonebot-team-a:
>     url: http://<bot>:8643/mcp
>     headers: { Authorization: "Bearer <team-a's API_SERVER_KEY>" }
>   nonebot-lab:
>     url: http://<bot>:8643/mcp
>     headers: { Authorization: "Bearer <lab's API_SERVER_KEY>" }
> ```
>
> ```yaml
> # ~/.hermes/profiles/team-a/config.yaml — declare only its own name
> mcp_servers:
>   nonebot-team-a: { url: http://<bot>:8643/mcp }   # url/headers inert; the name is what enables it
> ```
>
> team-a's agent then sees only `mcp__nonebot_team_a__*` and its calls carry team-a's token, so the
> plugin's scope resolution lines up per endpoint. **The default profile must allowlist itself too**,
> or it gets every server name — and with it the ability to act on everyone else's groups:
>
> ```yaml
> # ~/.hermes/config.yaml
> platform_toolsets:
>   api_server: [<your existing toolsets>, nonebot-default]   # only its own name
> ```
>
> Three costs: **the default profile's `config.yaml` holds every endpoint's token** (it owns all
> connections — so the default profile must be trusted and toolset-restricted; an agent there that can
> read files can read every token), one live connection per server name, and the name must match in both
> files (a typo means that profile silently gets no tools). If the Bearer is written as a
> `${MCP_*_API_KEY}` reference, the variable has to live in the **default profile's `.env`** —
> interpolation happens when the connection is made at startup, in the default scope.
>
> `validate_endpoints()` warns at startup whenever the routing table contains a `/p/<profile>` url while
> `HERMES_MCP_ENABLED=true`, pointing at the setup above.

Every refusal logs a WARNING on the bot side naming the caller's endpoint, its scope and the refused
target — check that first when "the reverse channel stopped working for one group".

### Operational cost and known limits

- Each profile is a full `HERMES_HOME`: `hermes-repair-sessions` must be run per profile, and skill
  upgrades installed per profile.
- **After changing a group's routing entry, run `/clear` in that group**: session lineage carries no
  endpoint dimension, so the old session id does not exist in the new profile — upstream silently
  starts a fresh one and the same session name ends up in two state.db files.
- `/ping` probes only the caller's own endpoint (it is open to regular users, so it must not list
  other groups' routing keys); the per-endpoint roll-call lives in the admin-only `/hermes-status`.
- The startup capability probe (`/v1/capabilities`) only covers the default endpoint, so an outdated
  Hermes behind a named profile will not be flagged.
- Startup logs WARN per entry for: keys that can never match, non-http(s) urls, a missing key, a key
  shorter than 16 chars, and one endpoint configured with several different keys.
- `session_search` is still a separate cross-group channel: profiles separate it naturally; without
  profiles, remove that tool from `platform_toolsets.api_server`.

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

| Command | Runs on | Description |
|------|---------|------|
| `hermes-install-skill --force` | **Hermes host** | Installs `SKILL.md` into `~/.hermes/skills/nonebot-bridge/` (`--force` is required to overwrite an existing install) |
| `hermes-purge-media` | **bot host** | Purges inline base64 image bytes from the plugin's `messages.db`. Reports only by default; `--apply` writes back, `--vacuum` shrinks the file |
| `hermes-repair-sessions` | **Hermes host** | Unsticks sessions in Hermes' `state.db` deadlocked by ambiguous compression lineage. Reports only by default; `--apply` backs up the database first |

"Runs on" follows the data each tool touches, not where the plugin happens to be installed. On a
single-host setup all three commands are simply on PATH; on a **split deployment the Hermes host
usually has no plugin install**, and you do not need to add one — all three are single files at the
repository root, import nothing but the standard library, and never import the package itself:

```bash
git clone https://github.com/gsskk/nonebot-plugin-hermes.git
cd nonebot-plugin-hermes
python3 hermes_repair_sessions.py            # exactly equivalent to hermes-repair-sessions
```

(Copying just the one file over works too — except for `hermes-install-skill`, which reads
`nonebot_plugin_hermes/skill/SKILL.md` from the same repo and therefore needs the repo directory.)

`hermes-purge-media` cleans up a legacy artifact: earlier versions stored the whole
`data:image/…;base64,…` payload that api_server inlines into agent replies straight into the
message database, reaching megabytes for a single row. The current version blocks this on both
the write and the render side; this command only clears out the bytes already stored.

Run it on the **bot host**, where the plugin is installed:

```bash
uv run hermes-purge-media                    # report only: hits per group, largest row, reclaimable bytes
uv run hermes-purge-media --apply --vacuum   # purge and shrink the file
```

With a plain venv use `.venv/bin/hermes-purge-media`; with the venv already activated the bare
`hermes-purge-media` works. The bare form is only on PATH once the virtualenv is active.

Messages are never deleted — the image payload is replaced with a `[图片]` placeholder. Idempotent,
safe to re-run. `--vacuum` needs an exclusive lock; stop the bot first if it can't acquire one.

`hermes-repair-sessions` repairs session lineage in Hermes' own `state.db`. The symptom is Hermes
logging this over and over:

```
Session '…' is closed by compression; adopt its live continuation before appending messages
compression skipped: … no unique live child could be adopted
```

See "Session Rotation" above for the cause: plugin versions 0.1.0 through 0.4.4 did not adopt the
rotated session id, so every compression forked another snapshot child off the same closed parent.
Once more than one live child exists the upstream lineage check fails closed and the session can no
longer be written to — the transcript freezes and the context grows without bound (compression can
never complete).

Run it on the **Hermes host**. That machine usually has no plugin install, so the single-file form is
what the steps below use:

```bash
systemctl stop hermes-gateway     # the repair needs the write lock, and a running agent may hold stale session state

git clone https://github.com/gsskk/nonebot-plugin-hermes.git
cd nonebot-plugin-hermes
python3 hermes_repair_sessions.py            # report only: which sessions are stuck, which rows would change
python3 hermes_repair_sessions.py --apply    # back up the database, then reopen parents + retire snapshots

systemctl start hermes-gateway
```

If Hermes shares a host with the bot and the plugin is installed there, those two lines become
`uv run hermes-repair-sessions [--apply]`.

No message row is ever deleted. **Upgrade the plugin to 0.4.5+ and restart it first**, then stop the
gateway and run the repair — otherwise the next compression closes the parent again and it re-sticks
within a few turns. If a child looks like a genuinely continued session (its messages span far more
than a single batch write), the script skips that session and reports it for a human to judge.

## Configuration Options

All configuration options are set via the `.env` file, see detailed comments in [.env.example](.env.example).

| Option | Default | Description |
|--------|--------|------|
| `HERMES_API_URL` | `http://127.0.0.1:8642` | Hermes API Server URL |
| `HERMES_API_KEY` | (Empty) | API Key (Recommended for session persistence) |
| `HERMES_API_TIMEOUT` | `300` | API request timeout (seconds) |
| `HERMES_GROUP_ENDPOINTS` | `{}` | Per-group endpoint table, keyed `{adapter}:{group_id}`, value `{"url": …, "key": …, "timeout": …}`. Empty = everything goes to `HERMES_API_URL`. Also the single source of the reverse channel's scope — see "Per-group endpoint routing" above |
| `HERMES_GROUP_TRIGGER` | `at` | Group trigger mode: `at` / `all` / `keyword` |
| `HERMES_KEYWORDS` | `["/ai"]` | Trigger keywords for `keyword` mode |
| `HERMES_PRIVATE_TRIGGER` | `all` | Private trigger mode: `all` / `allowlist` |
| `HERMES_ALLOW_USERS` | `[]` | Allowed user IDs for `allowlist` mode |
| `HERMES_ALLOW_GROUPS` | `[]` | Allowed group IDs (empty for all) |
| `HERMES_ADMIN_USERS` | `[]` | Admin allowlist as `["telegram:<user_id>", "onebotv11:<user_id>"]`. **Empty = deny by default**; sensitive commands like `/hermes-status` only run if the caller's `adapter:user_id` is in this list |
| `HERMES_SESSION_SHARE_GROUP` | `false` | Share session within group |
| `HERMES_HONCHO_ENABLED` | `false` | **Not recommended yet** (limited benefit today, adds extra token cost — see "Long-term Memory Scope" above). Send `X-Hermes-Session-Key` so long-term memory is scoped per group/DM and survives compression rotation. Requires a memory provider upstream and `HERMES_API_KEY` here |
| `HERMES_GROUP_SESSIONS_PER_USER` | `false` | Group memory granularity. `false` = one memory per group (shared by members); `true` = one per member |
| `HERMES_GROUP_SESSION_KEY_FORMAT` | `agent:main:nonebot-{adapter}:group:{group_id}` | Template for group-shared memory keys |
| `HERMES_GROUP_PER_USER_SESSION_KEY_FORMAT` | `agent:main:nonebot-{adapter}:group:{group_id}:{user_id}` | Template for per-member group memory keys |
| `HERMES_PRIVATE_SESSION_KEY_FORMAT` | `agent:main:nonebot-{adapter}:dm:{user_id}` | Template for DM memory keys |
| `HERMES_MAX_LENGTH` | `4000` | Max reply length (truncated if exceeded) |
| `HERMES_IGNORE_PREFIX` | `["."]` | Ignore messages starting with these chars |
| `HERMES_PERCEPTION_ENABLED` | `false` | In groups with active_session=false, inject bystander history into the LLM on @-mention. **Auto-implied when `HERMES_ACTIVE_SESSION_ENABLED=true`; this flag is then a no-op**. Never injected in private chats (Hermes session already covers it) |
| `HERMES_PERCEPTION_BUFFER` | `10` | Number of messages to buffer for perception |
| `HERMES_PERCEPTION_TEXT_LENGTH` | `200` | Max text length per historical message |
| `HERMES_PERCEPTION_IMAGE_MODE` | `placeholder` | ⚠️ **Deprecated since 0.3** — historical image recall moved to the `get_message_images` MCP tool. This knob now only controls whether a `[图片]` placeholder appears in history text (`none` = no placeholder; anything else = add placeholder). `inline_labeled` is superseded; setting it is equivalent to `placeholder` |
| `HERMES_ACTIVE_SESSION_ENABLED` | `false` | Enable active group sessions (M1). When `false` the plugin behaves as in v0.1.6 |
| `HERMES_ACTIVE_SESSION_TTL_SEC` | `300` | Active-window TTL in seconds; sliding renewal on each reply |
| `HERMES_ACTIVE_SWEEP_INTERVAL_SEC` | `30` | Cron sweep interval for expired active sessions |
| `HERMES_REACTIVE_FOLLOWUP_WINDOW` | `4` | Reactive follow-up turns send only the newest N lines of `<recent_messages>` (plus the bot's own latest line); explicit-trigger turns always get the full window. Set `0` to disable trimming |
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
