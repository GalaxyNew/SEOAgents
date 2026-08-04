# DEC-2026-08-05 · MemOS 试装结论:偏离原因查清了

> 接续 `DEC-2026-08-04-memory-layer.md`(D3)。那份把偏离原因记为「存疑」,
> 本份把它结掉。

---

## 一、结论先说

**14 号文记载的「智谱 embedding 限频」是误诊。**

实测智谱 embedding 端点(两个 base_url 都试):

```
HTTP 429  {"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}
```

**是欠费,不是限频。** HTTP 状态码确实是 429 —— 这几乎肯定就是当初误判的来源,
429 在绝大多数 API 里表示 rate limit。

这个误诊的代价很具体:「限频」意味着「等一等 / 加退避重试」,
而「欠费」意味着「充值或换供应商」。**大家在等一个永远不会过去的限流。**
偏离就这么固化了三个多月。

## 二、而且这个障碍本来就不该存在

MemOS 插件的 embedding **默认就是本地离线模型**(`Xenova/all-MiniLM-L6-v2`),
不需要任何 API key、不需要余额、不联网。README 原文:

> Multi-provider embedding — OpenAI-compatible, Gemini, Cohere, Voyage, Mistral,
> **or local offline (Xenova/all-MiniLM-L6-v2)**
> `MEMOS_EMBEDDING_PROVIDER` 默认值:`local`

也就是说:当初**配了一个不必要的外部 embedding**,它欠费了,然后据此放弃了
整个方案。门一直开着,只是没人试过不配。

## 三、09 号文的三条切换触发条件,实测全不成立

| 触发条件 | 实测 |
|---|---|
| `better-sqlite3` 编译失败 | ❌ **不成立** —— 12.11.1 编译通过,读写中文正常 |
| MemOS 稳定性不达标 | ❌ 未测过就放弃了,谈不上不达标 |
| Hub 模式跨机不稳 | ❌ 从未启用过 Hub |

**结论:当初没有任何一条正当理由切走。**`05`/`09` 号文选定 MemOS 的决策依然有效。

---

## 四、实装进展

### 已完成

- 前置条件全齐:Node 20.20.2 / gcc 11 / build-essential / 90G 可用
- `better-sqlite3@12.11.1` 编译并验证读写
- 插件 `@memtensor/memos-local-hermes-plugin@1.0.4` 已装(233 个包,~900MB)
- 软链已建:`hermes-agent/plugins/memory/memtensor`
- **Hermes 能加载 provider**:`load_memory_provider('memtensor')` → `name = memtensor` ✓
- Bridge 守护进程跑起来了,数据库 schema 初始化完成,Viewer 已启动

### 未完成(交接给下一次)

1. 🔴 **状态库落点不对** —— 现在在 `/root/.openharness/memos-state/memos-local/memos.db`,
   应在 `/data/hermes-seo/memos-state/`。`OPENCLAW_STATE_DIR` 设了但没生效,
   需要读 `src/config.ts` 里 stateDir 的实际推导逻辑。
   **这条不修就违反了 HERMES_HOME 隔离要求**(05 号文 §3.2 的核心约束)
2. `config.yaml` 尚未切到 `provider: memtensor`(仍是 `holographic`)
3. systemd / 开机自启未配
4. 技能进化与任务总结未做功能验证 —— 这两个能力才是选 MemOS 的理由,
   **没验证过就不能算实装完成**
5. 飞书 ↔ Cowork 对话同步未做

---

## 五、装的过程里三个坑(下一个人会踩)

### 5.1 `install.sh` 会污染默认 profile

脚本里写死 `CONFIG_FILE="$HOME/.hermes/config.yaml"`。我们的 Hermes 在
`/data/hermes-seo`,`$HOME` 是 `/root` —— 跑下去会往一个不存在的默认 profile
里写配置。**05 号文警告过这一点,是对的。** 所以全程手工装,没跑脚本。

### 5.2 `bridge.cts` 在 Node 20.20 上起不来

