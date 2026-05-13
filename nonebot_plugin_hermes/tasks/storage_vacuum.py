"""定时清理:消息日志 vacuum + 图片缓存配额淘汰。"""

from __future__ import annotations

import time

from nonebot import logger, require

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from .. import mcp as _mcp  # lazy access to runtime singletons
from ..config import plugin_config


def register_storage_vacuum() -> None:
    """每小时整点过 37 分跑一次。

    错峰避开 expire_active_sessions(那个跑秒级 interval),且 :37 是个安静时段
    (与各种整点报告 / 业务监控错开)。
    """

    @scheduler.scheduled_job(
        "cron",
        minute=37,
        id="hermes_storage_vacuum",
        replace_existing=True,
    )
    async def _vacuum() -> None:
        if _mcp.message_store is None or _mcp.image_cache is None:
            return
        retention_days = plugin_config.hermes_storage_message_retention_days
        max_rows = plugin_config.hermes_storage_message_max_rows
        min_ts = int(time.time() * 1000) - retention_days * 86400 * 1000
        msg_deleted = _mcp.message_store.vacuum(min_ts=min_ts, max_rows=max_rows)
        img_bytes_evicted = _mcp.image_cache.evict_if_over_quota()
        if msg_deleted or img_bytes_evicted:
            logger.info(f"[storage-vacuum] messages_deleted={msg_deleted} image_bytes_evicted={img_bytes_evicted}")
