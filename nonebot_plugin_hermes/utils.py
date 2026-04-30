import nonebot_plugin_alconna as alconna
from nonebot.adapters import Event

from .config import plugin_config


def get_adapter_name(target: alconna.Target) -> str:
    """从 Target 中提取适配器名称"""
    adapter = getattr(target, "adapter", "") or ""
    return adapter.lower().replace(" ", "").replace(".", "") or "unknown"


def check_isolation(event: Event, target: alconna.Target) -> bool:
    """
    检查当前消息是否在隔离白名单中。
    如果未通过白名单检查，返回 False。
    """
    user_id = event.get_user_id() or "user"

    if target.private:
        # 私聊触发检查
        if plugin_config.hermes_private_trigger == "allowlist":
            if user_id not in plugin_config.hermes_allow_users:
                return False
    else:
        # 群聊触发检查
        group_id = target.id
        if plugin_config.hermes_allow_groups and group_id not in plugin_config.hermes_allow_groups:
            return False

    return True
