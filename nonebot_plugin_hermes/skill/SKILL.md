---
name: nonebot-bridge
description: |
  Adapter for chatting in third-party group/private chats via the nonebot-plugin-hermes bridge.
  Activates when you see `mode: reactive` in a system message, or a tool result mentions
  `nonebot-bridge`. Use to push messages to a chat group, list active groups, or pull context.

tools:
  - push_message
  - list_active_sessions
  - get_recent_messages
  - get_message_images
---

# nonebot-bridge — chat adapter (M1)

You are wired to a nonebot2 process that forwards group / private chat messages to you and
allows you to send messages back via the `push_message` tool.

## Modes

- **reactive** (M1): A user @-mentioned you in a group. For the next 5 minutes you can
  freely insert messages into that group via either:
  1. Returning a `submit_decision` tool call in your normal chat completion response (the
     plugin will send it for you). **This is the preferred path** — it preserves the agent loop.
  2. Calling `push_message` directly. Use only for **delayed** replies that don't fit the
     request/response shape (e.g., "let me think… [later] here's my answer").

## Tools

### `push_message(adapter, group_id, text, image_urls?)`

Send one message into a group. Constraints:
- The (adapter, group_id) must currently be in an **active reactive session**. If not,
  returns `ok=false` with `error="no active reactive session"`. Do not retry — the user
  has not invited you in.
- The (adapter, group_id) must be **known** (the bot has seen at least one message in that
  group since process start). A fresh nonebot restart causes `error="unknown target"` until
  members talk again.

### `list_active_sessions(adapter?)`

List all groups currently in active reactive state. Returns sessions with `expires_at`,
`triggered_by`, and `topic_hint`. Use to decide whether a delayed `push_message` is still
welcome.

### `get_recent_messages(adapter, group_id, limit?, before_ts?)`

Pull the latest `limit` messages from a group buffer (capped at 50). Prefer the
`<recent_messages>` block already inlined in your reactive prompt — this tool is expensive
(burns context) and should only be used when you need to look further back than ~20 messages.

Each returned message carries:
- `id` — DB primary key, stable across turns; pair with `get_message_images` to fetch images
- `image_count` — number of images attached (0 = text only)
- `text / user / ts / is_bot` — as before

### `get_message_images(message_ids, adapter?, group_id?)`

Fetch image bytes for up to 4 message ids in a single call. Returns a content array
mixing a JSON header (per-image metadata) with `TextContent` markers + `ImageContent`
base64 blocks. The image content flows through Hermes's multimodal injection pipeline,
so on your next LLM turn you'll **actually see** the images.

Each per-image result has `available: true|false`. When unavailable, `reason` is one of:
- `cache_miss` — image was never fetched (URL expired before download) or has been
  evicted from the local cache; tell the user the image is gone, request a resend
- `not_found` — the message_id is not in the DB anymore (past 30-day retention or
  hard row cap)
- `too_large` — image exceeds 5 MB; ask user for a smaller version
- `cap_exceeded` — your call totaled more than 25 MB or hit the per-call cap; retry
  with fewer ids

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

### Honesty about attempts

When the user asks you to do something (look up data, search, fetch info):

- **Try first.** If your tools can actually attempt it, run them and put the real result
  into `reply_text`.
- **If the attempt fails or the request is genuinely beyond your reach,** say so plainly:
  "I couldn't find that — try X instead" / "我这查不到 X,可以用 Y 看看".
- **Do not** say "let me check" / "稍等" / "I'll look it up" / "我去看看" without making
  a real attempt. In reactive mode, once `reply_text` is sent the turn ends — these
  phrases dangle a promise you cannot keep.
- Act first, talk after. If you can't, say so directly and stop.

## Historical media recall

When the user refers to a past image (e.g. "上图", "这图", "刚才那张", "他刚发的"),
the `<recent_messages>` block shows `[图片]` placeholders but not the actual image.
Two-step protocol:

1. **Identify the message.** Each line in `<recent_messages>` starts with `[m:<id>]` —
   that id is the DB primary key, stable across turns. Heuristics:
   - "上图" / "这图" / "刚才那张" → most recent line where the message has an image
   - "我刚发的" → most recent image-bearing message from the current speaker
   - "他刚发的" → most recent image-bearing message from the user named in context
2. **Fetch the bytes.** Call `get_message_images(message_ids=[<id>])`. The returned
   ImageContent blocks become real visual input on your next LLM turn.

The `[m:<id>]` id is **stable** across turns — the same image always has the same label,
unlike positional schemes (#1, #2, …) which shift when new messages arrive. Use it to
anchor cross-turn references ("I analyzed m:1234 last turn, user is asking about it again").

The `<current_message>` block does NOT carry `[m:<id>]` — the current turn hasn't been
persisted yet. Only past messages have stable ids.

### When to skip the tool

- The user did not reference an image — don't fetch (token cost).
- `image_count == 0` on every recent message — tell the user directly, nothing to look at.
- Identical image already fetched this turn — reuse the previous result.

## Forwarded message blocks

Group messages may contain `<forwarded_messages count="N">...</forwarded_messages>`
blocks, or self-closing summary / fetch-failed variants of the same tag. These blocks
are transcript snapshots of a "merged forward" message the user shared:

- `[图片] [语音] [视频] [文件:...]` placeholders **inside** the block have **no
  retrievable URL**. Do not call `get_message_images` or any other media-recall tool
  against media that only appears inside a forwarded block — the tool cannot return
  forwarded media.
- Placeholders **outside** any forwarded block follow the normal retrieval rules.
- `status="fetch_failed"` means a merged-forward message exists but the plugin could
  not expand it. Treat it as "the user shared a chat log, contents unknown."
- The self-closing `preview="..."` form is a compact summary of a forwarded block
  that appeared in an earlier turn. Contents are deliberately minimised; do not ask
  the user to re-share for more detail.

## What NOT to do

- Don't call `push_message` for normal request/response replies — return `submit_decision`
  instead. The plugin handles the send for you.
- Don't call `push_message` to "ping" or "say hi" to inactive groups. The reactive guard
  will return 422 and your message will be discarded.
- Don't try to set user profiles / facts via this skill. M1 has no user profile support.
- Don't assume `reply_to_msg_id` works — M1 does not implement it.
- Don't call `get_message_images` speculatively for every reactive turn — only when the
  user's text actually references a past image. Each call costs bytes + an extra LLM turn.
- Don't call `get_message_images` against placeholders that appear inside a
  `<forwarded_messages>` block — those have no fetchable URL.
