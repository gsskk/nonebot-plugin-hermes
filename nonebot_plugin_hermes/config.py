"""
配置模型

所有配置项通过 NoneBot 的 .env 文件读取，前缀为 HERMES_。
"""

from typing import Set

from nonebot import get_plugin_config
from pydantic import BaseModel


class Config(BaseModel):
    # --- Hermes API Server ---
    hermes_api_url: str = "http://127.0.0.1:8642"
    hermes_api_key: str = ""
    hermes_api_timeout: int = 300

    # --- 触发模式 ---
    hermes_group_trigger: str = "at"
    hermes_keywords: Set[str] = {"/ai"}
    hermes_private_trigger: str = "all"
    hermes_allow_users: Set[str] = set()
    hermes_allow_groups: Set[str] = set()

    # --- 会话 ---
    hermes_session_share_group: bool = False

    # --- 消息 ---
    hermes_max_length: int = 4000
    hermes_ignore_prefix: Set[str] = {"."}

    # --- 被动感知 (Chat Awareness) ---
    hermes_perception_enabled: bool = False
    hermes_perception_buffer: int = 10
    hermes_perception_text_length: int = 200
    hermes_perception_image_mode: str = "placeholder"

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
    """MCP server bind host,**绝不暴露到非 loopback**"""

    hermes_mcp_port: int = 8643
    """MCP server bind port"""

    hermes_mcp_recent_limit_max: int = 50
    """get_recent_messages 工具单次返回上限"""

    # --- M1: 结构化输出路径(由 P0-spike 决定) ---
    hermes_structured_path: str = "tools"
    """tools = 路径 A(tools+tool_choice);prompt = 路径 B(JSON5)"""


plugin_config = get_plugin_config(Config)
