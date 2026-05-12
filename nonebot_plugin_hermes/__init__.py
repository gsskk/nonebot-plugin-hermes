"""
NoneBot Plugin Hermes

通过 Hermes Agent API Server 实现多平台 AI 聊天机器人。
"""

from nonebot import get_driver, logger, require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

# 确保依赖的插件已加载
require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")

from .config import Config, plugin_config

__version__ = "0.2.2"

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

# handlers 必须在 plugin manager 上下文里 import,matchers 才会注册到此插件名下
from . import handlers  # noqa: F401, E402

# 所有运行时副作用挪到 driver.on_startup 钩子,避免 plugin import 阶段
# 触发 nb-cli 的 "not loaded as a plugin" 检测(顶层副作用过重时会撞这个雷)。
_driver = get_driver()


@_driver.on_startup
async def _hermes_m1_startup():
    """M1-mem 启动序列:装配运行时单例 + 起 MCP server + 注册 cron。

    注意:不能在 on_startup 钩子里再追加 on_startup 钩子(已经在 startup phase 里),
    所以直接 await start_mcp_server() 而非走 register_lifecycle 的间接路径。
    on_shutdown 钩子仍可在此追加,因为 shutdown phase 还没到。
    """
    from .mcp import init_runtime_state, start_mcp_server, stop_mcp_server
    from .tasks import register_expire_active_sessions

    init_runtime_state()
    await start_mcp_server()
    _driver.on_shutdown(stop_mcp_server)
    register_expire_active_sessions()
    logger.info(
        f"Hermes Plugin loaded — API: {plugin_config.hermes_api_url} | "
        f"MCP: {'on ' + plugin_config.hermes_mcp_host + ':' + str(plugin_config.hermes_mcp_port) if plugin_config.hermes_mcp_enabled else 'off'} | "
        f"active_session: {'on' if plugin_config.hermes_active_session_enabled else 'off'}"
    )
