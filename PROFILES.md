# 按群路由到不同 Hermes 接入点(profiles / 多路复用)

> 0.5.1+,默认关。本文从 [README](README.md) 抽出,单独成篇。

让指定的群走各自的 Hermes **profile**,从而拥有该群独占的工具集、模型和文件工作区。

**先确认你要的是不是这个**:只想让 bot 别把 A 群的事在 B 群说出来,用 README 里的
`HERMES_HONCHO_ENABLED`(「长期记忆作用域」小节)就够了 —— 单进程、不改部署、不用为每个群维护
一份 profile。本节解决的是另一件事:**A 群只能查资料、B 群能跑代码**这种按群给不同能力。它顺带也
隔离了记忆(profile 各有自己的 state.db),代价是每多一个接入点,Hermes 侧就多一份要维护的
`HERMES_HOME`。

反向通道(`push_message` 等)的权限范围也挂在这张路由表上、按接入点自动收敛 —— 见下方
「反向通道自动跟着收敛」。

---

## 插件侧配置

```dotenv
# 键是 {adapter}:{group_id};未列出的群和所有私聊走默认的 HERMES_API_URL
HERMES_GROUP_ENDPOINTS='{"onebotv11:12345": {"url": "http://127.0.0.1:8642/p/team-a", "key": "<team-a 的 API_SERVER_KEY>"}}'
```

两种部署形态共用同一个 `url` 字段:

| 形态 | Hermes 侧 | `url` 填 |
|------|-----------|----------|
| 多路复用(推荐) | `hermes config set gateway.multiplex_profiles true` 后重启 gateway | `http://host:8642/p/<profile>` |
| 独立进程 | 每个 profile 各起一个 api server | `http://host:8643`(各自端口) |

`key` 留空会沿用全局 `HERMES_API_KEY`,`timeout` 留空沿用 `HERMES_API_TIMEOUT`。

> [!WARNING]
> **profile 名必须全小写**(合法字符 `[a-z0-9][a-z0-9_-]{0,63}`)。`hermes profile create TeamA` 会把名字
> 归一化成小写再落盘(`profiles/teama/`),但 URL 前缀**不做归一化** —— 上游只 `strip()` 后直接和目录名
> 集合比对,所以 `/p/TeamA/` 对着 `profiles/teama/` 会直接 **404**。名字里想分词就用 `-` 或 `_`。

> [!IMPORTANT]
> **指向命名 profile 时 `key` 必填,而且必须与默认 profile 的不同、不短于 16 字符。** 三个原因:
> 上游校验的是该 profile 自己的 `API_SERVER_KEY`(沿用全局 key 必然 401);它是反向通道认身份的
> 依据(见下);而且它是**"忘开 `gateway.multiplex_profiles`"唯一的告警器** —— 多路复用关闭时上游会
> **静默忽略** `/p/<profile>/` 前缀、把请求当默认 profile 处理,此时只有 key 不匹配才会报 401,
> 否则你会看到"一切正常"但零隔离。

---

## 完整示例:多个群,部分共用同一 profile

这是最常见、也最容易配错的形态:**几个群共用同一个 profile**,另外几个群各走别的 profile。
关键一句先说在前面:

> **反向通道要配几个命名 MCP server,由「不同 profile / 不同 key 的个数」决定,不是群数。**
> 共用一把 key 的那几个群会自动落进同一个 scope,一个 server 就全盖住。

设想:6 个群进路由表。其中 4 个群(`10001`~`10004`)共用 profile **team-a**(同一把
`API_SERVER_KEY`),另外 2 个群(`10005`、`10006`)走 profile **lab**(另一把 key)。其余所有群
和全部私聊走默认接入点。→ 一共 **2 个命名 profile**,所以反向通道要配 **2 个命名 server**
(`nonebot-team-a`、`nonebot-lab`)加一个补集用的 `nonebot-default`,**不是 6 个**。

**① 插件侧 `.env`**(`HERMES_GROUP_ENDPOINTS` 在 `.env` 里必须写成**一行**,这里为可读性折行):

