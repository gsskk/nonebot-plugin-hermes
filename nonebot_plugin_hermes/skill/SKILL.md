---
name: nonebot-bridge
description: |
  Adapter for chatting in third-party group/private chats via the nonebot-plugin-hermes bridge.
  Use this skill when you need to push messages back to a chat group, list which groups
  currently expect your replies, or pull recent group context.

  Activates when:
    - You see a system message with `mode: reactive` indicating you are inside a 5-minute
      active window in a group chat.
    - You receive a tool result mentioning `nonebot-bridge`.

tools:
  - push_message
  - list_active_sessions
  - get_recent_messages
---

# nonebot-bridge — chat adapter (M1)

You are wired to a nonebot2 process that forwards group / private chat messages to you and
allows you to send messages back via the `push_message` tool.

## Modes

- **reactive** (M1): A user @-mentioned you in a group. For the next 5 minutes you can
  freely insert messages into that group via either:
  1. Returning a `submit_decision` tool call in your normal chat completion response (the
     plugin will send it for you). **This is the preferred path** — it preserves the agent loop.
  2. Calling `push_message` directly. Use this only for **delayed** replies that don't
     fit the request/response shape (e.g., "let me think about that for a minute…
     [later] here's my answer").

## Tools

### `push_message(adapter, group_id, text, image_urls?)`

Send one message into a group. Constraints:
- The (adapter, group_id) must currently be in an **active reactive session**. If not, the
  call returns `ok=false` with `error="no active reactive session"`. Do not retry —
  the user has not invited you in.
- The (adapter, group_id) must be **known** (the bot has seen at least one message in that
  group since process start). On a fresh nonebot restart, groups become known again as
  members talk; you may see `error="unknown target"` for the first ~minute after a restart.

### `list_active_sessions(adapter?)`

List all groups currently in active reactive state. Returns sessions with `expires_at`,
`triggered_by`, and `topic_hint`. Use to decide whether a delayed `push_message` is still
welcome.

### `get_recent_messages(adapter, group_id, limit?, before_ts?)`

Pull the latest `limit` messages from a group buffer (capped at 50). **This is expensive** —
each call burns context. Prefer the `<recent_messages>` block already inlined in your
reactive prompt. Use this only when you need to look further back than ~20 messages.

## Output contract (reactive)

In reactive mode, your reply MUST be a single `submit_decision` tool call:

```
{
  "should_reply": true | false,
  "reply_text": "string, required when should_reply=true; leave empty for silent",
  "topic_hint": "short label, optional",
  "should_exit_active": false  // see exit threshold below
}
```

When `should_reply=false`, the plugin sends nothing — that is the **correct** behavior for
"this conversation isn't about me, I'll stay quiet." Staying silent ≠ leaving — keep
`should_exit_active=false` so you still hear the next message in the active window.

### Exit threshold (`should_exit_active`)

This flag closes the active window. Once closed, non-@ messages are dropped before you
ever see them. Set the bar **high**:

- Set `true` only when:
  - User explicitly says goodbye / thanks that's enough / never mind / 不用了.
  - You completed the last explicit request **and** the most recent message is clearly
    unrelated to you.
  - Group topic has fully shifted away and stayed off-topic for 3+ messages.
- Keep `false` for:
  - User's verbal thinking (「我想想」, "let me see", hesitation, pauses).
  - Brief lulls or off-topic banter mid-conversation.
  - Any message you're unsure about — silence is cheap, premature exit is not.

## What NOT to do

- Don't call `push_message` for normal request/response replies — return `submit_decision`
  instead. The plugin handles the send for you.
- Don't call `push_message` to "ping" or "say hi" to inactive groups. The reactive guard
  will return 422 and your message will be discarded.
- Don't try to set user profiles / facts via this skill. M1 has no user profile support.
- Don't assume `reply_to_msg_id` works — M1 does not implement it.
