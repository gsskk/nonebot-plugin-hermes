# Per-group endpoint routing (profiles / multiplexing)

> 0.5.1+, off by default. Extracted from the [README](README_EN.md) into its own page.

Route specific groups to their own Hermes **profile**, so each of those groups gets its own toolset,
model and file workspace.

**First check this is what you want:** if you only need the bot to stop mentioning group A's business
in group B, `HERMES_HONCHO_ENABLED` (the "Long-term Memory Scope" section in the README) is enough —
single process, no deployment change, no per-group profile to maintain. This section solves a
different problem: **group A can only look things up, group B may run code**. It happens to isolate
memory too (each profile has its own state.db), at the price of one more `HERMES_HOME` to maintain
per endpoint.

The reverse channel (`push_message`, etc.) derives its permission scope from this same routing table
and narrows per endpoint — see "The reverse channel narrows automatically" below.

---

## Plugin-side configuration

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

---

## Worked example: several groups, some sharing one profile

This is the most common — and most often misconfigured — shape: **a few groups share one profile**,
while some others each use a different profile. The one sentence to internalize first:

> **The number of named MCP servers the reverse channel needs is decided by the number of distinct
> profiles / distinct keys, not the number of groups.** Groups that share a key fall into the same
> scope automatically, and one server covers all of them.

Suppose 6 groups are in the routing table. Four of them (`10001`–`10004`) share profile **team-a**
(the same `API_SERVER_KEY`); the other two (`10005`, `10006`) use profile **lab** (a different key).
Every other group and all private chats use the default endpoint. → **2 named profiles**, so the
reverse channel needs **2 named servers** (`nonebot-team-a`, `nonebot-lab`) plus one `nonebot-default`
for the complement — **not 6**.

**① Plugin-side `.env`** (`HERMES_GROUP_ENDPOINTS` must be a **single line** in `.env`; wrapped here
for readability):

```jsonc
{
  "onebotv11:10001": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10002": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10003": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10004": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10005": { "url": "http://10.0.0.2:8642/p/lab",    "key": "<lab API_SERVER_KEY>" },
  "onebotv11:10006": { "url": "http://10.0.0.2:8642/p/lab",    "key": "<lab API_SERVER_KEY>" }
}
```

For groups on the same profile, fill in the **exact same** `url` and `key`. Giving them different keys
triggers a startup WARNING ("one endpoint configured with several different keys, at least one will
401") and splits them into two reverse-channel scopes.

**② The Hermes default profile** (`~/.hermes/config.yaml`) — every MCP connection and token is
established here:

```yaml
mcp_servers:
  nonebot-default: { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <global HERMES_API_KEY>" } }
  nonebot-team-a:  { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <team-a API_SERVER_KEY>" } }
  nonebot-lab:     { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <lab API_SERVER_KEY>" } }

platform_toolsets:
  api_server: [<default's existing toolsets>, nonebot-default]   # the default profile lists only its own name
```

**③ team-a** (`~/.hermes/profiles/team-a/config.yaml`) — only **references** its own name:

```yaml
platforms:
  api_server: { enabled: false }                    # port-binding platforms stay on the default profile
platform_toolsets:
  api_server: [<team-a's toolsets>, nonebot-team-a]
mcp_servers:
  nonebot-team-a: { url: http://<bot>:8643/mcp }    # the name is what enables it; url/headers are inert here
```

**④ lab** (`~/.hermes/profiles/lab/config.yaml`) is analogous — swap `team-a` for `lab`, reference
`nonebot-lab`.

The result: the agents of team-a's four groups only see `mcp__nonebot_team_a__*`, and their requests
carry team-a's token → the plugin resolves the scope to "groups owned by team-a" = exactly those four;
lab likewise. Why this is sufficient is explained below.

---

## The original default endpoint does not go away

With multiplexing on, the listener is still owned by the **default profile**: the old prefix-less URL
and the old key keep working, and `API_SERVER_KEY` supplied through systemd `Environment=` / docker
`environment:` still resolves (upstream keeps an `os.environ` fallback for the default profile's
credential read). Only **newly added named profiles** need their key in their own profile `.env`.

---

## What to do on the Hermes side

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
# "Security Best Practice: Restricting API Server Toolsets" in the README.

HERMES_HOME=$TEAM_HOME hermes-install-skill       # skills are installed per profile

# Reverse channel: only for profiles that need it. **The two deployment shapes differ here** —
# under multiplexing the Bearer must be configured on the DEFAULT profile and the header written
# here has no effect (see "The reverse channel narrows automatically" below). The line below is the
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

---

## The reverse channel narrows automatically

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
> name (`mcp__<server>__<tool>`), so the same URL may be connected more than once under different names
> — exactly the `nonebot-default` / `nonebot-team-a` / `nonebot-lab` setup from the "Worked example"
> above: one **same-URL, distinct-name, distinct-Bearer** server per endpoint on the default profile,
> and each named profile declaring only its own name.
>
> **The default profile must allowlist itself too**
> (`platform_toolsets.api_server: [<existing toolsets>, nonebot-default]`), or it gets every server
> name — and with it the ability to act on everyone else's groups.
>
> Three costs: **the default profile's `config.yaml` holds every endpoint's token** (it owns all
> connections — so the default profile must be trusted and toolset-restricted; an agent there that can
> read files can read every token), one live connection per server name, and the name must match in both
> files (a typo means that profile silently gets no tools). If the Bearer is written as a
> `${MCP_*_API_KEY}` reference, the variable has to live in the **default profile's `.env`** —
> interpolation happens when the connection is made at startup, in the default scope.
>
> At startup `multiplex_reverse_channel_notices()` emits an **INFO**-level note whenever the routing
> table contains a `/p/<profile>` url while `HERMES_MCP_ENABLED=true`, pointing at the setup above. It
> is INFO rather than WARNING because the plugin cannot verify from its own side whether the Hermes end
> is configured correctly — this note fires even on a correct setup, and a WARNING that fires on every
> correct deployment only breeds alarm fatigue. **If you've configured it correctly, just ignore it.**
> The real failure signal comes at push time: a precise `拒绝越权` (permission-denied) WARNING
> (fail-closed) — that is the one to watch.

Every refusal logs a WARNING on the bot side naming the caller's endpoint, its scope and the refused
target — check that first when "the reverse channel stopped working for one group".

---

## Operational cost and known limits

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
