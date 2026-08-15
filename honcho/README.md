# Honcho 自托管示例

`HERMES_HONCHO_ENABLED=true` 只是让插件多发一个 `X-Hermes-Session-Key` 请求头。真正把
长期记忆按群存起来的是 **Hermes 那端的 memory provider**,目前只有 Honcho 会消费这个头
(其他 provider 收到也不理)。

这个目录是部署 Honcho 的示例配置,不是插件运行的必需品——不接 memory provider 时,
那个开关是 no-op,插件行为与关掉时完全一致。

| 文件 | 用途 |
|------|------|
| `docker-compose.yml` | 四个服务:api / deriver / postgres(pgvector) / redis |
| `.env.example` | 面向本插件用途裁剪过的配置示例 |

## 前置

- Docker(上游没有发布预构建镜像,api 与 deriver 都从源码构建,首次拉取 + 构建约 2~3G)
- 一个 OpenAI 兼容的 LLM 网关与 key
- 磁盘:镜像落在 docker 的 data-root,pgdata 落在 `HONCHO_DATA`,两处都要预留空间

## 部署

```bash
git clone https://github.com/plastic-labs/honcho.git /opt/honcho

mkdir -p ~/honcho-deploy && cd ~/honcho-deploy
cp <本仓库>/honcho/docker-compose.yml .
cp <本仓库>/honcho/.env.example .env
$EDITOR .env                      # 填 key、改 POSTGRES_PASSWORD

export HONCHO_SRC=/opt/honcho     # 源码位置
export HONCHO_DATA=/data/honcho   # 数据落盘位置(可选,默认 ./data)

docker compose up -d --build
docker compose logs -f api        # 首次启动会自动跑数据库迁移
```

API 默认在 `http://127.0.0.1:8000`。

## 接到 Hermes

Honcho 是 Hermes 的插件,而 **Hermes 的插件是 opt-in 的**——只加载
`~/.hermes/config.yaml` 里 `plugins.enabled` 列出的插件。没启用时 `hermes honcho`
这个子命令根本不存在(报 `invalid choice: 'honcho'`),因为它是插件注册出来的。

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - honcho
```

装上 `honcho-ai` 依赖后重启 Hermes,再跑 `hermes honcho setup` 指向上面的地址。
验证配置是否生效:

```bash
hermes honcho status      # 连接状态
hermes honcho strategy    # 当前 session 命名策略
```

最后在 bot 的 `.env` 里打开插件侧开关:

```dotenv
HERMES_HONCHO_ENABLED=true
HERMES_GROUP_SESSIONS_PER_USER=false   # 一个群一份记忆,群成员共享
```

需要注意 Hermes 端必须配了 `API_SERVER_KEY`,插件端必须配了 `HERMES_API_KEY`——
上游对 `X-Hermes-Session-Key` 要求鉴权,没有 key 时插件不发这个头并在启动日志 WARN。

## 验证链路通了

把 Hermes 日志开到 debug,在群里 @ 一次 bot,应该看到 Honcho 插件打出解析后的 session key:

```
Honcho session key resolved: agent-main-nonebot-onebotv11-group-<群号>
```

换个群再 @ 一次,这个值应该跟着变——这就是群间记忆隔离生效的直接证据。
(冒号会被 Honcho 净化成 `-`,正常。)

## 成本

Honcho 不是装上就完事的组件,它持续烧 LLM 额度:

- **deriver**:每条消息触发一次后台提炼——这是大头
- **dialectic**:按轮次触发,一轮可能多发几次
- **summary**:会话推进到一定长度跑一次
- **embedding**:开启时每条消息一次(`.env.example` 里默认关掉)

群越活跃烧得越多,而且这些后台调用与 bot 回复用户**共用同一个额度池**。如果你的 LLM
是按额度封顶的订阅制,强烈建议给 Honcho 单配一把便宜的 key,把后台提炼和主对话分开——
否则后台把额度啃完时,表现是 bot 该说话时说不了,排查起来会绕远路。

省钱的三个旋钮:flash 档模型、`DERIVER_WORKERS=1`、`EMBED_MESSAGES=false`。

## 预期

记忆需要累积,头一两周体感不明显——这是正常的,不要在第三天下结论。

另外这个开关只隔离**记忆**。`session_search` 工具搜的是整个 state.db、不分群,
要一并堵住需在 Hermes 端的 `platform_toolsets.api_server` 里移除该工具。
