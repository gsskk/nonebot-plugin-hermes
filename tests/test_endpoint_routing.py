"""按群路由到不同 Hermes 接入点。"""

from __future__ import annotations


def test_group_endpoints_empty_by_default():
    from nonebot_plugin_hermes.config import plugin_config

    assert plugin_config.hermes_group_endpoints == {}


def test_endpoint_model_defaults_are_inheritable_sentinels():
    """key/timeout 省略即回落到全局配置,所以默认值必须是可判空的哨兵。"""
    from nonebot_plugin_hermes.config import HermesEndpoint

    ep = HermesEndpoint(url="http://127.0.0.1:8642/p/groupa")
    assert ep.url == "http://127.0.0.1:8642/p/groupa"
    assert ep.key == ""
    assert ep.timeout == 0


def test_endpoint_model_accepts_full_form():
    from nonebot_plugin_hermes.config import HermesEndpoint

    ep = HermesEndpoint(url="http://127.0.0.1:8643", key="k2", timeout=120)
    assert (ep.url, ep.key, ep.timeout) == ("http://127.0.0.1:8643", "k2", 120)