`npx tsx bridge.cts` 报 `request for 'uuid' is not in cache` ——
ESM 加载器接管了 `.cts`,里面的 `require` 撞上 Node 的同步加载限制。
适配器里有针对 Node ≥23 的绕过逻辑,但对 20.20 不生效。

**解法**:`tsc` 预编译成 CJS 再用 `node` 跑,并且
`dist-bridge/package.json` 必须写 `{"type":"commonjs"}` ——
否则会被父级的 `"type":"module"` 当成 ESM,报
`exports is not defined in ES module scope`。

启动脚本已固化在 `/data/hermes-seo/memos-start.sh`,注释里写明了原因。

### 5.3 README 的环境变量名和代码对不上

README 写 `MEMOS_STATE_DIR` / `MEMOS_EMBEDDING_PROVIDER` / `MEMOS_DAEMON_PORT`,
但 1.0.4 的源码里 `process.env.*` 实际只读:

```
OPENCLAW_STATE_DIR · OPENCLAW_CONFIG_PATH · MEMOS_BRIDGE_CONFIG
MEMOS_ARMS_* · TELEMETRY_ENABLED
```

第一次严格按 README 配完,端口用的是默认值、状态库跑到了别处。
**以代码为准,不是以 README 为准** —— 这条对所有第三方插件都适用。

---

## 六、给下一次的第一步

```bash
cd /data/hermes-seo/memos-plugin
grep -n "stateDir" src/config.ts | head
```

先搞清楚 stateDir 的实际推导链,再决定是设对环境变量还是走
`MEMOS_BRIDGE_CONFIG` 的 `stateDir` 字段(我已经在 JSON 里给了,但没生效,
说明它可能被 `$HOME` 推导覆盖了)。

状态库落点修好之后,才谈得上切 `config.yaml` 和验证技能进化。

---

# 追记(同日晚)· 状态库落点已修

## 七、落点为什么会跑偏 —— 完整推导链

`OPENCLAW_STATE_DIR` 设了没用,是因为**它从来就不管落点**。Node 侧只有一条链:

```
bridge.cts:299/365
  const stateDir = configOpts.stateDir ?? `${process.env.HOME}/.openharness/memos-state`
                          ↑
  parseConfig()  ——  只读 MEMOS_BRIDGE_CONFIG 这一个环境变量,别无他途
```

`OPENCLAW_STATE_DIR` 在 Node 侧的唯一用途是 `readPluginConfigFromFile()` 里找
`openclaw.json`;`MEMOS_STATE_DIR` 则只有 Python 侧的
`adapters/hermes/config.py::get_memos_state_dir()` 读。**两个都不是落点开关。**

真正的落点开关是 `adapters/hermes/config.py::get_bridge_config()`:
它把 `stateDir` 拼进 JSON,由 `daemon_manager.start_daemon()` 塞进
`MEMOS_BRIDGE_CONFIG` 传给 bridge。

而上一版 `memos-start.sh` 是**直接 `node dist-bridge/bridge.cjs --daemon`**,
绕过了整个 Python adapter → `MEMOS_BRIDGE_CONFIG` 为空 → `configOpts = {}`
→ 落到 fallback `$HOME/.openharness/memos-state`,`$HOME` 是 `/root`。

顺带,同一个绕过还让 `MEMOS_DAEMON_PORT` / `MEMOS_VIEWER_PORT` 一起失效 ——
端口是 adapter 以 `--port` / `--viewer-port` 命令行参数传的,直接跑 node
拿到的是代码默认值 18990 / 18899,而不是 env 里写的 18992 / 18901。
**一个绕过,三处失效,但都不报错。**

## 八、改法:让两条启动路径共用一套推导

不是给 `memos-start.sh` 手写一份 `MEMOS_BRIDGE_CONFIG` JSON —— 那就成了第三处
定义(交接文档 §8.9 那个坑已经踩过两次)。改成:

