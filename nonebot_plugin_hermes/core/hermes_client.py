"""
Hermes API Server HTTP 客户端

通过 /v1/chat/completions 与 Hermes Agent 通信。
M1-mem 路径 B(P0-spike 决策):tools/tool_choice 被 Hermes 吞掉,改用 system prompt 强约束 + JSON5 容错解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
import json5  # type: ignore[import-untyped]
from nonebot import logger

from ..config import plugin_config

# user_content_override 期望形态:纯文本 或 OpenAI 多模态 parts 列表
UserContent = Union[str, List[Dict[str, Any]]]

_MD_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MEDIA_TAG_PATTERN = re.compile(r"MEDIA:(\S+)")

# 提取首个 {...} 块。
# 当前正则只支持嵌套一层(`\{[^{}]*\}` 出现在外层 `\{...\}` 中)。
# M1 submit_decision schema 全平,够用。如未来 schema 加 nested object,
# 需改用真正的平衡解析器(parser combinator 或 json5 边读边定位)。
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


def maybe_extract_decision_reply_text(text: str) -> Optional[str]:
    """passive 路径的防御:如果 raw_text 是 submit_decision 形 JSON,抠出 reply_text。

    场景:同一 Hermes session 之前跑过 reactive 模式,LLM 上下文学到了
    submit_decision 契约;之后切回 passive(active_session 关掉)时,session
    依旧吐 JSON,导致整段 JSON 被当作回复发给用户。

    返回值:
      - 字符串:JSON 是 submit_decision 形且 should_reply=true,返回 reply_text
      - 空串 "":JSON 是 submit_decision 形但 should_reply=false(显式静默)
      - None:不是 submit_decision 形,调用方应继续用原始 raw_text
    """
    parsed = _try_parse_first_json_block(text)
    if parsed is None or "should_reply" not in parsed:
        return None
    if not parsed.get("should_reply"):
        return ""
    rt = parsed.get("reply_text")
    if isinstance(rt, str):
        return rt
    return None


@dataclass
class ChatResult:
    raw_text: str
    structured: Optional[Dict[str, Any]] = None
    media_urls: List[str] = field(default_factory=list)
    parse_failed: bool = False
    """期望结构化输出但解析失败(JSON 提取不到 / json5 解析报错 / 非 dict 类型)。"""

    is_transport_error: bool = False
    """HTTP 失败(非 200 / timeout / connect error / 其他异常)。

    handler 据此决定:transport_error → 可重试或对用户报错;parse_failed →
    通常静默降级(模型回了不可解析的内容);两者**不互斥**(transport_error
    场景下 parse_failed 也设 True 以阻止 caller 误把 raw_text 当模型有效输出)。
    """


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
        user_content_override: Optional[UserContent] = None,
    ) -> ChatResult:
        """调用 Hermes,返回 ChatResult。

        - mode='passive': 普通文本回复(不强制结构化)
        - mode='reactive' + expect_structured=True + structured_tool_name='submit_decision':
          system prompt 追加 STRUCTURED OUTPUT 段,期望模型回复纯 JSON;解析失败 parse_failed=True
        - system_prompt: 由 prompt_builder 注入;None 走默认 Message Context 拼装。
          **注意**:外部传入 system_prompt 时,Platform/User/Group 上下文须由调用方
          自行包含,本方法不会再额外补。
        - user_content_override: 由 prompt_builder 直接给出 user message 的 content
          (str 或 OpenAI 多模态 parts 列表;text + image_urls 参数将被忽略)
        - mode 字段当前为路由元数据,chat() 内部不分支判断;Task 15 handler 据此决定
          如何呈现结果(reactive 走 structured 流,passive 走 raw_text)。
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
                    return ChatResult(
                        raw_text=f"⚠️ AI 服务返回错误 ({resp.status_code})",
                        parse_failed=True,
                        is_transport_error=True,
                    )
                data = resp.json()
        except httpx.TimeoutException:
            logger.error(f"[HERMES] API 请求超时 ({self.timeout}s)")
            return ChatResult(
                raw_text="⚠️ AI 服务响应超时,请稍后重试",
                parse_failed=True,
                is_transport_error=True,
            )
        except httpx.ConnectError:
            logger.error(f"[HERMES] 无法连接到 {self.api_url}")
            return ChatResult(
                raw_text="⚠️ 无法连接到 AI 服务",
                parse_failed=True,
                is_transport_error=True,
            )
        except Exception as exc:
            logger.error(f"[HERMES] API 请求异常: {exc}")
            return ChatResult(
                raw_text=f"⚠️ AI 服务异常: {exc}",
                parse_failed=True,
                is_transport_error=True,
            )

        choices = data.get("choices") or []
        if not choices:
            # 期望结构化但响应空:这是结构性失败而非"模型选择不回复"
            return ChatResult(raw_text="", parse_failed=expect_structured)

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
