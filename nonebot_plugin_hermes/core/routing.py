"""按群解析 Hermes 接入点。

Hermes 把工具集、模型、文件工作区都绑在 profile(一份独立的 HERMES_HOME)上,
所以"这个群能用什么能力"在插件侧唯一的表达方式就是"这个群连哪个接入点"。

一个 base_url 字段同时覆盖两种部署形态:
  - 多路复用:同一个 gateway 用 /p/<profile>/ 前缀服务多个 profile
  - 独立进程:每个 profile 各自监听一个端口
两者对插件而言只是 URL 不同,不需要分支。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import HermesEndpoint, plugin_config

_DEFAULT_LABEL = "default"

# 上游 has_usable_secret 的门槛:短于此,profile 侧会判为"未配置"并拒绝请求。
_MIN_KEY_LEN = 16


@dataclass(frozen=True)
class HermesTarget:
    """一次调用要发往的 Hermes 接入点。

    不可变且随用随解析:配置可在运行期被改(测试、热更),缓存会让路由与配置漂移。
    """

    base_url: str
    api_key: str
    timeout: int
    label: str
    """诊断用标签:默认接入点为 "default",其余为路由键 `{adapter}:{group_id}`。"""


def default_target() -> HermesTarget:
    return HermesTarget(
        base_url=plugin_config.hermes_api_url.rstrip("/"),
        api_key=plugin_config.hermes_api_key,
        timeout=plugin_config.hermes_api_timeout,
        label=_DEFAULT_LABEL,
    )


def _from_entry(label: str, entry: HermesEndpoint) -> HermesTarget:
    return HermesTarget(
        base_url=entry.url.rstrip("/"),
        api_key=entry.key or plugin_config.hermes_api_key,
        timeout=entry.timeout or plugin_config.hermes_api_timeout,
        label=label,
    )


def resolve_target(adapter_name: str, is_private: bool, group_id: str | None) -> HermesTarget:
    """解析这一轮该发往哪个接入点。私聊与未配置的群一律走默认接入点。"""
    if is_private or not group_id:
        return default_target()
    label = f"{adapter_name}:{group_id}"
    entry = plugin_config.hermes_group_endpoints.get(label)
    if entry is None:
        return default_target()
    return _from_entry(label, entry)


def all_targets() -> list[HermesTarget]:
    """默认接入点 + 表内全部接入点,供体检类命令逐个探活。"""
    targets = [default_target()]
    for label, entry in plugin_config.hermes_group_endpoints.items():
        targets.append(_from_entry(label, entry))
    return targets


def _normalize_adapter(raw: str) -> str:
    """与 utils.get_adapter_name 的归一化保持一致(测试钉住这个等价关系)。

    这里不 import utils:那会把 alconna 拉进 core 层。
    """
    return raw.lower().replace(" ", "").replace(".", "") or "unknown"


def validate_endpoints() -> list[str]:
    """返回配置问题描述(启动期 WARN 用)。只描述不修正,也不抛。"""
    problems: list[str] = []
    default_url = plugin_config.hermes_api_url.rstrip("/")
    entries = plugin_config.hermes_group_endpoints

    for label, entry in entries.items():
        adapter_part = label.split(":", 1)[0]
        if ":" not in label:
            problems.append(f"路由键 {label!r} 不是 '{{adapter}}:{{group_id}}' 形式,永远匹配不上")
        elif adapter_part != _normalize_adapter(adapter_part):
            problems.append(
                f"路由键 {label!r} 的 adapter 段未归一化(应为 {_normalize_adapter(adapter_part)!r}:"
                f"小写、去空格与点),永远匹配不上"
            )

        url = entry.url.strip()
        if not url.startswith(("http://", "https://")):
            problems.append(f"{label} 的 url {url!r} 不是 http(s) 地址")
            continue

        if url.rstrip("/") != default_url and not entry.key:
            problems.append(
                f"{label} 指向与默认接入点不同的地址却没有自己的 key:命名 profile 校验的是它自己的 "
                f"API_SERVER_KEY(请求会 401),而且该群在反向通道里也拿不到独立权限(落回默认接入点的补集)"
            )
        elif entry.key and len(entry.key) < _MIN_KEY_LEN:
            problems.append(f"{label} 的 key 短于 {_MIN_KEY_LEN} 字符,上游会判为未配置并拒绝请求")

    # 同一个接入点配了多把不同的 key —— 其中至少一把必然 401。
    keys_by_url: dict[str, set[str]] = {}
    for entry in entries.values():
        if entry.key:
            keys_by_url.setdefault(entry.url.strip().rstrip("/"), set()).add(entry.key)
    for url, keys in keys_by_url.items():
        if len(keys) > 1:
            problems.append(f"接入点 {url} 在表内配了 {len(keys)} 把不同的 key,其中至少一把会 401")

    return problems
