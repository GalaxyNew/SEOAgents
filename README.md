# SEOAgents

**自进化 SEO / AEO 智能体集群** — 基于 [DojoAgents](https://github.com/Alpha-Dojo/DojoAgents) 七层架构,按《DojoAgents-SEO 自适应智能体开发配置手册》实现的完整可运行项目。

传统单点 SEO 工具在这里被转换为:由 **Agent Loop (L3)** 调度、在 **Execution Sandbox (L4)** 中安全运行、由 **APScheduler (L2)** 驱动持续自进化的分布式智能体编辑集群。

```
┌─ L1 用户访问层   seoagents/dashboard/{static,web}   审计看板 · SERP 监控 · AEO 热力图
├─ L2 应用服务层   seoagents/dashboard/server.py      FastAPI API · cron 调度 · 飞书推送网关
├─ L3 智能体核心   seoagents/agent + multi_agent      UniversalAgentLoop · Auditor/Writer/Linker
├─ L4 工具执行层   seoagents/tools                    GSC/Trends · OpenSERP · 内链 · Lighthouse 沙箱 · MCP
├─ L5 能力层       seoagents/skills                   RuntimeSkillCompiler · E-E-A-T 规则 · Schema 模版
├─ L6 数据层       seoagents/quant                    Pandas 清洗 · M_t 评分引擎 · AEO V_t 模型
└─ L7 基础设施层   seoagents/config + storage         ConfigStore(agents.yaml) · SQLite · 原子文件存储
```

## 核心特性

**自主追踪 → 闭环更新 → 自进化**:每日凌晨 2 点(可配)自动执行
`seo_self_evolution_pipeline`:全站技术审计 → Lighthouse CWV → GSC 流量 → OpenSERP
排位 → Trends 飙升词 → AEO 品牌可见度 → 计算演化评分,发现死链自动生成 301
映射 + 重建 sitemap + 提交收录;当 `M_t` 超过阈值时,由 L5 技能编译器把本轮整改
trace **固化为免 LLM 的静态技能**,下次同类问题零 token 重放。

每日评分(L6,权重可配):

```
M_t = α·C_t + β·I_t + γ·Σᵢ (Wᵢ / Rᵢ,ₜ) − δ·E_t
      点击增量   收录率    趋势加权排位倒数      技术缺陷惩罚

V_t = Σₑ Sₑ·Mₑ    e ∈ {ChatGPT, Claude, Perplexity, GoogleAIO}
```

**无密钥可跑**:不配置任何 API Key 时自动降级为确定性 mock 模式(MockLLMProvider
播放固定策略、演示站点快照、确定性指标),整条流水线照常闭环 —— 先跑通,再逐个填入
真实密钥切换。

## 快速开始

```bash
# 1. 安装 (Python >= 3.11)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"            # 真实 API 模式再加: ".[google,trends,mcp]"

# 2. (可选) 生成配置模版并填入密钥;跳过此步 = mock 模式
seoagents config init                  # 写入 ~/.dojo/agents.yaml

# 3. 零依赖冒烟自检 (不需要 pytest)
python scripts/selfcheck.py

# 4. 启动看板  ->  http://127.0.0.1:8765
seoagents dashboard

# 5. 单次执行
seoagents evolve                       # 立即跑一轮自进化闭环
seoagents audit [URL]                  # 技术审计
seoagents agent "诊断首页收录问题" --role auditor --trace
seoagents pipeline                     # Auditor→Writer→Linker 内容整改流水线
seoagents skills list                  # 查看已固化技能
seoagents skills replay FixDeadLinkWithAutoIndexSkill   # 免 LLM 重放
```

外挂重型服务(OpenSERP 真实 SERP 抓取 + Seonaut 可视化审计):

```bash
docker compose -f docker-compose.seo.yml up -d
# openserp -> http://localhost:7000   seonaut -> http://localhost:9000
```

## 配置 (`~/.dojo/agents.yaml`)

完整模版见 [config/agents.example.yaml](config/agents.example.yaml)。要点:

| 段 | 作用 |
| --- | --- |
| `llm_providers` | anthropic / openai_compat(DeepSeek、GLM、本地端点);`api_key` 留空 = mock |
| `mcp_servers` | L4 MCP Registry,挂载 dataforseo-mcp 等外部数据源(`pip install 'seoagents[mcp]'`) |
| `seo_credentials` | GSC OAuth 路径、PageSpeed key、openserp/seonaut 端点 |
| `sites` | 目标站点、GSC property、品牌名、追踪关键词、内链页面库 |
| `scoring` | α/β/γ/δ 权重与技能固化阈值 `skill_compile_threshold` |
| `aeo.engine_shares` | AI 引擎市场占有率权重 Sₑ |
| `sandbox` | 网络主机白名单、执行超时(所有工具调用强制走 SandboxPolicy) |
| `gateway` | 飞书群机器人 webhook(留空 = dry-run 打印卡片) |
| `scheduler` | 每日进化任务时刻(UTC) |

支持 `${ENV_VAR}` 引用;密钥经 `ConfigStore.redacted()` 脱敏后才允许暴露给看板。

## HTTP API(看板同源)

```
GET  /api/metrics/summary        M_t 历史 / SERP 排位 / AEO 可见度 / 技能列表
GET  /api/metrics/deadlinks      未修复死链
POST /api/audit/run              {url?, max_pages?}      技术审计
POST /api/audit/lighthouse       {url?}                  CWV 审计
POST /api/agent/run              {task, role}            单智能体回路
POST /api/pipeline/content       {target_url?}           Auditor→Writer→Linker
POST /api/jobs/evolution/run                             手动触发进化流水线
GET  /api/skills · POST /api/skills/replay               技能管理
GET  /api/config                                         脱敏配置
```

交互式文档: `http://127.0.0.1:8765/docs`

## 测试

```bash
python scripts/selfcheck.py     # 依赖极简的端到端自检(推荐先跑)
pytest -q                       # 完整套件: 评分/内链/执行器/配置/技能/回路/流水线/API
```

## 对手册的关键勘误

实现过程中修复了手册源文档的以下问题,行为以本仓库为准:

1. **代码残缺**:`flat_data = []` / `summary_output = []` 等空赋值、`r["keys"][0]` 缺索引、两处缺 `import json`、`pd.Timestamp.now().sub(...)` 非法调用、飞书卡片 `elements` 为空 —— 均已补全修复。
2. **Docker 配置**:seonaut 官方镜像为 `stjudewashere/seonaut`(手册拼写多了 "re"),且必须搭配独立 MySQL 服务;OpenSERP 上游默认端口是 **7000** 而非 7070。
3. **调度器**:async 任务必须用 `AsyncIOScheduler`,手册的装饰器写法在 BackgroundScheduler 下无法执行协程。
4. **GSC API**:采用现行 `searchconsole v1` 发现文档(旧 `webmasters v3` 仍兼容查询)。
5. **example.com 为 RFC 2606 保留演示域**:配置未改时审计确定性演示快照,不产生外网流量。

## 项目结构

```
SEOAgents/
├── pyproject.toml               依赖锁 (uv 兼容; google/trends/mcp/semantic 为可选 extras)
├── docker-compose.seo.yml       openserp + seonaut + mysql 外挂服务群
├── docker/Dockerfile            应用容器 (含 Node.js/Chromium 供 Lighthouse)
├── config/agents.example.yaml   L7 配置模版
├── scripts/selfcheck.py         零依赖端到端自检
├── tests/                       pytest 套件 (8 个模块, 40+ 断言)
└── seoagents/
    ├── logging.py               统一 LOGGER (禁止裸 print/basicConfig)
    ├── cli.py                   seoagents 控制台入口
    ├── config/                  L7: 类型化 ConfigStore (env 展开/深合并/脱敏/portalocker)
    ├── storage/                 L7: AtomicJson(l)Store + SQLite 历史库 (审计/SERP/死链/AEO)
    ├── agent/                   L3: models / providers (Anthropic·OpenAI 兼容·Mock) / loop / runtime
    ├── planning/                L3: 每日优化计划模型
    ├── multi_agent/             L3: Auditor→Writer→Linker 编排器
    ├── tools/                   L4: 7 个内置 ToolSpec + ToolExecutor 金牌模式 + MCP 桥
    │   └── environments/sandbox L4: SandboxPolicy + Lighthouse 沙箱执行器
    ├── skills/                  L5: SkillManager + RuntimeSkillCompiler + 内置规则/模版
    ├── quant/                   L6: pandas 清洗 + M_t/V_t 评分引擎
    ├── cron/                    L2: AsyncIOScheduler + 自进化流水线
    ├── gateway/adapters/        L2: BaseGatewayAdapter + 飞书卡片通知器
    └── dashboard/               L1/L2: FastAPI server/routers/schemas/services
        ├── static/index.html    零构建自包含看板 (SVG 趋势图/AEO 热力/一键触发)
        └── web/                 React 19 + Vite 源码 (可选 npm run build)
```

## License

Apache-2.0(与上游 DojoAgents 一致)