```jsonc
{
  "onebotv11:10001": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10002": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10003": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10004": { "url": "http://10.0.0.2:8642/p/team-a", "key": "<team-a API_SERVER_KEY>" },
  "onebotv11:10005": { "url": "http://10.0.0.2:8642/p/lab",    "key": "<lab API_SERVER_KEY>" },
  "onebotv11:10006": { "url": "http://10.0.0.2:8642/p/lab",    "key": "<lab API_SERVER_KEY>" }
}
```

同一 profile 的几个群,`url` 与 `key` 都填成**一模一样**的那把。给它们配不同的 key 会触发启动
WARNING(「同一接入点多把 key,至少一把会 401」),而且反向通道会把它们拆成两个 scope。

**② Hermes 默认 profile**(`~/.hermes/config.yaml`)—— 所有 MCP 连接与 token 都在这里建立:

```yaml
mcp_servers:
  nonebot-default: { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <全局 HERMES_API_KEY>" } }
  nonebot-team-a:  { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <team-a API_SERVER_KEY>" } }
  nonebot-lab:     { url: http://<bot>:8643/mcp, headers: { Authorization: "Bearer <lab API_SERVER_KEY>" } }

platform_toolsets:
  api_server: [<默认原有工具集>, nonebot-default]   # 默认 profile 只声明自己那个名字
```

**③ team-a**(`~/.hermes/profiles/team-a/config.yaml`)—— 只**引用**属于自己的那个名字:

```yaml
platforms:
  api_server: { enabled: false }                    # 端口绑定类平台只能留在默认 profile
platform_toolsets:
  api_server: [<team-a 的工具集>, nonebot-team-a]
mcp_servers:
  nonebot-team-a: { url: http://<bot>:8643/mcp }    # 声明名字即开启;url/headers 在这里不生效
```

**④ lab**(`~/.hermes/profiles/lab/config.yaml`)同理,把 `team-a` 换成 `lab`、引用 `nonebot-lab`。

于是:team-a 名下那 4 个群的 agent 只看到 `mcp__nonebot_team_a__*`,发出的请求带 team-a 那把
token → 插件把 scope 判成「team-a 名下的群」= 恰好那 4 个;lab 同理。为什么这样就够、原理见下。

---

## 老的默认接入点不会失效

打开多路复用后,原来那个监听器仍由**默认 profile** 持有:不带前缀的老 URL、老 key 继续可用,
`API_SERVER_KEY` 放在 systemd `Environment=` / docker `environment:` 里也照样读得到(上游对默认
profile 的凭证读取保留了 `os.environ` 回落)。要迁的只有**新增的命名 profile**,它的 key 必须放在
该 profile 自己的 `.env` 里。

---

## Hermes 侧要做的事

一次性(在**默认 profile** 上做,它才是多路复用器):

```bash
hermes config set gateway.multiplex_profiles true
hermes gateway restart
```

多路复用打开后,**不要**再为次级 profile 单独 `hermes gateway start`。次级 profile 自己的
config.yaml 要这样写:

```yaml
# ~/.hermes/profiles/team-a/config.yaml —— 次级 profile 的,不是默认 profile 的
platforms:
  api_server:
    enabled: false                     # 端口绑定类平台只能留在默认 profile

mcp_servers:
  nonebot-team-a:                      # 声明名字即开启;url/headers 在这里不生效
    url: http://<bot>:8643/mcp

platform_toolsets:
  api_server: [<该 profile 原有的工具集>, nonebot-team-a]   # 不列出来它就拿不到反向通道
```

对应的默认 profile —— 所有 MCP 连接和 token 都由它建立:

```yaml
# ~/.hermes/config.yaml —— 默认 profile
mcp_servers:
  nonebot-default:                     # 补集:不在路由表里的群
    url: http://<bot>:8643/mcp
    headers: { Authorization: "Bearer <全局 HERMES_API_KEY>" }
  nonebot-team-a:                      # team-a 名下的群
    url: http://<bot>:8643/mcp
    headers: { Authorization: "Bearer <team-a 的 API_SERVER_KEY>" }

platform_toolsets:
  api_server: [<原有工具集>, nonebot-default]              # 默认 profile 只列自己那个名字
```

