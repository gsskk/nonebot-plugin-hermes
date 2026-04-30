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
        self._api_url = plugin_config.hermes_api_url.rstrip("/")
        self._api_key = plugin_config.hermes_api_key
        self._timeout = plugin_config.hermes_api_timeout

    async def chat(
        self,
        text: str,
        image_urls: Optional[List[str]] = None,
        session_key: str = "",
    ) -> Tuple[str, List[str]]:
        """调用 Hermes API，返回 (回复文本, 媒体URL列表)。

        Args:
            text: 用户消息文本
            image_urls: 图片 URL 列表（多模态）
            session_key: 会话标识（通过 X-Hermes-Session-Id 头传递）

        Returns:
            (reply_text, media_urls)
        """
        url = f"{self._api_url}/v1/chat/completions"

        # 构建消息内容：纯文本或多模态
        content: Any
        if image_urls:
            content = [{"type": "text", "text": text}]
            for img_url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": img_url}})
        else:
            content = text

        payload: Dict[str, Any] = {
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": content}],
            "stream": False,
        }

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": session_key,
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code != 200:
                    body = resp.text[:200]
                    logger.error(f"[HERMES] API 返回 {resp.status_code}: {body}")
                    return f"⚠️ AI 服务返回错误 ({resp.status_code})", []

                data = resp.json()

        except httpx.TimeoutException:
            logger.error(f"[HERMES] API 请求超时 ({self._timeout}s)")
            return "⚠️ AI 服务响应超时，请稍后重试", []
        except httpx.ConnectError:
            logger.error(f"[HERMES] 无法连接到 {self._api_url}")
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
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._api_url}/v1/models", headers=headers)
                return resp.status_code == 200
        except Exception:
            return False


# 全局客户端实例
hermes_client = HermesClient()
