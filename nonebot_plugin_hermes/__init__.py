"""
NoneBot Plugin Hermes

通过 Hermes Agent API Server 实现多平台 AI 聊天机器人。
"""

from nonebot import logger, require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

# 确保依赖的插件已加载
require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")

from .config import Config, plugin_config
from .mcp import init_runtime_state, register_lifecycle

__version__ = "0.2.0-m1mem"

__plugin_meta__ = PluginMetadata(
    name="Hermes Agent",
    description="通过 Hermes Agent API Server 实现多平台 AI 聊天机器人",
    homepage="https://github.com/gsskk/nonebot-plugin-hermes",
    usage=(
        "在群聊中 @机器人 发送消息即可与 Hermes Agent 对话。\n"
        "私聊直接发送消息即可。\n\n"
        "M1: 群聊 @ 后 5 分钟内 bot 会监听话题相关消息并按需主动插话。\n\n"
        "命令:\n"
        "/clear - 重置对话\n"
        "/ping - 检查连接状态\n"
        "/help - 显示帮助"
    ),
    type="application",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"author": "gsskk", "version": __version__},
)

# 装配内存运行时(message_buffer / active_sessions / bot_registry)
init_runtime_state()

# 注册 MCP server 启动 / 停止钩子
register_lifecycle()

# 注册 cron 任务
from .tasks import register_expire_active_sessions  # noqa: E402

register_expire_active_sessions()

# 导入 handlers 注册事件处理器(必须在 PluginMetadata 与 init_runtime_state 之后)
from . import handlers  # noqa: F401, E402

logger.info(
    f"Hermes Plugin loaded — API: {plugin_config.hermes_api_url} | "
    f"MCP: {'on ' + plugin_config.hermes_mcp_host + ':' + str(plugin_config.hermes_mcp_port) if plugin_config.hermes_mcp_enabled else 'off'} | "
    f"active_session: {'on' if plugin_config.hermes_active_session_enabled else 'off'}"
)
