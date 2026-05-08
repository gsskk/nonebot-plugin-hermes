"""
Hermes API Server HTTP 客户端

通过 /v1/chat/completions 与 Hermes Agent 通信。
M1-mem 路径 B(P0-spike 决策):tools/tool_choice 被 Hermes 吞掉,改用 system prompt 强约束 + JSON5 容错解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

import httpx
import json5  # type: ignore[import-untyped]
from nonebot import logger

from ..config import plugin_config

_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MEDIA_TAG_PATTERN = re.compile(r"MEDIA:(\S+)")

# 提取首个 {...} 块,容忍嵌套一层(M1 决策 schema 不深)
_FIRST_JSON_BLOCK = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)

_DECISION_HINT = (
    "\n\n=== STRUCTURED OUTPUT ===\n"
    "Your reply MUST be a single JSON object with these keys:\n"
    "  should_reply (boolean, required)\n"
    "  reply_text (string, optional, required when should_reply=true)\n"
    "  topic_hint (string, optional)\n"
    "  should_exit_active (boolean, optional)\n"
    "Output ONLY the JSON object, no preamble, no postscript, no markdown fences."
)


def extract_response_media(text: str) -> Tuple[str, List[str]]:
    """从 Hermes 回复中提取 markdown 图片 / MEDIA: 标签 URL,返回 (清洗后文本, URL 列表)。"""
    media_urls: List[str] = []
    for m in _MD_IMAGE_PATTERN.finditer(text):
        url = m.group(2)
        if url.startswith(("http://", "https://")):
            media_urls.append(url)
    for m in _MEDIA_TAG_PATTERN.finditer(text):
        media_urls.append(m.group(1))
    cleaned = _MD_IMAGE_PATTERN.sub("", text)
    cleaned = _MEDIA_TAG_PATTERN.sub("", cleaned)
    return cleaned.strip(), media_urls


def _try_parse_first_json_block(text: str) -> Optional[Dict[str, Any]]:
    """从模型回复中提取首个 {...} 块并 JSON5 解析。失败返回 None,调用方记 parse_failed。"""
    if not text:
        return None
    m = _FIRST_JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        parsed = json5.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


@dataclass
class ChatResult:
    raw_text: str
    structured: Optional[Dict[str, Any]] = None
    media_urls: List[str] = field(default_factory=list)
    parse_failed: bool = False


class HermesClient:
    def __init__(self) -> None:
        self._api_url_cache: Optional[str] = None
        self._api_key_cache: Optional[str] = None
        self._timeout_cache: Optional[int] = None

    @property
    def api_url(self) -> str:
        if self._api_url_cache is None:
            self._api_url_cache = plugin_config.hermes_api_url.rstrip("/")
        return self._api_url_cache

    @property
    def api_key(self) -> str:
        if self._api_key_cache is None:
            self._api_key_cache = plugin_config.hermes_api_key
        return self._api_key_cache

    @property
    def timeout(self) -> int:
        if self._timeout_cache is None:
            self._timeout_cache = plugin_config.hermes_api_timeout
        return self._timeout_cache

    def get_headers(self, session_key: str = "") -> Dict[str, str]:
        h = {"Content-Type": "application/json", "X-Hermes-Session-Id": session_key}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(
        self,
        *,
        text: str,
        image_urls: Optional[List[str]] = None,
        session_key: str,
        user_id: str,
        group_id: Optional[str],
        adapter_name: str,
        is_private: bool,
        mode: Literal["reactive", "passive"] = "passive",
        expect_structured: bool = False,
        structured_tool_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_content_override: Optional[Any] = None,
    ) -> ChatResult:
        """调用 Hermes,返回 ChatResult。

        - mode='passive': 普通文本回复(不强制结构化)
        - mode='reactive' + expect_structured=True + structured_tool_name='submit_decision':
          system prompt 追加 STRUCTURED OUTPUT 段,期望模型回复纯 JSON;解析失败 parse_failed=True
        - system_prompt: 由 prompt_builder 注入;None 走默认 Message Context 拼装
        - user_content_override: 由 prompt_builder 直接给出 user message 的 content
          (text + image_urls 参数将被忽略)
        """
        url = f"{self.api_url}/v1/chat/completions"

        if user_content_override is not None:
            content: Any = user_content_override
        else:
            cur_imgs = image_urls or []
            if not cur_imgs:
                content = text
            else:
                parts: List[Dict[str, Any]] = [{"type": "text", "text": text}]
                for u in cur_imgs:
                    parts.append({"type": "image_url", "image_url": {"url": u}})
                content = parts

        if system_prompt is None:
            ctx_lines = [f"Platform: {adapter_name or 'unknown'}"]
            ctx_lines.append("Chat Type: " + ("Private" if is_private else "Group"))
            if user_id:
                ctx_lines.append(f"User ID: {user_id}")
            if not is_private and group_id:
                ctx_lines.append(f"Group ID: {group_id}")
            system_prompt = "Message Context:\n" + "\n".join(ctx_lines)

        if expect_structured and structured_tool_name == "submit_decision":
            system_prompt = system_prompt + _DECISION_HINT

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]

        payload: Dict[str, Any] = {
            "model": "hermes-agent",
            "messages": messages,
            "stream": False,
        }
        # 路径 B:不发 tools / tool_choice(Hermes 透传不可靠,P0-spike 已验)

        headers = self.get_headers(session_key)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code != 200:
                    body = resp.text[:200]
                    logger.error(f"[HERMES] API 返回 {resp.status_code}: {body}")
                    return ChatResult(raw_text=f"⚠️ AI 服务返回错误 ({resp.status_code})", parse_failed=True)
                data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"[HERMES] API 请求超时 ({self.timeout}s)")
            return ChatResult(raw_text="⚠️ AI 服务响应超时,请稍后重试", parse_failed=True)
        except httpx.ConnectError:
            logger.error(f"[HERMES] 无法连接到 {self.api_url}")
            return ChatResult(raw_text="⚠️ 无法连接到 AI 服务", parse_failed=True)
        except Exception as exc:
            logger.error(f"[HERMES] API 请求异常: {exc}")
            return ChatResult(raw_text=f"⚠️ AI 服务异常: {exc}", parse_failed=True)

        choices = data.get("choices") or []
        if not choices:
            return ChatResult(raw_text="")

        msg = choices[0].get("message") or {}
        raw_text = msg.get("content") or ""

        # 路径 B:从 raw_text 提取首个 {...} JSON5 块
        if expect_structured and structured_tool_name == "submit_decision":
            structured = _try_parse_first_json_block(raw_text)
            if structured is None:
                logger.warning("[HERMES] 路径 B 未能从回复中解析出 JSON 块")
                return ChatResult(raw_text=raw_text, parse_failed=True)
            return ChatResult(raw_text=raw_text, structured=structured)

        # 普通文本路径(passive 或未要求结构化)
        cleaned, media_urls = extract_response_media(raw_text)
        return ChatResult(raw_text=cleaned, media_urls=media_urls)

    async def health_check(self) -> bool:
        try:
            headers = self.get_headers()
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.api_url}/v1/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False


hermes_client = HermesClient()
