"""
配置模型

所有配置项通过 NoneBot 的 .env 文件读取，前缀为 HERMES_。
"""

from typing import Set

from pydantic import BaseModel


class Config(BaseModel):
    # --- Hermes API Server ---
    hermes_api_url: str = "http://127.0.0.1:8642"
    """Hermes API Server 地址"""

    hermes_api_key: str = ""
    """Hermes API Server 密钥（对应 api_server.extra.key）"""

    hermes_api_timeout: int = 300
    """API 请求超时时间（秒），Agent 执行可能较慢"""

    # --- 触发模式 ---
    hermes_group_trigger: str = "at"
    """群聊触发方式: at / all / keyword"""

    hermes_keywords: Set[str] = {"/ai"}
    """keyword 模式下的触发关键词"""

    hermes_private_trigger: str = "all"
    """私聊触发方式: all / allowlist"""

    hermes_allow_users: Set[str] = set()
    """允许私聊的用户 ID（allowlist 模式）"""

    hermes_allow_groups: Set[str] = set()
    """允许响应的群组 ID（空 = 全部允许）"""

    # --- 会话 ---
    hermes_session_expire: int = 3600
    """会话过期时间（秒），过期后自动开始新会话"""

    hermes_session_share_group: bool = False
    """群内是否共享同一个 session（False = 每人独立）"""

    # --- 消息 ---
    hermes_max_length: int = 4000
    """单条回复最大长度（超出截断，QQ 限制约 4500 字符）"""

    hermes_ignore_prefix: Set[str] = {"."}
    """以这些字符开头的消息不触发回复"""


_plugin_config: Config | None = None


def get_config() -> Config:
    """延迟加载配置，避免循环导入"""
    global _plugin_config
    if _plugin_config is None:
        from nonebot import get_plugin_config

        _plugin_config = get_plugin_config(Config)
    return _plugin_config


# 兼容旧的直接引用方式
class _LazyConfig:
    """延迟代理，使 plugin_config.xxx 的写法仍然生效"""

    def __getattr__(self, name: str):
        return getattr(get_config(), name)


plugin_config: Config = _LazyConfig()  # type: ignore[assignment]
