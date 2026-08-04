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