| 改动 | 说明 |
|---|---|
| `memos-start.sh` 重写 | 只是 `daemon_manager.ensure_daemon()` 的一层壳,与 Hermes 运行时同一条码路 |
| `dist-bridge/bridge.js` → `bridge.cjs` 软链 | `find_bridge_script()` 只对 `.js` 后缀走 `node`,`.cjs` 会被丢给 tsx(Node 20.20 上必炸) |
| `adapters/hermes/bridge_path.txt` | 记同一路径,没有 env 的场景兜底 |
| `hermes-seo.service` | 删掉三行 `Environment=MEMOS_*`,改 `EnvironmentFile=/opt/hermes-seo/memos.env`,与手工启动共用一份 |
| `memos.env` 重写 | 每个变量标注「谁读它」;四个没人读的 `SUMMARIZER_*` 注释掉并写明原因 |
| 以 `hermes` 用户启动 | gateway 是 `User=hermes`,root 起的 daemon 会把 `memos-state` 写成 root 拥有,之后 gateway 再也写不进去 |

## 九、装的过程里第四个坑:本地 embedding 静默降级

改完落点第一次冒烟就暴露了一个**上一轮不可能发现的问题**(上一轮从没 ingest 过):

```
Unable to add response to browser cache: EACCES: permission denied,
  mkdir '/data/hermes-seo/memos-plugin/node_modules/@huggingface/transformers/.cache'
[warn] Embedding failed for chunk=..., storing without vector
[debug] Stored chunk=... hasVec=false
```

`transformers.js` 3.8.1 的 `cacheDir` **写死在包里**
(`path.join(dirname__, '/.cache/')`,`src/env.js:96`),没有任何环境变量可以改。
`node_modules` 是 root 装的,daemon 以 hermes 跑 → 建不了缓存目录。

**危险的不是失败,是它失败得很安静**:只 `warn`,chunk 照存,
`hasVec=false`,检索悄悄退化成纯 FTS,`embeddings` 表恒 0 行。
选 MemOS 就是为了语义检索和技能沉淀,退成 FTS 等于白装,而且没人会收到通知。
这正是 16 号文 §9 `data_status` 契约要防的那种假阳性。

修法两条,缺一不可:

1. `.cache` 软链到 `/data/hermes-seo/memos-state/model-cache`(hermes 拥有)。
   放在 state 目录下还有个好处:23MB 模型不随 `npm install` 重装重下
2. `memos-start.sh` 加**可写性预检**,不可写就直接 `exit 1` 不启动 ——
   宁可起不来,也不要带病跑一个检索质量悄悄减半的记忆层

> ⚠️ `npm install` / 升级插件会删掉这个软链,重装后必须重做。预检会拦住。

## 十、实测结果

```
落点        /data/hermes-seo/memos-state/memos-local/memos.db   ✅
            (日志原文:Plugin ready. DB: ...,Embedding: local)
归属        hermes:docker,gateway 可写                          ✅
/root/.openharness  已挪为 .wrong-landing.20260805,启动后未复活  ✅
            (旧库全表 0 行,没有数据丢失)
端口        daemon 127.0.0.1:18992 · viewer 18901                ✅
向量        修缓存前 hasVec=false / embeddings 0 行
            修缓存后 hasVec=true  / embeddings 2 行              ✅
模型        23MB 落在 memos-state/model-cache/Xenova/...         ✅
检索        ingest → search 双会话命中,summary/ref/score 齐全    ✅
两条路径    手工启动与 systemd 环境下 adapter 推导出同一个 stateDir ✅
telemetry   默认是**开**的,已在 memos.env 关掉                   ✅
```

## 十一、剩下的(接着往下做)

1. `config.yaml` 切 `provider: memtensor`(现仍 `holographic`)—— 切完要重启
   gateway,新的 `EnvironmentFile` 也在那时生效
2. systemd / 开机自启:daemon 现在由 adapter 按需拉起,要不要独立 unit 待定
3. **技能进化与任务总结的功能验证** —— 这两个能力才是选 MemOS 的理由,没验证不算完成。
   注意 `summarizer` 目前**没有接线**:`get_bridge_config()` 只从 `openclaw.json`
   的 `plugins.entries.*.config` 取,环境变量那条路不存在。技能进化要 LLM,
   接线方式得先定
