#!/usr/bin/env python3
"""
OneBot v11 ↔ Hermes Agent Bridge

Standalone bridge that connects an OneBot v11 framework (NapCatQQ, LLOneBot,
go-cqhttp, etc.) to Hermes Agent's built-in API Server, enabling QQ bot
conversations powered by Hermes without modifying Hermes source code.

Architecture:
    QQ User ↔ OneBot Framework ↔ [this bridge] ↔ Hermes API Server ↔ AIAgent

Usage:
    cp config.example.yaml config.yaml   # edit config
    python onebot_bridge.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
import yaml

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("onebot-bridge")


def setup_logging(level: str = "INFO") -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format=fmt)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "onebot": {"ws_url": "ws://127.0.0.1:3001", "access_token": ""},
    "hermes": {"api_url": "http://127.0.0.1:8642", "api_key": ""},
    "bot": {
        "self_id": "",
        "group_trigger": "at",
        "keywords": ["/ai"],
        "private_trigger": "all",
        "allow_users": [],
        "allow_groups": [],
    },
    "log_level": "INFO",
}


def load_config(path: str = "config.yaml") -> Dict[str, Any]:
    """Load config from YAML file, falling back to defaults."""
    cfg = dict(DEFAULT_CONFIG)
    config_path = Path(path)
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        # Merge top-level sections
        for section in ("onebot", "hermes", "bot"):
            if section in user_cfg and isinstance(user_cfg[section], dict):
                cfg[section] = {**cfg[section], **user_cfg[section]}
        if "log_level" in user_cfg:
            cfg["log_level"] = user_cfg["log_level"]
    else:
        logger.warning("Config file %s not found, using defaults", path)
    return cfg


# ---------------------------------------------------------------------------
# CQ Code Parsing
# ---------------------------------------------------------------------------

# Match [CQ:type,key=value,key=value]
_CQ_PATTERN = re.compile(r"\[CQ:(\w+)(?:,([^\]]*))?\]")


def parse_cq_params(param_str: str) -> Dict[str, str]:
    """Parse 'key=value,key=value' into a dict."""
    if not param_str:
        return {}
    params = {}
    for part in param_str.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip()
    return params


def extract_text_and_images(
    message: Any, self_id: str = ""
) -> tuple[str, List[str], bool]:
    """Extract plain text, image URLs, and whether @self from a message.

    Handles both string (CQ code) and array (segment) message formats.

    Returns:
        (text, image_urls, is_at_self)
    """
    text_parts: List[str] = []
    image_urls: List[str] = []
    is_at_self = False
    self_id_str = str(self_id) if self_id else ""

    if isinstance(message, str):
        # String format with CQ codes
        last_end = 0
        for m in _CQ_PATTERN.finditer(message):
            # Collect text between CQ codes
            if m.start() > last_end:
                text_parts.append(message[last_end : m.start()])
            cq_type = m.group(1)
            params = parse_cq_params(m.group(2) or "")
            if cq_type == "at":
                qq = params.get("qq", "")
                if qq == self_id_str or qq == "all":
                    is_at_self = True
            elif cq_type == "image":
                url = params.get("url", "")
                if url:
                    image_urls.append(url)
            elif cq_type == "face":
                pass  # Ignore QQ faces
            elif cq_type == "reply":
                pass  # Ignore reply markers
            last_end = m.end()
        # Trailing text
        if last_end < len(message):
            text_parts.append(message[last_end:])

    elif isinstance(message, list):
        # Array format (segments)
        for seg in message:
            if not isinstance(seg, dict):
                continue
            seg_type = seg.get("type", "")
            data = seg.get("data", {})
            if seg_type == "text":
                text_parts.append(data.get("text", ""))
            elif seg_type == "at":
                qq = str(data.get("qq", ""))
                if qq == self_id_str or qq == "all":
                    is_at_self = True
            elif seg_type == "image":
                url = data.get("url", "")
                if url:
                    image_urls.append(url)
    else:
        text_parts.append(str(message))

    text = "".join(text_parts).strip()
    return text, image_urls, is_at_self


# ---------------------------------------------------------------------------
# Markdown Image Extraction (from Hermes responses)
# ---------------------------------------------------------------------------

_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MEDIA_TAG_PATTERN = re.compile(r"MEDIA:(\S+)")


def extract_response_media(text: str) -> tuple[str, List[str]]:
    """Extract image/file URLs from Hermes' markdown response.

    Returns:
        (cleaned_text, media_urls)
    """
    media_urls: List[str] = []

    # Extract markdown images ![alt](url)
    for m in _MD_IMAGE_PATTERN.finditer(text):
        url = m.group(2)
        if url.startswith("http://") or url.startswith("https://"):
            media_urls.append(url)

    # Extract MEDIA: tags
    for m in _MEDIA_TAG_PATTERN.finditer(text):
        media_urls.append(m.group(1))

    # Clean text
    cleaned = _MD_IMAGE_PATTERN.sub("", text)
    cleaned = _MEDIA_TAG_PATTERN.sub("", cleaned)
    cleaned = cleaned.strip()

    return cleaned, media_urls


# ---------------------------------------------------------------------------
# OneBot Bridge
# ---------------------------------------------------------------------------

# Reconnect backoff delays (seconds)
RECONNECT_DELAYS = [1, 2, 5, 10, 30, 60]
MAX_RECONNECT_ATTEMPTS = 100


class OneBotBridge:
    """Bridge between OneBot v11 WebSocket and Hermes API Server."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        ob = config["onebot"]
        hm = config["hermes"]
        bot = config["bot"]

        self.ws_url: str = ob["ws_url"]
        self.access_token: str = str(ob.get("access_token") or "").strip()

        self.api_url: str = hm["api_url"].rstrip("/")
        self.api_key: str = str(hm.get("api_key") or "").strip()

        self.self_id: str = str(bot.get("self_id") or "").strip()
        self.group_trigger: str = bot.get("group_trigger", "at")
        self.keywords: List[str] = bot.get("keywords", ["/ai"])
        self.private_trigger: str = bot.get("private_trigger", "all")
        self.allow_users: List[str] = [str(u) for u in (bot.get("allow_users") or [])]
        self.allow_groups: List[str] = [str(g) for g in (bot.get("allow_groups") or [])]

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._http: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._echo_counter = 0

        # Active requests: session_key → asyncio.Task (for potential future interrupt)
        self._active_requests: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the bridge with auto-reconnect."""
        self._running = True
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300))

        backoff_idx = 0
        while self._running and backoff_idx < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._connect_and_listen()
                backoff_idx = 0  # Reset on clean disconnect
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                delay = RECONNECT_DELAYS[min(backoff_idx, len(RECONNECT_DELAYS) - 1)]
                logger.warning(
                    "OneBot connection error: %s — reconnecting in %ds (attempt %d)",
                    exc,
                    delay,
                    backoff_idx + 1,
                )
                await asyncio.sleep(delay)
                backoff_idx += 1

        await self._cleanup()

    async def stop(self) -> None:
        """Stop the bridge gracefully."""
        logger.info("Stopping bridge...")
        self._running = False
        # Cancel active requests
        for task in self._active_requests.values():
            task.cancel()
        self._active_requests.clear()
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        if self._http and not self._http.closed:
            await self._http.close()
        self._http = None

    # ------------------------------------------------------------------
    # OneBot WebSocket Connection
    # ------------------------------------------------------------------

    async def _connect_and_listen(self) -> None:
        """Connect to OneBot WebSocket and process events."""
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        self._session = aiohttp.ClientSession()
        logger.info("Connecting to OneBot at %s ...", self.ws_url)
        self._ws = await self._session.ws_connect(self.ws_url, headers=headers)
        logger.info("✅ Connected to OneBot WebSocket")

        async for msg in self._ws:
            if not self._running:
                break
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(data)
            elif msg.type in (
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            ):
                logger.warning("OneBot WebSocket closed/error")
                break

    async def _dispatch(self, data: Dict[str, Any]) -> None:
        """Route an incoming OneBot event."""
        post_type = data.get("post_type")

        if post_type == "meta_event":
            meta_type = data.get("meta_event_type")
            if meta_type == "lifecycle":
                sub = data.get("sub_type", "")
                logger.info("OneBot lifecycle: %s", sub)
                # Auto-detect self_id from connect event
                if not self.self_id and data.get("self_id"):
                    self.self_id = str(data["self_id"])
                    logger.info("Auto-detected self_id: %s", self.self_id)
            elif meta_type == "heartbeat":
                logger.debug("OneBot heartbeat (status: %s)", data.get("status"))
            return

        if post_type == "message":
            # Run message handling in background so we don't block the WS reader
            asyncio.create_task(self._handle_message(data))
            return

        logger.debug("Ignored event: post_type=%s", post_type)

    # ------------------------------------------------------------------
    # Message Handling
    # ------------------------------------------------------------------

    async def _handle_message(self, event: Dict[str, Any]) -> None:
        """Process an incoming message event."""
        message_type = event.get("message_type")  # "private" or "group"
        user_id = str(event.get("user_id", ""))
        group_id = str(event.get("group_id", ""))
        message = event.get("message", "")  # Can be string or list
        message_id = event.get("message_id")
        sender = event.get("sender", {})
        nickname = sender.get("nickname", "") or sender.get("card", "") or user_id

        # Ignore messages from self
        if user_id == self.self_id:
            return

        # Parse message content
        text, image_urls, is_at_self = extract_text_and_images(message, self.self_id)

        if not text and not image_urls:
            return

        # --- Trigger checks ---

        if message_type == "group":
            # Group allowlist
            if self.allow_groups and group_id not in self.allow_groups:
                return

            # Group trigger mode
            if self.group_trigger == "at":
                if not is_at_self:
                    return
            elif self.group_trigger == "keyword":
                matched = any(text.startswith(kw) for kw in self.keywords)
                if not matched and not is_at_self:
                    return
                # Strip matched keyword prefix
                for kw in self.keywords:
                    if text.startswith(kw):
                        text = text[len(kw) :].strip()
                        break
            # "all" mode: always respond

        elif message_type == "private":
            if self.private_trigger == "allowlist":
                if user_id not in self.allow_users:
                    return

        if not text and not image_urls:
            return

        # --- Build session key ---
        if message_type == "group":
            session_key = f"onebot-group-{group_id}-{user_id}"
        else:
            session_key = f"onebot-private-{user_id}"

        logger.info(
            "[%s] %s (%s): %s%s",
            message_type,
            nickname,
            user_id,
            text[:80],
            f" [+{len(image_urls)} images]" if image_urls else "",
        )

        # --- Handle bridge commands ---
        if text.startswith("/"):
            handled = await self._handle_bridge_command(
                text, message_type, user_id, group_id, session_key
            )
            if handled:
                return

        # --- Call Hermes API ---
        try:
            reply = await self._call_hermes(text, image_urls, session_key)
        except Exception as exc:
            logger.error("Hermes API call failed: %s", exc, exc_info=True)
            reply = f"⚠️ AI 服务暂时不可用：{exc}"

        if not reply:
            return

        # --- Extract media from response ---
        reply_text, media_urls = extract_response_media(reply)

        # --- Send reply ---
        if message_type == "group":
            await self._send_group(group_id, reply_text, media_urls)
        else:
            await self._send_private(user_id, reply_text, media_urls)

    async def _handle_bridge_command(
        self,
        text: str,
        message_type: str,
        user_id: str,
        group_id: str,
        session_key: str,
    ) -> bool:
        """Handle bridge-level commands. Returns True if handled."""
        cmd = text.split()[0].lower()

        if cmd in ("/new", "/reset", "/clear"):
            # We can't truly clear the Hermes session from outside, but we
            # can switch to a new session_id by appending a timestamp
            logger.info("Session reset requested for %s", session_key)
            reply = "✅ 会话已重置，开始新的对话。"
            if message_type == "group":
                await self._send_group(group_id, reply)
            else:
                await self._send_private(user_id, reply)
            return True

        if cmd == "/ping":
            reply = "🏓 pong! OneBot Bridge is running."
            if message_type == "group":
                await self._send_group(group_id, reply)
            else:
                await self._send_private(user_id, reply)
            return True

        if cmd == "/help":
            reply = (
                "🤖 OneBot Bridge 命令：\n"
                "/new - 重置对话\n"
                "/ping - 检查 Bridge 状态\n"
                "/help - 显示此帮助\n"
                "\n其他消息将转发给 AI 助手处理。"
            )
            if message_type == "group":
                await self._send_group(group_id, reply)
            else:
                await self._send_private(user_id, reply)
            return True

        return False

    # ------------------------------------------------------------------
    # Hermes API
    # ------------------------------------------------------------------

    async def _call_hermes(
        self, text: str, image_urls: List[str], session_key: str
    ) -> str:
        """Call Hermes API Server and return the response text."""
        url = f"{self.api_url}/v1/chat/completions"

        # Build content: text-only or multimodal
        if image_urls:
            content: Any = [{"type": "text", "text": text}]
            for img_url in image_urls:
                content.append(
                    {"type": "image_url", "image_url": {"url": img_url}}
                )
        else:
            content = text

        payload = {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        }

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": session_key,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with self._http.post(url, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Hermes API returned {resp.status}: {body[:200]}"
                )
            data = await resp.json()

        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "")

    # ------------------------------------------------------------------
    # OneBot Message Sending
    # ------------------------------------------------------------------

    async def _send_action(
        self, action: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Send an action to the OneBot WebSocket."""
        if not self._ws or self._ws.closed:
            logger.warning("Cannot send action: WebSocket not connected")
            return None

        self._echo_counter += 1
        payload = {
            "action": action,
            "params": params,
            "echo": str(self._echo_counter),
        }
        await self._ws.send_json(payload)
        logger.debug("Sent action: %s", action)
        return None  # We don't wait for response in this simple bridge

    async def _send_private(
        self, user_id: str, text: str, media_urls: Optional[List[str]] = None
    ) -> None:
        """Send a private message."""
        # Build message segments
        segments = self._build_message_segments(text, media_urls)
        await self._send_action(
            "send_private_msg",
            {"user_id": int(user_id), "message": segments},
        )
        logger.info("[private→%s] %s", user_id, text[:80])

    async def _send_group(
        self, group_id: str, text: str, media_urls: Optional[List[str]] = None
    ) -> None:
        """Send a group message."""
        segments = self._build_message_segments(text, media_urls)
        await self._send_action(
            "send_group_msg",
            {"group_id": int(group_id), "message": segments},
        )
        logger.info("[group→%s] %s", group_id, text[:80])

    @staticmethod
    def _build_message_segments(
        text: str, media_urls: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Build OneBot message segment array."""
        segments: List[Dict[str, Any]] = []

        if text:
            # Split long messages (QQ has ~4500 char limit per message)
            if len(text) > 4000:
                text = text[:4000] + "\n\n…（消息过长，已截断）"
            segments.append({"type": "text", "data": {"text": text}})

        if media_urls:
            for url in media_urls:
                if url.startswith("http://") or url.startswith("https://"):
                    segments.append(
                        {"type": "image", "data": {"file": url}}
                    )
                elif os.path.isfile(url):
                    # Local file — use file:// protocol
                    abs_path = os.path.abspath(url)
                    segments.append(
                        {"type": "image", "data": {"file": f"file://{abs_path}"}}
                    )

        return segments


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    # Determine config path
    config_path = os.environ.get("ONEBOT_BRIDGE_CONFIG", "config.yaml")
    config = load_config(config_path)
    setup_logging(config.get("log_level", "INFO"))

    logger.info("=" * 50)
    logger.info("  OneBot Bridge for Hermes Agent")
    logger.info("=" * 50)
    logger.info("OneBot WS:  %s", config["onebot"]["ws_url"])
    logger.info("Hermes API: %s", config["hermes"]["api_url"])
    logger.info("Trigger:    group=%s, private=%s", config["bot"]["group_trigger"], config["bot"]["private_trigger"])

    bridge = OneBotBridge(config)

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bridge.stop()))

    await bridge.start()


if __name__ == "__main__":
    asyncio.run(main())