`api_server` 之外,`webhook`、`msgraph_webhook`、`wecom_callback`、`bluebubbles`、`sms`、
`whatsapp_cloud`、`line`,以及 `connection_mode: webhook` 的 `feishu` 同样要关。`hermes profile
create --clone` 会把默认 profile 的 config.yaml 整份复制过去,一定要查这一项。没关的话 gateway
启动日志会刷 `Skipping secondary profile '<name>' due to port-binding config error`,该 profile 的
**全部** adapter 都不启动 —— 但 `/p/<name>/` 仍然可用,所以这条告警很容易被当噪音放着。

`mcp_servers` / `platform_toolsets` 那两段只在用反向通道时才需要,取舍见下方
「反向通道自动跟着收敛」。反过来,如果你选的是"独立进程"形态,那就**别开**多路复用。

`hermes profile create` 结尾打印的 `Next steps` 里那条 `<name> gateway start` 是写给默认的
"一进程一 profile"部署的,**多路复用下别执行**(`<name> setup` 要执行,`<name> chat` 可以用来
验证 key 配好了)。上游确实有守卫会拒绝它并让你改用默认 profile 的 `hermes gateway restart`,
但那个守卫有两个前提、不能当保险:它要**默认 gateway 正在运行**才探测得到(默认 gateway 停着时
这条命令会成功起一个独立进程,之后拉起多路复用器就双绑:同一 bot token 两个 poller、端口冲突),
而且要该 profile 在 `multiplex_profile_allowlist` 的服务范围内,被排除掉时守卫直接放行。

`hermes config set gateway.multiplex_profiles true` 可能会打印一条 `not a recognized config key`
并建议你改成 `gateway.multiplex_profile_allowlist` —— **别照着改**。这个键运行时确实会被读
(`gateway/config.py` 里有专门认它的分支,注释直接点名这条命令),告警只是上游 CLI 的键表没登记
嵌套形式;想消掉就用顶层形式 `hermes config set multiplex_profiles true`(等价)或加 `--force`。
`multiplex_profile_allowlist` 是另一件事:哪些命名 profile 被多路复用器服务,**留空不配 = 全部服务**,
设成 `[]`(或写错类型 fail-safe 成 `[]`)则只服务默认 profile,你的 `/p/team-a/` 会 404。

改完重启,然后用这条确认前缀真的生效(唯一的 ground truth):

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer <team-a 自己的 API_SERVER_KEY>" \
  http://<hermes-host>:8642/p/team-a/v1/models
# 200 = 生效;401 = 前缀被静默忽略(当默认 profile 处理了,等于没开);
# 404 = 前缀被拒(profile 不存在,或被 allowlist 排除)
```

每个新接入点各一次:

```bash
export TEAM_HOME=~/.hermes/profiles/team-a

hermes profile create team-a                       # 独立 state.db / 记忆 / skills / config.yaml
team-a setup                                       # 给它自己的大模型 API key(见下方 WARNING,别跳过)
echo "API_SERVER_KEY=$(openssl rand -hex 32)" >> $TEAM_HOME/.env   # 必须与默认 profile 不同

# 这个群能用什么能力 —— 本功能唯一不可替代的价值就在这一步。
# 编辑 $TEAM_HOME/config.yaml 的 platform_toolsets.api_server,工具集选法见
# README「限制 API Server 工具集」那张表。

HERMES_HOME=$TEAM_HOME hermes-install-skill       # skill 按 profile 分别装

