"""
NoneBot Plugin Hermes

通过 Hermes Agent API Server 实现多平台 AI 聊天机器人。
支持所有 NoneBot adapter（OneBot v11/v12、QQ Official、Kook 等）。
"""

from nonebot import require, logger
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

# 确保依赖的插件已加载
require("nonebot_plugin_alconna")

from .config import Config, plugin_config  # noqa: E402

__version__ = "0.1.0"

__plugin_meta__ = PluginMetadata(
    name="Hermes Agent",
    description="通过 Hermes Agent API Server 实现多平台 AI 聊天机器人",
    homepage="https://github.com/NousResearch/hermes-agent",
    usage=(
        "在群聊中 @机器人 发送消息即可与 Hermes Agent 对话。\n"
        "私聊直接发送消息即可。\n\n"
        "命令：\n"
        "/clear - 重置对话\n"
        "/ping - 检查连接状态\n"
        "/help - 显示帮助"
    ),
    type="application",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={
        "author": "NousResearch",
        "version": __version__,
    },
)

logger.info(f"Hermes Plugin loaded — API: {plugin_config.hermes_api_url}")

# 导入 handlers 以注册事件处理器
from . import handlers  # noqa: F401, E402