4. 飞书 ↔ Cowork 对话同步
5. `memory.775767.xyz` 现在反代的是 8765(dashboard),不是 viewer。
   要指向 18901 之前先解决鉴权 —— viewer 本地 curl 直接 200,没有门;
   现在是靠 ufw 只开 22/80/443 挡着(viewer 监听的是 `0.0.0.0:18901`,
   **不是** 127.0.0.1,防火墙是唯一防线)

---

# 再追记 · provider 已切换、summarizer 已接线、技能沉淀已验证

## 十二、config.yaml 切到 memtensor

`memory.provider: holographic → memtensor`,备份 `config.yaml.bak.20260805-memtensor`。
重启 gateway 前**先把手工起的 daemon 停掉**,好验真正要验的那条路:

```
load_memory_provider('memtensor') → is_available()=True → initialize()
INFO daemon_manager Starting daemon: node .../dist-bridge/bridge.js --daemon --port 18992 --viewer-port 18901
INFO plugins.memory.memtensor MemTensor bridge connected
```

adapter 自己把 daemon 拉起来了,落点仍是 `/data/hermes-seo/memos-state`,
`/root/.openharness` 没有复活。gateway 进程 env 里 `MEMOS_*` 七个变量全部来自
共用的 `memos.env`。

## 十三、summarizer 接线在 openclaw.json,不在环境变量

代码里**没有任何 `SUMMARIZER_*` 环境变量**。唯一入口是
`bridge.cts::readPluginConfigFromFile()`,它按序找
`OPENCLAW_CONFIG_PATH` → `$OPENCLAW_STATE_DIR/openclaw.json` →
`$stateDir/openclaw.json` → `$HOME/.openclaw/openclaw.json`,
取 `plugins.entries.*<含 memos>*.config`。

接线文件:`/data/hermes-seo/memos-state/openclaw.json`(daemon_manager 把
`OPENCLAW_STATE_DIR` 设成 stateDir,所以第 2、3 条候选指向同一个文件)。

**密钥没有落进 JSON**:`src/config.ts::resolveEnvVars` 支持 `${VAR}` 插值
(`/\$\{([A-Z_][A-Z0-9_]*)\}/g`),所以写 `"apiKey": "${MEMOS_SUMMARIZER_API_KEY}"`,
值留在 `memos.env`。接线前先 curl 验过凭证可用 —— 别接一个死凭证。

> 注意 `mergeRuntimeConfig` 是**浅合并**且文件侧优先。文件里只写 summarizer,
> 所以 `MEMOS_EMBEDDING_PROVIDER=local` 仍然生效(日志确认 `Embedding: local`)。

## 十四、三项能力实测

| 能力 | 结果 |
|---|---|
| chunk 摘要 | ✅ summary 与原文不同(如「GSC searchAnalytics延迟导致HTTP 200空rows排查」),LLM 真被调用 |
| 任务切分与总结 | ✅ 换会话触发收尾,标题「L3 资产备份与回滚门禁设计」由 LLM 生成 |
| **技能沉淀** | ✅ 生成 `l3-asset-backup-restore-gating` v1,194 行 SKILL.md + 4 条 eval(4/4 命中),落在 `memos-state/skills-store/` |

技能是 `installed=0` —— **提案态,没有自动安装**,这正是 02 号文 §5.3 要求的提案制。
`skillEvolution.autoInstall: false` 是显式配的,别改成 true。

> 任务收尾靠 `extractAgentPrefix()`:session key 按 `:` 切,取前三段作 agent 前缀。
> 同前缀换会话会 finalize 上一个任务。所以 session key 建议用
> `agent:场景:实例:会话` 这种四段式,否则整串当前缀,任务永远不收尾。

## 十五、🔴 技能沉淀没有接进实时链路

**这是本轮最重要的发现,不修的话 `skills` 表在日常运行中仍然会是 0 行。**

`SkillEvolver` 只在 `src/viewer/server.ts` 两处被接起来:

1. `server.ts:4912` —— viewer 的**批量 postprocess** 任务里
2. `server.ts:1361` —— `POST /api/task/{id}/retry-skill` **手动重试**

