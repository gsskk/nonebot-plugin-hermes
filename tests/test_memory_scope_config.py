"""长期记忆作用域配置项默认值——老用户升级后行为零变化。"""

from __future__ import annotations


def test_honcho_disabled_by_default():
    from nonebot_plugin_hermes.config import plugin_config

    assert plugin_config.hermes_honcho_enabled is False


def test_group_sessions_per_user_defaults_false():
    """默认群级共享:一个群一份记忆,群成员共用——这是 issue #2 要的隔离粒度。"""
    from nonebot_plugin_hermes.config import plugin_config

    assert plugin_config.hermes_group_sessions_per_user is False


def test_key_format_defaults_align_with_hermes_native():
    """默认模板对齐 Hermes 原生 build_session_key 4-level 格式 + nonebot- 前缀防撞。"""
    from nonebot_plugin_hermes.config import plugin_config

    assert plugin_config.hermes_group_session_key_format == "agent:main:nonebot-{adapter}:group:{group_id}"
    assert (
        plugin_config.hermes_group_per_user_session_key_format
        == "agent:main:nonebot-{adapter}:group:{group_id}:{user_id}"
    )
    assert plugin_config.hermes_private_session_key_format == "agent:main:nonebot-{adapter}:dm:{user_id}"
