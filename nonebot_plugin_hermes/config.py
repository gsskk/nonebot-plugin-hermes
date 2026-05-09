"""
配置模型

所有配置项通过 NoneBot 的 .env 文件读取，前缀为 HERMES_。
"""

from typing import Literal, Set

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    # --- Hermes API Server ---
    hermes_api_url: str = "http://127.0.0.1:8642"
    """Hermes API Server 地址"""

    hermes_api_key: str = ""
    """Hermes API Server 密钥(对应 api_server.extra.key)"""

    hermes_api_timeout: int = 300
    """API 请求超时时间(秒),Agent 执行可能较慢"""

    # --- 触发模式 ---
    hermes_group_trigger: str = "at"
    """群聊触发方式: at / all / keyword"""

    hermes_keywords: Set[str] = {"/ai"}
    """keyword 模式下的触发关键词"""

    hermes_private_trigger: str = "all"
    """私聊触发方式: all / allowlist"""

    hermes_allow_users: Set[str] = set()
    """允许私聊的用户 ID(allowlist 模式)"""

    hermes_allow_groups: Set[str] = set()
    """允许响应的群组 ID(空 = 全部允许)"""

    # --- 会话 ---
    hermes_session_share_group: bool = False
    """群内是否共享同一个 session(False = 每人独立)"""

    # --- 消息 ---
    hermes_max_length: int = 4000
    """单条回复最大长度(超出截断,QQ 限制约 4500 字符)"""

    hermes_ignore_prefix: Set[str] = {"."}
    """以这些字符开头的消息不触发回复"""

    # --- 被动感知 (Chat Awareness) ---
    hermes_perception_enabled: bool = False
    """是否开启被动感知(监听但不回复非触发消息,为下次对话提供背景)"""

    hermes_perception_buffer: int = 10
    """被动感知缓存的历史消息数量"""

    hermes_perception_text_length: int = 200
    """被动感知单条历史消息最大长度(超出截断)"""

    hermes_perception_image_mode: str = "placeholder"
    """历史记录中的图片处理模式:
    - placeholder: 历史里图只用 [图片] 占位 + URL 引用,多模态 content 只发当前图 (默认)
    - inline_labeled: 历史最后一张图带 <<HISTORICAL IMAGES>> 标签放入多模态 content,与当前图清晰分隔
    - none: 完全不提历史图
    旧值 'last' 视为 'inline_labeled' 别名 (已废弃,启动时 WARN)
    """

    # --- M1: 内存缓冲 ---
    hermes_buffer_per_group_cap: int = 200
    """每群在 MessageBuffer 中保留多少条最近消息(LRU 之外的硬上限)"""

    hermes_buffer_total_groups_cap: int = 50
    """MessageBuffer 跨群总容量,超出按 LRU 驱逐"""

    # --- M1: 活跃态 ---
    hermes_active_session_enabled: bool = False
    """是否开启 @ 触发的群活跃态(False 退化为 v0.1.6 等价行为)"""

    hermes_active_session_ttl_sec: int = 300
    """活跃态默认 TTL(秒),滑动续期"""

    hermes_active_sweep_interval_sec: int = 30
    """expire_active_sessions cron 频率(秒)"""

    # --- M1: 反向 MCP 通道 ---
    hermes_mcp_enabled: bool = False
    """是否启动内嵌 FastMCP server(False 时 Hermes 反向调用全失败,出向不影响)"""

    hermes_mcp_host: str = "127.0.0.1"
    """MCP server bind host. 默认 loopback (127.0.0.1)。
    改监听公网/局域网在技术上可行,但安全代价:push_message 能让 bot 往群里发
    任意内容,前端防御只有 Bearer token(明文 HTTP,且与 HERMES_API_KEY 同
    钥匙)。要改请配套反向代理 + TLS + 来源 IP ACL。"""

    hermes_mcp_port: int = 8643
    """MCP server bind port"""

    hermes_mcp_recent_limit_max: int = Field(default=50, ge=1)
    """get_recent_messages 工具单次返回上限。最小 1——0/负值会让工具静默返空,
    Pydantic 在启动期校验防 misconfig。"""

    # --- M1: 结构化输出路径(由 P0-spike 决定) ---
    hermes_structured_path: Literal["tools", "prompt"] = "prompt"
    """tools = 路径 A(tools+tool_choice);prompt = 路径 B(JSON5)。
    Task 3 spike (2026-05-09) 结论:Hermes 不透传 tools/tool_choice 给底层 LLM,
    必须用 prompt 强约束 + JSON5 容错解析。"""


plugin_config = get_plugin_config(Config)