而实时链路是 `index.ts → IngestWorker → TaskProcessor`,
`worker.ts:57` 建了 TaskProcessor 却**从来没调用 `onTaskCompleted()` 注册回调**。
任务照常 finalize、照常出标题和总结,但没有任何东西监听完成事件。

本次是走 `retry-skill` 手动触发才生成出技能的。也就是说:
**14 号文记的「技能沉淀能力丢失」,即使装好 MemOS 也不会自动恢复**,
还需要显式接线。三个可选路线,得先拍板:

- 在 `IngestWorker` 里注册回调(改第三方代码,升级会丢)
- 让 Hermes adapter 在 `on_session_end` 后主动调 `retry-skill`(不改插件,但要经 viewer HTTP)
- 定时跑 viewer 的 postprocess(批量,延迟大但最不侵入)

## 十六、viewer 鉴权 —— 修正前一节的说法

上一节写「viewer 本地 curl 直接 200,没有门」**不准确**,更正:

- `GET /` 返回 200,但那只是页面外壳
- **所有 `/api/*` 未带会话 cookie 一律 401**,门是有的
- 但 `/api/auth/status` 当时返回 `{"needsSetup":true}` —— **口令从未设置**,
  任何能到 18901 的人都可以 `POST /api/auth/setup` 抢注。已设 24 位随机口令,
  写在 `/root/memos-viewer-password.txt`(600)

仍然不建议把 `memory.775767.xyz` 指过去:

- `hashPassword` 是 `sha256(pw + "memos-lite-salt-2026")` —— **全局固定盐、无 KDF**,
  与 dashboard 的 PBKDF2 十万轮 + 独立盐不是一个量级
- 口令最短只要 4 位
- viewer 监听 `0.0.0.0:18901`(不是 127.0.0.1),现在纯靠 ufw 只放行 22/80/443 挡着

要暴露的话,前面得再套一层(nginx basic auth 或复用 dashboard 的会话)。

---

# 三追记 · 入口选错了 —— 宿主 shim 一次解决三个「没接线」

## 十七、结论:问题不是三个 bug,是一个入口选择

今天先后发现三处「代码在但没接线」:`SkillEvolver`、`HubServer`、`connectToHub`。
数一下就清楚了:

```
bridge.cts : SkillEvolver 0 · HubServer 0 · connectToHub 0 · sharing 0
index.ts   : SkillEvolver(:381 接 onTaskCompleted) · HubServer(:2382) · connectToHub(×2)
```

`index.ts` 是包的 `main`。**联邦(Hub/Client)与技能进化整套都只在它里面接线**,
而 Hermes adapter 跑的是 `bridge.cts` 编译出的精简 daemon —— `dist-bridge/src/`
里连 `hub` 目录都没有。`client/` 之所以在,只因为 viewer 要读状态和按需跨端搜索,
**不是后台同步**。

所以不该在三个地方各打一个补丁,该换入口。

## 十八、宿主 shim

`index.ts` 是 OpenClaw 插件对象 `{id, name, kind:"memory", configSchema, register(api)}`,
`register` 只用到 **9 个** api 成员:

```
logger(38次) · registerTool(20) · config(4) · resolvePath(2) · on(2)
registerService(1) · registerMemoryCapability(1) · pluginConfig(1) · id(1)
```

补一层 `host-shim.ts` 就能让它脱离 OpenClaw 独立跑(`/data/hermes-seo/hubtest/`)。
不改任何第三方源码,升级不丢。启动器 `run-shim.sh`。

> 注意 `index.ts` 里 `stateDir = process.env.OPENCLAW_STATE_DIR || api.resolvePath("~/.openclaw")`
> —— 与 bridge 那条链**完全不同**:这条入口里 `OPENCLAW_STATE_DIR` 是真管落点的。

## 十九、装的过程里第五个坑:1.0.4 的 index.ts 从 npm 装出来根本加载不了

```
Error: ENOENT: no such file or directory,
  open '.../memos-plugin/skill/memos-memory-guide/SKILL.md'
  at src/skill/bundled-memory-guide.ts:9
```

