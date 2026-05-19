"""
配置模型

所有配置项通过 NoneBot 的 .env 文件读取，前缀为 HERMES_。
"""

from typing import Set

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class Config(BaseModel):
    # --- Hermes API Server ---
    hermes_api_url: str = "http://127.0.0.1:8642"
    """Hermes API Server 地址"""

    hermes_api_key: str = ""
    """Hermes API Server 密钥(对应 api_server.extra.key)"""

    hermes_api_timeout: int = 300
    """API 请求超时时间(秒),Agent 执行可能较慢"""

    # --- 触发模式 ---
    hermes_group_trigger: str = "at"
    """群聊触发方式: at / all / keyword"""

    hermes_keywords: Set[str] = {"/ai"}
    """keyword 模式下的触发关键词"""

    hermes_private_trigger: str = "all"
    """私聊触发方式: all / allowlist"""

    hermes_allow_users: Set[str] = set()
    """允许私聊的用户 ID(allowlist 模式)"""

    hermes_allow_groups: Set[str] = set()
    """允许响应的群组 ID(空 = 全部允许)"""

    hermes_admin_users: Set[str] = set()
    """管理员白名单(adapter+user 复合 ID)。用于 /hermes-status 等敏感命令。
    格式:`{adapter}:{user_id}`,adapter 取小写 + 去空格点(同 get_adapter_name)。
    例:["telegram:7055555877", "onebotv11:12345678"]
    空集 = 不允许任何人使用敏感命令(默认 deny)。"""

    # --- 会话 ---
    hermes_session_share_group: bool = False
    """群内是否共享同一个 session(False = 每人独立)"""

    # --- 消息 ---
    hermes_max_length: int = 4000
    """单条回复最大长度(超出截断,QQ 限制约 4500 字符)"""

    hermes_ignore_prefix: Set[str] = {"."}
    """以这些字符开头的消息不触发回复"""

    # --- 被动感知 (Chat Awareness) ---
    hermes_perception_enabled: bool = False
    """是否开启被动感知(监听但不回复非触发消息,为下次对话提供背景)"""

    hermes_perception_buffer: int = 10
    """被动感知缓存的历史消息数量"""

    hermes_perception_text_length: int = 200
    """被动感知单条历史消息最大长度(超出截断)"""

    hermes_perception_image_mode: str = "placeholder"
    """历史记录中的图片处理模式:
    - placeholder: 历史里图只用 [图片] 占位 + URL 引用,多模态 content 只发当前图 (默认)
    - inline_labeled: 历史最后一张图带 <<HISTORICAL IMAGES>> 标签放入多模态 content,与当前图清晰分隔
    - none: 完全不提历史图
    旧值 'last' 视为 'inline_labeled' 别名 (已废弃,启动时 WARN)

    **DEPRECATED (2026-05-13)**: 历史图召回改走 MCP 工具 (get_message_images),
    本配置仅控制 [图片] 占位是否出现在历史里;inline_labeled 模式已不再实装。
    """

    # --- M1: 内存缓冲 ---
    hermes_buffer_per_group_cap: int = 200
    """每群在 MessageBuffer 中保留多少条最近消息(LRU 之外的硬上限)"""

    hermes_buffer_total_groups_cap: int = 50
    """MessageBuffer 跨群总容量,超出按 LRU 驱逐"""

    # --- M1: 活跃态 ---
    hermes_active_session_enabled: bool = False
    """是否开启 @ 触发的群活跃态(False 退化为 v0.1.6 等价行为)"""

    hermes_active_session_ttl_sec: int = 300
    """活跃态默认 TTL(秒),滑动续期"""

    hermes_active_sweep_interval_sec: int = 30
    """expire_active_sessions cron 频率(秒)"""

    # --- Notice 事件触发 (Phase A) ---
    hermes_poke_trigger_enabled: bool = False
    """OneBot v11: 被戳一戳时触发对话(私聊/群无差别),等价 @。
    其他适配器无效,缺省全关 = 老用户行为零变化。"""

    hermes_greet_on_join: bool = False
    """OneBot v11: 群里有人加入时,在 active_session 开启的群触发一次 reactive turn
    让 Hermes 自决是否欢迎(decision_protocol 的 noop 是合法选择)。
    active_session 关时不触发——passive 是 1:1 Q&A 语义,不适用欢迎场景。"""

    # --- Phase B-0: ack 反馈 + 非文本段感知 ---
    hermes_ack_feedback_enabled: bool = False
    """显式触发 (用户主动 @ bot 或私聊) 时给一个'已收到'视觉回执。
    B-0 实装: OneBot v11 **群聊** (NapCat/LLOneBot/LuckyLilliaBot) 贴 emoji,
    chat 完成后撤销。其他适配器或场景 silently no-op。

    开关名通用,B-0.5 规划里要扩 Telegram/Discord 私聊 typing 状态,避免改名 breaking。

    **已知限制**:
      - 私聊不贴 emoji: QQ NT 协议下 set_msg_emoji_like 仅支持群聊
        (LuckyLilliaBot/NapCat 在私聊调用都会 raise '只支持群聊消息')
      - emoji 撤销依赖 OneBot 实现端较新版本:
          NapCat: 全版本支持 (用 set=False)
          LuckyLilliaBot / 较新 LLOneBot: 支持 (unset_msg_emoji_like 或 set=False)
          老 LLOneBot: 两条路径都不支持, emoji 永久留在消息上 (启动后 WARN-once 告知)
    若 emoji 不撤销但你不想 disable, 接受'永久已读痕迹'即可——不影响主流程。"""

    hermes_ack_emoji_id: int = 341
    """B-0 OneBot v11 路径下贴的 QQ 表情 id。默认 341 (/打招呼) ——
    动画"hi 打招呼",bot 收到 @ 的最自然反馈。
    其他推荐:
      - 373 (/忙):一只小动物在打字,typing-indicator 风格
      - 129 (/挥手):经典小表情版的挥手,跨版本更稳但视觉平淡
    注意:341/373 是 QQ NT 超表情 (EMCode 10000+),NapCat 内部有个
    `length > 3 ? type=2 : type=1` 启发式,3 位 id 会被当经典型——
    实测多数 NapCat 版本仍能正常 render,但跨版本不保证。
    若实测视觉异常,可换经典型小表情 (EMCode < 300,如 129)。
    NapCat schema 接受 Number | String,走 int 是为了 .env 直接写数字
    (HERMES_ACK_EMOJI_ID=237 不用引号),pydantic-settings 不会撞类型错。
    完整列表见 NapCat face_config.json。仅 OneBot 路径用到。"""

    hermes_reactive_post_reply_cooldown_sec: int = 8
    """reactive 模式下,bot 刚回复完群里 N 秒内,非显式 @ 触发的新消息直接静默。
    用来阻断「我刚说完别人接话→我又凑一句」类型的过触发。
    0 = 关闭(回退到旧行为)。显式 @bot 不受影响,任何时候都会立刻进入决策。"""

    hermes_transport_error_fallback_text: str = "嗯…我这边遇到点状况,稍后再问一次"
    """Hermes 上游返 5xx / 传输错误时, 替代 LLM raw_text 的兜底文本。
    没有这条兜底, 服务端英文错误信息(如 "Model generated invalid tool call: ...")
    会被原文当 raw_text 发到群里,体验差也泄露内部信息。
    空串 → 不发任何文本(等价于 silent)。仅在 reactive 显式触发 / passive 路径生效——
    非显式触发本来就静默,不受影响。"""

    # --- M1: 反向 MCP 通道 ---
    hermes_mcp_enabled: bool = False
    """是否启动内嵌 FastMCP server(False 时 Hermes 反向调用全失败,出向不影响)"""

    hermes_mcp_host: str = "127.0.0.1"
    """MCP server bind host. 默认 loopback (127.0.0.1)。
    改监听公网/局域网在技术上可行,但安全代价:push_message 能让 bot 往群里发
    任意内容,前端防御只有 Bearer token(明文 HTTP,且与 HERMES_API_KEY 同
    钥匙)。要改请配套反向代理 + TLS + 来源 IP ACL。"""

    hermes_mcp_port: int = 8643
    """MCP server bind port"""

    hermes_mcp_recent_limit_max: int = Field(default=50, ge=1)
    """get_recent_messages 工具单次返回上限。最小 1——0/负值会让工具静默返空,
    Pydantic 在启动期校验防 misconfig。"""

    # --- M1: 持久化存储 ---
    hermes_storage_db_path: str = ""
    """SQLite 消息日志路径。空串走默认 ~/.local/share/nonebot-plugin-hermes/messages.db"""

    hermes_storage_message_retention_days: int = 30
    """消息日志保留天数,超龄行 vacuum 时删"""

    hermes_storage_message_max_rows: int = 100_000
    """消息日志总行数硬上限,超出 vacuum 时按 ts 老到新删"""

    hermes_image_cache_dir: str = ""
    """图字节缓存目录。空串走默认 ~/.cache/nonebot-plugin-hermes/images/"""

    hermes_image_cache_quota_mb: int = 200
    """图缓存总体积上限(MB),超出按 atime 老到新淘汰"""

    hermes_image_fetch_timeout_s: int = 10
    """单图 HTTP 抓取超时秒数"""

    hermes_image_fetch_max_attempts: int = 2
    """单图总尝试次数(1=不重试,2=一次重试,以此类推)"""


plugin_config = get_plugin_config(Config)
