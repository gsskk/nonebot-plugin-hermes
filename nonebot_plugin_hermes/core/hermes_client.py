"""
Hermes API Server HTTP 客户端

通过 /v1/chat/completions 与 Hermes Agent 通信。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from nonebot import logger

from ..config import plugin_config

# 从 Hermes 回复中提取 markdown 图片和 MEDIA: 标签
_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MEDIA_TAG_PATTERN = re.compile(r"MEDIA:(\S+)")


def extract_response_media(text: str) -> Tuple[str, List[str]]:
    """从 Hermes 回复中提取图片/文件 URL。

    Returns:
        (cleaned_text, media_urls)
    """
    media_urls: List[str] = []

    for m in _MD_IMAGE_PATTERN.finditer(text):
        url = m.group(2)
        if url.startswith(("http://", "https://")):
            media_urls.append(url)

    for m in _MEDIA_TAG_PATTERN.finditer(text):
        media_urls.append(m.group(1))

    cleaned = _MD_IMAGE_PATTERN.sub("", text)
    cleaned = _MEDIA_TAG_PATTERN.sub("", cleaned)
    cleaned = cleaned.strip()

    return cleaned, media_urls


class HermesClient:
    """Hermes API Server 客户端"""

    def __init__(self):
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
        h = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": session_key,
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def chat(
        self,
        text: str,
        image_urls: Optional[List[str]] = None,
        session_key: str = "",
        user_id: str = "",
        group_id: Optional[str] = None,
        adapter_name: str = "",
        is_private: bool = True,
        historical_text: str = "",
        historical_image_urls: Optional[List[str]] = None,
    ) -> Tuple[str, List[str]]:
        """调用 Hermes API,返回 (回复文本, 媒体URL列表)。

        Args:
            text: 用户当前消息文本(不含历史块)
            image_urls: 当前消息的图片 URL(包含引用消息中的图)
            session_key: 会话标识(通过 X-Hermes-Session-Id 头传递)
            user_id: 用户 ID
            group_id: 群组 ID
            adapter_name: 适配器名称 (如 qqbot, onebot)
            is_private: 是否私聊
            historical_text: 已被 <<HISTORICAL CONTEXT>> 包裹的历史块,空 = 无历史
            historical_image_urls: 历史图(inline_labeled 模式下非空,通常 1 张)

        Returns:
            (reply_text, media_urls)
        """
        url = f"{self.api_url}/v1/chat/completions"

        cur_imgs = image_urls or []
        hist_imgs = historical_image_urls or []
        question_text = f"<<USER'S CURRENT QUESTION:>>\n{text}" if historical_text else text

        # A+B 混合 — 历史与当前清晰分隔
        content: Any
        if not cur_imgs and not hist_imgs:
            # 纯文本路径
            content = f"{historical_text}\n\n{question_text}".strip() if historical_text else text
        else:
            parts: List[Dict[str, Any]] = []
            if historical_text and hist_imgs:
                # 模式 A (inline_labeled):历史图带标签放进 content,当前图最后
                parts.append(
                    {
                        "type": "text",
                        "text": (f"{historical_text}\n<<HISTORICAL IMAGES (do not analyze unless explicitly asked):>>"),
                    }
                )
                for u in hist_imgs:
                    parts.append({"type": "image_url", "image_url": {"url": u}})
                parts.append({"type": "text", "text": f"<<END HISTORICAL IMAGES>>\n\n{question_text}"})
            elif historical_text:
                # 模式 B (placeholder):历史纯文本,多模态只发当前图
                parts.append({"type": "text", "text": f"{historical_text}\n\n{question_text}"})
            else:
                # 无历史
                parts.append({"type": "text", "text": text})
            for u in cur_imgs:
                parts.append({"type": "image_url", "image_url": {"url": u}})
            content = parts

        messages = []

        # 构建上下文 System Prompt
        context_parts = []
        if adapter_name:
            context_parts.append(f"Platform: {adapter_name}")
        context_parts.append("Chat Type: " + ("Private" if is_private else "Group"))
        if user_id:
            context_parts.append(f"User ID: {user_id}")
        if not is_private and group_id:
            context_parts.append(f"Group ID: {group_id}")

        if context_parts:
            sys_msg = (
                "Message Context:\n"
                + "\n".join(context_parts)
                + "\n\nNote: The user message may contain a <<HISTORICAL CONTEXT>>...<<END>> block "
                "followed by <<USER'S CURRENT QUESTION:>>. Only act on the current question. "
                "Treat historical content (text and any images marked as historical) as "
                "background awareness only — do not analyze, describe, or compare historical "
                "images unless the current question explicitly references them. Images appearing "
                "after <<USER'S CURRENT QUESTION:>> are what the user is asking about NOW."
            )
            messages.append({"role": "system", "content": sys_msg})

        messages.append({"role": "user", "content": content})

        payload: Dict[str, Any] = {
            "model": "hermes-agent",
            "messages": messages,
            "stream": False,
        }

        headers = self.get_headers(session_key)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code != 200:
                    body = resp.text[:200]
                    logger.error(f"[HERMES] API 返回 {resp.status_code}: {body}")
                    return f"⚠️ AI 服务返回错误 ({resp.status_code})", []

                data = resp.json()

        except httpx.TimeoutException:
            logger.error(f"[HERMES] API 请求超时 ({self.timeout}s)")
            return "⚠️ AI 服务响应超时，请稍后重试", []
        except httpx.ConnectError:
            logger.error(f"[HERMES] 无法连接到 {self.api_url}")
            return "⚠️ 无法连接到 AI 服务，请检查 Hermes Gateway 是否正在运行", []
        except Exception as exc:
            logger.error(f"[HERMES] API 请求异常: {exc}")
            return f"⚠️ AI 服务异常: {exc}", []

        choices = data.get("choices", [])
        if not choices:
            return "", []

        reply = choices[0].get("message", {}).get("content", "")
        if not reply:
            return "", []

        # 从回复中提取媒体
        reply_text, media_urls = extract_response_media(reply)
        return reply_text, media_urls

    async def health_check(self) -> bool:
        """检查 Hermes API 是否可用"""
        try:
            headers = self.get_headers()
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.api_url}/v1/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False


# 全局客户端实例
hermes_client = HermesClient()