`package.json` 的 `files` 是
`["index.ts","bridge.cts","src","adapters","prebuilds","install.sh",...]`
—— **没有 `skill/`**。而 `bundled-memory-guide.ts` 在**模块顶层、无 try/catch**
地 `readFileSync` 它。于是 npm 装出来的 1.0.4,`index.ts` 这条主入口一加载就炸。
bridge 入口不 import 它,所以这个缺陷一直没暴露 —— 也解释了为什么没人用主入口。

已用 `adapters/openharness/skills/memos-memory.md`(同一份指南的适配器副本)补齐
`skill/memos-memory-guide/SKILL.md`。**升级后要重做。**

## 二十、第六个坑:技能生成的 LLM 链第一跳默认指向宿主

```
[warn] SkillGenerator.step1 failed (openclaw/?), trying next fallback:
       Error: OpenClaw API not available. Ensure sharing.capabilities.hostCompletion is enabled.
```

`buildSkillConfigChain(ctx)` = `[skillEvolution.summarizer, summarizer, openclaw fallback]`。
第一跳解析成了 `openclaw`(宿主补全)。宿主不提供补全时,**技能评估已经通过、
名字和理由都生成了,却卡在 `skill_status=generating` 不再前进** —— 又是一次
「不报错、只停住」。

解法:在插件配置里**显式**给 `skillEvolution.summarizer`,别依赖回退。

## 二十一、实测:全链路自动跑通(独立库,没碰生产)

```
agent_end hook 捕获 → 摘要 → 任务切分 → 换会话自动收尾
  → SkillEvolver 自动触发(无人工 retry-skill)→ 4 步生成 → 落盘入库

[info] Session changed within agent: finalizing task=... from session=hm:seo:s2:a
[info] SkillEvolver: generating new skill "nginx-multi-domain-tls-sni-troubleshooting"
[info] SkillGenerator: Step 1/4 → 2/4 → 3/4 → 4/4
[info] Skill generated: v1 [active] score=8.6 evals=4 evalHits=4/4
       from task "Nginx 多域名证书与 SNI 排障"
```

228 行 SKILL.md + 4 条 eval,`installed=0` 提案态。
**这是「技能沉淀」第一次在实时链路里自动发生**,此前那次是手工调 retry-skill。

同一进程里 Hub 也自动起来了:`memos-local: hub started at http://127.0.0.1:19011`。

Hub 服务端此前已单独验过(见十五节之外的独立验证):
错误 teamToken 403 · 正确 → pending 不直发 token · 无 token 401 ·
admin 拉待批 → 批准 → 客户端换取 userToken(214 字符)→
`/hub/me` `/hub/memories` `/hub/skills` 全 200。带限流(60/分,搜索 30/分)
与离线检测(2 分钟无心跳)。

> 09 号文当年把「Hub 模式跨机不稳」列为切走 MemOS 的触发条件之一。
> 现在可以结掉:**Hub 能跑**。当年的判断没有依据,因为从没启用过。

## 二十二、复现时的两个操作坑

1. `agent_end` 的游标:**首次见到某会话时从最后一条 user 消息起算**
   (设计如此,避免重启后重灌历史)。一次性喂 8 条只会进最后一轮 ——
   重放必须按真实宿主那样**逐轮 fire、消息数组逐轮增长**。
2. 每步间隔给够。5 秒时摘要还在队列里,`TaskProcessor` 的 `processing` 守卫
   会把回调吞掉,前一个会话的 chunk 全部 `task_id IS NULL`。放到 25 秒才正常。

## 二十三、待定:要不要把生产切到这条入口

切的话要动的:
- Hermes adapter 的 `daemon_manager` 改为起 shim 而不是 bridge daemon
- 宿主配置要提供 `models.providers`(否则 `openclawAPI` 为空,链第一跳仍会失败)
- 端口:viewer = gatewayPort+10,hub = gatewayPort+11,得和现有 18901/18992 对齐
- `skill/memos-memory-guide/SKILL.md` 与 `dist/package.json` 两个本地修补要进
  安装说明,`npm install` 后必须重做

不切的话,技能沉淀和联邦这两件永远只能手工触发。
