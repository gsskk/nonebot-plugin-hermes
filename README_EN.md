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

## Per-group endpoint routing / multiplexing (0.5.1+, off by default)

Route specific groups to their own Hermes **profile** — each gets its own toolset, model and file
workspace; the reverse channel's permission scope narrows per endpoint too. Only need the bot to stop
mentioning group A's business in group B? You don't need any of this — see "Long-term Memory Scope"
above.

Configuration, the Hermes-side steps, reverse-channel token narrowing, an end-to-end example
(including **several groups sharing one profile**), and the operational limits now live in their own
page:

**→ [Per-group routing / multiplexing / profiles — full doc](PROFILES_EN.md)**

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
| `hermes-optimize-state` | **Hermes host** | Dedupes the `<recent_messages>` windows re-injected into every historical turn of Hermes' `state.db`, strips the static protocol reminder, then reclaims space. Reports only by default; `--apply` backs up the database first |
| `hermes-repair-sessions` | **Hermes host** | Unsticks sessions in Hermes' `state.db` deadlocked by ambiguous compression lineage. Reports only by default; `--apply` backs up the database first |

"Runs on" follows the data each tool touches, not where the plugin happens to be installed. On a
single-host setup all four commands are simply on PATH; on a **split deployment the Hermes host
usually has no plugin install**, and you do not need to add one — all four are single files at the
repository root, import nothing but the standard library, and never import the package itself:

```bash
git clone https://github.com/gsskk/nonebot-plugin-hermes.git
cd nonebot-plugin-hermes
python3 hermes_repair_sessions.py            # exactly equivalent to hermes-repair-sessions
```

(Copying just the one file over works too — except for `hermes-install-skill`, which reads
`nonebot_plugin_hermes/skill/SKILL.md` from the same repo and therefore needs the repo directory.)

#### `hermes-optimize-state`: clear the windows re-injected into the transcript

Both the reactive and passive paths wrap the `<recent_messages>` window into the user message. The
window is dozens of lines and each turn adds only one or two, so the same group message ends up
stored dozens of times in `state.db`; Hermes replays the whole transcript every turn, making this
duplication both disk and bill. This tool folds the historical windows back into an incremental
shape: each group message is kept only on its first appearance, and the static protocol reminder
carried by every line is dropped (the `decision_protocol` on the system side already states the same
thing). `<runtime_state>` and `<current_message>` are the current turn's live state and are left
byte-for-byte intact.

```bash
hermes-optimize-state                  # report only: how much would be saved, which rows change
hermes-optimize-state --sample         # also print 3 before/after comparisons — see whether the result is still readable
hermes-optimize-state --sample 5       # sample 5
hermes-optimize-state --apply          # back up, rewrite, merge FTS segments + VACUUM
```

**Multiple profiles: run it per database.** Each profile is a full `HERMES_HOME`, so there are three
ways to point at one:

```bash
hermes-optimize-state --profile team          # ~/.hermes/profiles/team/state.db
HERMES_HOME=/opt/data hermes-optimize-state   # custom deployment
hermes-optimize-state --db /path/to/state.db  # give the full path directly, overriding all inference
```

`--profile default` means the root home (`~/.hermes/state.db`), not `profiles/default` — same rule as
upstream `get_profile_dir`; profile names are lowercased; `--profile` is always anchored to the
**root** home, so from inside the team profile `--profile other` resolves to `~/.hermes/profiles/other`,
not a nested path.

The resolved source is the final answer: **if the specified database does not exist the tool errors
out, it never falls back to another profile**. A mistyped profile name, or a profile that has not been
initialised yet, both have this shape — falling back would silently land the rewrite on the default
profile's database, which afterwards looks perfectly normal.

`--sample` shows the **post-rewrite** lines (what the model will actually read next turn), with the
dropped duplicate messages folded into a one-line count — a compression ratio cannot answer "is it
still readable?". Samples are taken from the session with the most rewritten rows, spread evenly by
position: the dedup effect varies enormously with position (the cold-start turn keeps almost the whole
window, mid-conversation turns keep only one or two messages), so showing only the biggest savers
would overstate the effect.

Stop `hermes-gateway` first (the tool exits if it can't take the write lock). A few things worth
knowing up front:

- **Only touches `sessions.source='api_server'` and `role='user'` rows** — CLI / TUI / cron sessions
  are not plugin traffic and are left untouched; the assistant side is the model's own output and is
  also left alone.
- **The dedup unit is the message, not the physical line.** A history line's body can itself contain
  newlines (bot-sent lists, multi-paragraph replies); deduping by physical line would strip a line
  shared by two messages off the later one — the message gets shaved while its first line stays.
- **Keyed on the `[m:<id>]` primary key, and computed per session.** Each Hermes session is an
  independent transcript; the new generation after `/clear` should rebuild context, so dedup never
  crosses sessions.
- **Self-proving invariant**: before rewriting it records each message's key **and a body digest**,
  then re-checks each one afterwards — if any is missing, or a surviving body is not one of the
  versions the original contained, the whole thing rolls back. Keys alone are not enough: a message
  shaved of a few body lines still has its first line, so the key still resolves.
- **The FTS indexes are maintained by triggers following the `UPDATE`**, but the triggers hang off a
  rebuild high-water marker — mid-rebuild a rewrite would bypass them and silently corrupt the search
  index. If the marker is present the tool refuses to run; finish `hermes sessions optimize-storage`
  first.
- Side effect: a given group message afterwards matches full-text search once (rather than once per
  turn that echoed it) — still findable.
- Cost: the rewritten session takes one full prompt-cache miss on its next turn, then rebuilds the
  cache against the new, smaller prefix.

Pure space reclamation (without changing content) is built into upstream: `hermes sessions optimize`
merges FTS segments + `VACUUM`, `hermes sessions prune --older-than N` deletes sessions by retention,
`hermes sessions optimize-storage` migrates the old inline-FTS layout to the compact one. What this
tool adds is the one thing none of them do: **duplicate copies of the same content within a
transcript**.

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
| `HERMES_GROUP_ENDPOINTS` | `{}` | Per-group endpoint table, keyed `{adapter}:{group_id}`, value `{"url": …, "key": …, "timeout": …}`. Empty = everything goes to `HERMES_API_URL`. Also the single source of the reverse channel's scope — see [PROFILES_EN.md](PROFILES_EN.md) |
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
| `HERMES_ACTIVE_SESSION_TTL_SEC` | `300` | Active-window TTL in seconds; sliding renewal on each reply. A chat turn that outruns the TTL does not let the window expire mid-turn (lease); at turn end the remaining window is topped up to a 10s floor — enough for queued messages to run, not a fresh full TTL |
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