# 反向通道:只给需要它的 profile 配。**两种部署形态写法不同**,见下面
# 「反向通道自动跟着收敛」小节 —— 多路复用下 Bearer 必须配在默认 profile 上,
# 这里写的 header 不会生效。独立进程形态才是下面这条:
HERMES_HOME=$TEAM_HOME hermes mcp add nonebot --url http://<bot>:8643/mcp
#   Bearer 填上面那把 API_SERVER_KEY
```

**两边唯一需要一致的值就是这把 `API_SERVER_KEY`**:插件侧写进 `HERMES_GROUP_ENDPOINTS[...].key`,
Hermes 侧既是它的 `API_SERVER_KEY` 也是它的 MCP token。轮换一次改两处、覆盖两个方向。

`hermes profile create` 还会在 `~/.local/bin/<name>` 生成一个 wrapper(内容是
`exec hermes -p <name> "$@"`),于是:

- **profile 名会变成一个 shell 命令。** 保留名只有 `hermes` / `test` / `tmp` / `root` / `sudo`,
  像 `web`、`top`、`docker` 这种照样能建,并且会在 PATH 里抢在原命令前面 —— 起名前先
  `command -v <name>` 看一眼。
- 之后该 profile 的 hermes 子命令可以直接 `team-a config set …` / `team-a mcp add …`,不必写
  `HERMES_HOME=…`。但 `hermes-install-skill` 是**本插件**的独立 CLI,不走这个 wrapper,仍要带
  `HERMES_HOME=`。

> [!WARNING]
> **多路复用下必须给命名 profile 自己的 LLM provider key** —— 就是大模型厂商那把 API key
> (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `NOUS_API_KEY` /
> `GEMINI_API_KEY` 之类),没有它 agent 连一次推理都发不出去。注意它与本节另外两把 key 是三件
> 不同的东西:
>
> | 这把 key | 谁验它 | 放哪 |
> |---|---|---|
> | LLM provider key(如 `ANTHROPIC_API_KEY`) | 大模型厂商 | `profiles/<name>/.env` |
> | `API_SERVER_KEY` | Hermes 自己的 api_server 入站鉴权 | `profiles/<name>/.env` |
> | 插件的 `HERMES_API_KEY` / 条目 `key` | 同上,是插件出向呈上的那一把 | bot 的 `.env` |
>
> `hermes profile create` 结尾会提示"否则会继承你 shell 环境里的 key" —— 那只在单 profile 部署
> 成立。多路复用打开后,凭证读取以 profile 的 secret scope 为权威且**不回落 `os.environ`**
> (全局豁免表里只有 PATH / HOME / `API_SERVER_HOST|PORT|ENABLED` 这类部署项,没有任何 API key),
> 所以 `.env` 空着的 profile 里 agent 一次都跑不起来。跑 `<name> setup`,或把 key 直接写进
> `profiles/<name>/.env`。**同一条规则适用于该 profile 用到的所有凭证**,不止 LLM ——
> 搜索(`EXA_API_KEY` 等)、图片生成、memory provider 的 key 也都要在它自己的 `.env` 里。

---

## 反向通道自动跟着收敛

反向通道(`push_message` / `get_recent_messages` / `get_message_images` / `list_active_sessions`)
**没有第二张 token 表**:调用方呈上哪个接入点的 key,就只能操作该接入点名下的群;呈上全局
`HERMES_API_KEY` 则只能操作**补集**(不在路由表里、或条目没有自己 key 的那些群);两者都不是就 401。
不配路由表时补集 = 全部群,行为与 0.5.0 完全一致。

也就是说:**想被保护的群必须进路由表并指向一个命名 profile**。留在补集里的群,补集那把 key 的持有者
(默认 profile)照样能读能推。

> [!IMPORTANT]
> **多路复用下,"哪个 profile 有反向通道"可以按 profile 控;"它呈哪把 token"不行。** 上游把这件事
> 分成两层:
>
> | 层 | 读谁的 config | 时机 |
> |---|---|---|
> | **连接**(进程里有没有这个 MCP client) | **默认 profile** 的 `config.yaml` | gateway 启动一次,注册表全进程共享 |
> | **可用性**(agent 拿不拿到这些工具) | **被路由到的那个 profile** 的 `config.yaml` | 每请求读 |
>
> 所以多路复用下:
>
> - **Bearer 必须配在默认 profile 上**。命名 profile 里 `hermes mcp add` 写的 `url` / `headers`
>   不会生效 —— 同名 server 全进程共用默认 profile 建的那一个连接。
> - 反过来,**要不要给某个 profile 反向通道是它自己说了算**:它的 `platform_toolsets.api_server`
>   列出该 server 名 = 打开;放特殊哨兵 `no_mcp` = 该 profile 完全没有 MCP 工具;两者都不写则它的
>   MCP 名单为空,同样拿不到。这一层每请求读、改完不用重启。
> - 照最直觉的配法(默认 profile 一个 `nonebot` server),**scope 不随 profile 变**:插件看到的永远
>   是那把共享 token,通常就是全局 `HERMES_API_KEY`(scope = 补集),于是进了路由表的群谁都推不进去
>   —— 会被拒并留 WARNING(fail-closed,但等于那些群没有反向通道)。
>
> **想在多路复用下让 token 也按接入点分开,可以做到** —— MCP 工具名按 server 名 namespace
> (`mcp__<server>__<tool>`),所以同一个 URL 可以用不同名字连多次。就是上文「完整示例」里
> `nonebot-default` / `nonebot-team-a` / `nonebot-lab` 那样:默认 profile 里每个接入点一个
> **同 URL、不同名字、不同 Bearer** 的 server,命名 profile 只声明属于自己的那个名字。
>
> **默认 profile 自己也要显式 allowlist**(`platform_toolsets.api_server: [<原工具集>, nonebot-default]`),
> 否则它会拿到全部 server 名、也就拿到了操作别人群的能力。
>
> 三个代价:**默认 profile 的 config.yaml 里握着全部接入点的 token**(所有连接都由它建,所以默认
> profile 必须可信 + 受限工具集,它的 agent 能读文件就能拿到全部 token);每个 server 名一条常驻
> 连接;名字两处必须一致,拼错就是那个 profile 静默没有工具。Bearer 若写成 `${MCP_*_API_KEY}`
> 引用形式,变量必须在**默认 profile 的 `.env`** 里 —— 插值发生在启动建连时的默认作用域下。
>
> 启动期 `multiplex_reverse_channel_notices()` 会对"路由表里有 `/p/<profile>` 形式的 url 且
> `HERMES_MCP_ENABLED=true`"这个组合打一条 **INFO** 级提醒,让你按上面这样配。它是 INFO 而非
> WARNING,因为插件无法从自己这侧核实对面配对没配对 —— 这条在正确配置上也必然触发,配成
> WARNING 只会制造告警疲劳。**配对了直接忽略即可**;真配错的失败信号在 push 那一刻:会有一条
> 精确的 `拒绝越权` WARNING(fail-closed),那才是要盯的。

被拒时 bot 侧会留一条 WARNING,写清调用方属于哪个接入点、它的范围、被拒的目标 —— 排查
"某个群的反向推送忽然不工作"时先看这条。

---

## 运维成本与已知限制

- 每个 profile 是一份完整的 `HERMES_HOME`:`hermes-repair-sessions` 要按 profile 分别跑,
  skill 升级要按 profile 分别装。
- **改动某个群的路由条目后要对该群 `/clear`**:session 血缘不带接入点维度,旧 session id 在新
  profile 里不存在,上游会静默开一段新会话,同名 session 分居两份 state.db。
- `/ping` 只探当前会话自己的接入点(它对普通用户开放,不能列别群的路由键);逐接入点体检在
  管理员命令 `/hermes-status` 里。
- 启动期的上游能力探测(`/v1/capabilities`)只探默认接入点,命名 profile 的 Hermes 版本偏旧不会告警。
- 启动日志会对路由表里"永远匹配不上的键 / 非 http(s) 地址 / 缺 key / key 过短 / 同一接入点多把 key"
  逐条 WARN。
- `session_search` 仍是另一条跨群通道:分了 profile 自然分开;不分 profile 又想堵,在该 profile 的
  `platform_toolsets.api_server` 里移除该工具。
