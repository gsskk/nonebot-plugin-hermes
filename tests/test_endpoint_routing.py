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


def _set_table(monkeypatch, table: dict):
    from nonebot_plugin_hermes.config import HermesEndpoint, plugin_config

    parsed = {k: HermesEndpoint(**v) for k, v in table.items()}
    monkeypatch.setattr(plugin_config, "hermes_group_endpoints", parsed)
    return plugin_config


def test_resolve_target_falls_back_to_default(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import resolve_target

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642/")
    monkeypatch.setattr(plugin_config, "hermes_api_key", "sk-global")
    monkeypatch.setattr(plugin_config, "hermes_api_timeout", 300)
    _set_table(monkeypatch, {})

    tgt = resolve_target("ob11", False, "g1")
    assert tgt.base_url == "http://127.0.0.1:8642", "尾斜杠必须去掉,拼接时才不会出现 //v1"
    assert tgt.api_key == "sk-global"
    assert tgt.timeout == 300
    assert tgt.label == "default"


def test_resolve_target_matches_adapter_and_group(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import resolve_target

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    monkeypatch.setattr(plugin_config, "hermes_api_key", "sk-global")
    monkeypatch.setattr(plugin_config, "hermes_api_timeout", 300)
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8642/p/teamA/", "key": "sk-a", "timeout": 120}})

    hit = resolve_target("ob11", False, "g1")
    assert hit.base_url == "http://127.0.0.1:8642/p/teamA"
    assert hit.api_key == "sk-a"
    assert hit.timeout == 120
    assert hit.label == "ob11:g1"

    # 同群号不同 adapter 不能命中
    assert resolve_target("telegram", False, "g1").label == "default"
    # 未列出的群回落
    assert resolve_target("ob11", False, "g2").label == "default"


def test_resolve_target_private_always_default(monkeypatch):
    """私聊不参与按群路由——路由键的语义就是群。"""
    from nonebot_plugin_hermes.core.routing import resolve_target

    _set_table(monkeypatch, {"ob11:u1": {"url": "http://127.0.0.1:9999"}})
    assert resolve_target("ob11", True, None).label == "default"


def test_entry_inherits_global_key_and_timeout(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import resolve_target

    monkeypatch.setattr(plugin_config, "hermes_api_key", "sk-global")
    monkeypatch.setattr(plugin_config, "hermes_api_timeout", 300)
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8643"}})

    tgt = resolve_target("ob11", False, "g1")
    assert tgt.api_key == "sk-global"
    assert tgt.timeout == 300


def test_all_targets_includes_default_and_entries(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import all_targets

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8643"}})

    labels = [t.label for t in all_targets()]
    assert labels == ["default", "ob11:g1"]


def test_routing_adapter_normalization_matches_get_adapter_name():
    """routing 自己归一化 adapter 段(不 import utils),口径必须与 get_adapter_name 一致。"""
    from types import SimpleNamespace

    from nonebot_plugin_hermes.core.routing import _normalize_adapter
    from nonebot_plugin_hermes.utils import get_adapter_name

    for raw in ("OneBot V11.", "Telegram", "onebot.v11"):
        assert _normalize_adapter(raw) == get_adapter_name(SimpleNamespace(adapter=raw))


def test_validate_endpoints_flags_missing_key(monkeypatch):
    """指向别的接入点却没有自己的 key:既 401 又没有反向隔离 —— 启动时就要说。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    monkeypatch.setattr(plugin_config, "hermes_api_key", "sk-global-at-least-16")
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8642/p/teamA"}})

    problems = validate_endpoints()
    assert len(problems) == 1
    assert "ob11:g1" in problems[0]


def test_validate_endpoints_flags_bad_key_and_url(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    monkeypatch.setattr(plugin_config, "hermes_api_key", "sk-global-at-least-16")
    _set_table(
        monkeypatch,
        {
            "no-colon-key": {"url": "http://127.0.0.1:8643", "key": "k-at-least-16-chars"},
            "ob11:g2": {"url": "127.0.0.1:8643", "key": "k-at-least-16-chars"},
        },
    )

    problems = validate_endpoints()
    assert any("no-colon-key" in p for p in problems)
    assert any("ob11:g2" in p for p in problems)


def test_validate_endpoints_flags_unnormalized_adapter(monkeypatch):
    """get_adapter_name() 输出小写去空格去点,写成 OneBotV11:… 永远匹配不上。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    _set_table(monkeypatch, {"OneBotV11:g1": {"url": "http://127.0.0.1:8643", "key": "k-at-least-16-chars"}})

    assert any("OneBotV11" in p for p in validate_endpoints())


def test_validate_endpoints_flags_short_key(monkeypatch):
    """上游 has_usable_secret(min_length=16):短 key 在 profile 侧等于没配。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8642/p/teamA", "key": "short"}})

    assert any("16" in p for p in validate_endpoints())


def test_validate_endpoints_flags_same_url_different_keys(monkeypatch):
    """同一个接入点两把不同的 key:其中一把必然 401。"""
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    _set_table(
        monkeypatch,
        {
            "ob11:g1": {"url": "http://127.0.0.1:8642/p/teamA", "key": "key-one-at-least-16"},
            "ob11:g2": {"url": "http://127.0.0.1:8642/p/teamA", "key": "key-two-at-least-16"},
        },
    )

    assert any("teamA" in p for p in validate_endpoints())


def test_validate_endpoints_silent_when_clean(monkeypatch):
    from nonebot_plugin_hermes.config import plugin_config
    from nonebot_plugin_hermes.core.routing import validate_endpoints

    monkeypatch.setattr(plugin_config, "hermes_api_url", "http://127.0.0.1:8642")
    _set_table(monkeypatch, {"ob11:g1": {"url": "http://127.0.0.1:8643", "key": "sk-a-at-least-16-ch"}})
    assert validate_endpoints() == []
