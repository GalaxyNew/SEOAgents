# Changelog

## v0.6.0 — G1-F 前端迁移 dashboard-kit（22 号文标准落地）

G1 的最后一块缺口。此前 dashboard-kit 只存在于 21/22 号文的设计里，代码库中并不存在；SEOAgents 前端有 **1109 处硬编码色值**散落在 19 个文件中，"主题切换"实际只能改一个色相变量而底座会被一起染色。

### 新增：dojocore/dashboard-kit（标准件七件套之⑦）

联邦级前端标准件，新部门门户直接用它出壳：

- **`tokens.css`** — design token 单一事实源。三组分层（22 号文 §2.1）：底座组中性恒定且**禁止引用 `--hue`**（彩度 ≤0.014）、强调组由单变量 `--hue` 驱动、语义组全局恒定；明暗双套 L 阶梯；4px 间距网格、字阶、圆角、动效四件
- **`themes.js`** — 主题引擎。6 预设主题环（部门色映射）+ 任意自定义 hue + 明暗切换 + localStorage 持久化（全 try/catch，隐私模式/file:// 下静默降级）+ `storage` 事件跨页同步 + ECharts 黄金角 137.5° 同源着色
- **`components/`** — 七件组件：KpiCard / StatusDot / Timeline / TaskTable / InboxList / AssetCard / ChartShell，附状态胶囊统一语义与数据新鲜度徽标（REAL/MOCK/STALE/N-A）；含 `preview.html` 演示页
- **`layout/`** — 统一壳：顶栏 48px + 侧栏 + 部门门户三区骨架，满屏页各列独立滚动
- **`fonts/`** — Inter Variable + JetBrains Mono 本地分发（替掉 Google Fonts 外链），含 `size-adjust` 回退字体度量对齐
- **`audit.mjs`** — 发版门禁（22 号文 §六）六项检查，含自实现 OKLCH→sRGB→WCAG 对比度计算，零依赖

### 迁移

- 142 个唯一 hex + 39 种 rgba 按 HSL 明度阶梯映射到 token，**覆盖率 100%**；保留原视觉外观（用户纪律：换技术不重做视觉）
- 旧 token 名（`--ink`/`--acc`/`--panel-2`/`--line`）统一收敛到 kit 标准名
- 主题控件接入 kit：6 色板 + hue 滑杆 + 明暗切换，替代原先只有滑杆的实现

### 修复

- **全站白屏（既有缺陷，非本次引入）** — 15 处直接对 API 响应字段调用数组方法（`modelOptions?.providers.find()`、`summary.skills.filter()` 等），后端返回缺字段时抛 `Cannot read properties of undefined`，React 整棵树崩溃。**该崩溃在迁移前的 main 产物上同样可复现**。现全部加 `|| []` 兜底，实测所有 API 返回 `{}` 的最恶劣情况下页面仍正常渲染、零报错
- **ChartShell 图表不可见** — `flex:1` 被 `min-height` 压塌，且 `dk-grow` 用 scaleX 使纵向柱子归零；新增 `dk-grow-y`
- **TaskTable 表体溢出遮挡下方面板** — flex column 子项默认 `flex-shrink:1` 把面板压成 min-content，表格自然高度溢出到相邻区块之上
- **CLS 0.589 → 0** — 异步注入容器无预留高度导致数据到达时下推整页；入场动画改用 `transform`（不参与布局）替代 `translate` 属性；回退字体度量对齐消除换字重排

### 性能

路由级懒加载 + chunk 拆分（recharts / react-grid-layout / React 运行时 / 杂项各自独立），Copilot 抽屉延到 `requestIdleCallback` 后挂载，字体 preload 由构建期插件按 hash 注入：

| 指标 | 迁移前 | 迁移后 |
|---|---|---|
| 入口 JS (gzip) | 82.5 KB | **14.2 KB** |
| audit 首屏口径 (gzip) | — | **19.7 KB**（红线 200） |
| 首屏未使用 JS | 692 KB | 76 KB |
| CLS | 0.589 | **0** |
| TBT | — | **0 ms** |

### 验收

- **audit.mjs 6/6 PASS** — 硬编码色值 0 处；底座 hue 隔离；对比度 6 主题 × 明暗 48 项配对全达标；字体白名单；入口 19.7KB / 总量 287.6KB gzip；reduced-motion 全局覆盖
- **浏览器实测 6 主题 × 明暗 = 12 组**，逐组 DOM 校验：底座值恒定 2 种、强调色 12 种互异、七件套（KPI 4 / 时间线 4 / 表格 5 行 / 收发件 3 / 资产 3）每组完整可见无遮挡、刷新持久化生效；12 张截图留证
- **Lighthouse Performance**：模拟慢速 4G + 4×CPU 降速 **87**（CLS 0 / TBT 0 满分，三次复跑稳定）；真实宽带 `--throttling-method=provided` **100**。实测网络请求全部在 403ms 内完成、主线程 0.4s；剩余差距来自 React 19 生产版运行时 190KB 的框架下限

---

## v0.5.1 — G1-I2 任务卡接入联邦契约

PR #16。G1-I 建成账本、G1-J 挂上工作流，但任务卡对联邦一直是隐形的——指挥中心聚合出的是「跨部门协作」视图，不是「部门在干什么」的全貌。

### 新增
- **healthz 子系统探针补 `taskcard`** — 只数在办卡不拉证据链（15 秒一轮，探针要轻）；账本不可用记 `degraded` 而非 `fail`（丢台账仍能干活，丢 collab 才是联邦失联）
- **`inbox/summary` 增加 `taskcards` 计数** — total/active/stalled/blocked/review/audit_flagged，与既有 collab 口径并列互不干扰
- **`GET /api/v1/taskcards/federation`** — 指挥中心聚合专用精简投影，不返回 evidence/meta/goal；审计状态给布尔而非清单

### 修复
- **`inbox/summary` 邻居故障连坐** — 原本 collab 抛异常就整体早退，任务卡数据健在也一起消失（「联邦看不见台账」换形式重现）。改为两个数据源各自独立降级，collab 挂着时台账仍返回 REAL。由端到端实测暴露，已补回归测试

### 测试覆盖
本次是 `/api/v1/inbox/summary` 的**首个测试覆盖**，此前该端点在生产运行但无任何测试。

### 验收
- `pytest tests/test_taskcard_federation_contract.py` → **18/18 通过**
- `pytest tests/` → **259 passed**（G1-J 后基线 241，零回归）
- 真实 HTTP 端到端：healthz 含 `taskcard ok:3`、summary 台账计数与实际一致、federation 投影字段精简且路由未被 `/{card_id}` 通配吃掉

---

## v0.5.0 — G1-J 工作流 ↔ 任务卡自动挂钩

PR #14。终结「工序与台账两张皮」：工作流跑工序、任务卡记台账，此前互不知情。

### 诊断修正
21 号文 §2.3 称工作流引擎需补三件，实测后确认**两件已实装**（暂停恢复 `workflow_api.py:833/853`、人审卡点 `HUMAN_GATE` + `engine.py:189` 禁自审），真缺口只有第三件。

### 新增
- **`dojocore/taskcard/workflow_bridge.py`** — 观察者式桥接
  - `on_start` 工作流启动自动开卡（或挂母卡），回填 `WorkflowInstance.parent_task`
  - `on_node_done` 节点完成写证据行，记名=节点执行者；input/output 控制节点不写
  - `on_node_failed` / `on_human_gate` 卡进 BLOCKED 并说明卡点
  - `on_finish` 完成→REVIEW，失败/取消→BLOCKED
  - `reconcile` 报告实例与卡的状态分歧，供巡检抓漏事件漂移

### 两条铁律（各有测试守护）
- **桥接绝不自动 PASSED** — 自动化只能报告，验收必须他人签发，双验收位不可被工作流绕过
- **桥接故障不得中断工作流** — 所有方法自吞异常；账本不可达时工序照跑完

### 验收
- `pytest tests/test_taskcard_workflow_bridge.py` → **24/24 通过**
- `pytest tests/` → **241 passed**（G1-I 后基线 217，零回归）

---

## v0.4.0 — G1-I 任务卡引擎（联邦任务系统核心）

PR #11。替代 2026-08-12 废除的 Mac frontmatter markdown 任务账本，终结「无任务系统真空期」；G2/G4 的前置件。

### 新增
- **G1-I taskcard 引擎**：`dojocore/taskcard/`（1140 行）
  - `models.py` — TaskCard 数据模型 + 8 状态机 + 合法迁移图 + `audit_flags()` 假完成扫描
  - `store.py` — SQLite 持久化，部门×日期自动分配卡号（TSEO20260814-01）
  - `service.py` — 开卡/指派/流转/证据行/**真跑 verify_cmd**/双验收位门禁
  - `api.py` — 11 个 REST 路由挂 `/api/v1/taskcards`
- **三条硬门禁**（对旧账本三类失效的修复）
  - 状态漂移 → 状态只能经 `transition()` 变更，非法边被拒；每次变更强制记名证据行
  - 口头验收 → `verify()` 真跑子进程，exit code 入证据链；`approve()` 要求成功验证记录
  - 自审 → `reviewed_by ≠ owner`；L3+ 额外要求 `reviewer_provider ≠ owner_provider`
- **假完成扫描**：`GET /api/v1/taskcards/audit` 直接查出 PASSED 但无验证记录/无验收人/自审/同源评审/缺验收标准/在办无 owner

### 修复
- **三处 SQLite 文件描述符泄漏**（taskcard/timeline/collab store）
  - `sqlite3.Connection.__exit__` 只提交不关闭，每次查询泄漏一个 fd
  - 几百次操作后报 `unable to open database file`，表象像库损坏实则 fd 耗尽
  - timeline 与 collab 正在生产运行，同样受影响，一并改为 contextmanager

### 验收
- `pytest tests/test_taskcard_engine.py` → **40/40 通过**
- `pytest tests/` → **217 passed**（基线 177，零回归；既存 3 failed + 5 errors 经 git stash 对照确认与本改动无关）
- 真实 HTTP 端到端：11 路由挂载，完整生命周期走通，三条门禁均返回 400 拦截，假完成诱饵卡被审计抓出

---

## v0.3.0 — G1 数据层 + 巡检分子化 + 联邦节点标准端点

PR #9 合并到 main（2026-08-12T17:46:40Z）。

### 新增
- **G1-A 数据层**：`snapshot_store.py`（523 行）— 4 张新表 DDL + 读写层
  - seo_daily_snapshot（每日快照，UNIQUE date+site+task_name 去重）
  - keyword_pool（关键词池，产线查表不调 API）
  - backlink_history（外链历史）
  - cwv_history（Core Web Vitals 明细）
- **G1-B 巡检分子化**：`seo_tasks.py`（568 行）+ `seo_tasks_api.py`（107 行）
  - 10 个独立工序：tech_crawl/cwv_measure/dead_link_scan/dead_link_fix/index_status/gsc_performance/serp_track/trend_rising/aeo_probe/m_t_score
  - 每工序独立 curl 触发，写入 snapshot，支持同日去重
- **联邦节点标准三端点**：`dojocore/federation_api.py`（238 行）
  - GET /healthz（健康灯 + 能力计数 + 子系统状态）
  - GET /api/v1/inbox/summary（收发件箱摘要，data_status=REAL）
  - GET /api/v1/timeline?limit=N（时间线事件）
  - GET /api/v1/capabilities（能力目录）
  - 指挥中心轮询契约统一，指挥中心只读聚合不持有状态

### 删除
- `seonaut_service.py`（185 行静态假数据 HTML 仪表盘，全项目零调用）

### 安全
- `.gitignore` 补 credentials/ + *-sa.json 防凭据泄露（合并前审计发现）

### 验收
- SnapshotStore 7/7 测试通过
- 10 工序 API + 同日去重实测
- 联邦三端点公网 200 + data_status=REAL + 真实 GSC 事件
- hermes-mac.775767.xyz 公网 200
## v0.2.0 — 数据诚信、MCP 出站、工具目录

上一版有 7 条路径会在数据拿不到时**静默产出看起来正常的数字**。本版把这些
路径全部改成显式失败,并加了三道闸让新代码无法再引入同类问题。

### 数据诚信契约(新增)

`seoagents/quality.py` — 四态 `data_status` 信封:

| 状态 | 含义 | 允许的下游用途 |
|---|---|---|
| `REAL` | 真实数据源采集成功 | 全部 |
| `DEGRADED` | 真实但有已知缺陷 | 可展示(带角标);**不得进 M_t** |
| `UNAVAILABLE` | 拿不到 | 只能展示空态,**不得补零** |
| `DISPUTED` | 多 provider 分歧超容差 | 只能展示分歧;不得取平均或自选赢家 |

三道闸:

1. **工具层** — `ToolExecutor` 校验每个返回值,缺 `data_status` 直接判失败。
   集中校验意味着新加的工具无法靠"忘了写"绕过契约。
2. **评分层** — `compute_m_t(sources=...)` 在任一输入非 `REAL` 时返回
   `m_t=None, status="PARTIAL"` 并列出被排除的输入。
3. **资产层** — 血缘完整性(Asset Hub 侧,见方案 03 号文)。

### 移除的伪造路径

| 位置 | 原行为 |
|---|---|
| `dashboard/routers/gsc_api.py` | GSC 返回空时用 `random.Random()` 生成 9 个西语关键词及点击/展现/排名,UI 无法与真实行区分 |
| `dashboard/routers/gsc_api.py` | KPI 同比是按时间范围写死的字面量("+1200%"、"↓ 71%"),与数据无关 |
| `tools/aeo_monitor.py` | AI 可见度 = `sha256(engine+brand+query)` + 每天 +0.005 的人造上涨 |
| `tools/serp_tracker.py` | 端点不可达时用 `sha256(keyword)` 映射出 1..20 的名次 |
| `tools/site_auditor.py` | 站点不在白名单时静默改审内置演示快照(内含刻意植入的死链) |
| `tools/indexing.py` | 写完本地 nginx 片段即调 `mark_dead_link_fixed()`,看板显示"0 条未修复" |
| `sandbox/seo_audit_sandbox.py` | 无 Node 时用 `sha256(url)` 生成 62-95 的性能分 |
| `tools/seo_trends.py` | GSC/Trends 失败时回落哈希构造的数据集 |

### 语义修正

- **C_t 改为增量**。公式文档写的是 click *delta*,实现传的是 `sum()` 总量,
  于是 `should_compile_skill(m_t)` 实际在问"这个站流量大不大"而不是
  "这轮整改有没有效"。无对照窗口时 M_t 标 PARTIAL。
- **`index_ratio` → `crawl_success_ratio`**。原值是爬取成功率,不是收录覆盖率;
  真正的 `index_coverage_ratio` 来自 GSC,拿不到时为 `None`。
- **301 三态**:`PROPOSED`(已生成配置)→ `DEPLOYED` → `VERIFIED`。
  新增 `verify_301_live` 实测 301 响应,**只有它能清除死链状态**。
- **`submit_indexing`** 返回值不再含 "submitted" 字样(下游字符串判断会误读成功)。
- **`trend_weight`** 不再由 `sha256(keyword)` 决定,未实测时返回中性 1.0。
- SERP **"测到了但没排上"** 与 **"没测到"** 严格区分:前者才允许被评分惩罚。
  解析失败返回空列表曾被上游读成"没排上"→ 名次记 100,一次 Google 前端改版
  会被记录成排名暴跌。

### 新增能力

- **`seoagents/mcp_server.py`** — 把 `ToolRegistry` 全量暴露为 MCP tools。
  `get_schema()` 本就是标准 function-calling schema,转换只是字段改名。
  新增工具时本文件零改动。失败显式抛出,不返回可信外观的降级内容。
- **`seoagents/plugins/`** — 能力枚举 + 工具目录。目录含手册点名的全部 12 款,
  **未安装的也在**:7 款可用 / 2 款未采用 / 3 款查无此项(`rankwise`、
  `claude_seo`、`searchstack_aeo` 多轮检索无命中,保留条目是为了让"文档宣称
  拥有但实际不存在"这件事保持可见)。
  四种部署模式(`hosted_saas` / `remote_http` / `local_pip` / `local_docker`),
  远程与托管模式本机开销为 0。
- **`/api/catalog`、`/api/catalog/{id}`、`/api/capabilities`、
  `/api/resources/estimate`** — 未安装工具的详情页照样可用(项目主页、能做什么、
  许可与热度、部署方式、资源估算、已知坑),资源估算让部署模式的取舍在界面上
  就能算清楚,而不是事后 OOM 才发现。

### 已知部署陷阱(记录在目录条目里)

- SEOnaut 官方镜像在 **GHCR**(`ghcr.io/stjudewashere/seonaut`),不在 Docker Hub
- SEOnaut 环境变量是 `SEONAUT_DATABASE_*`,不是 `SEONAUT_DB_*`
- OpenSERP 默认端口 **7000**(手册写的 7070 是错的),浏览器渲染需 `shm_size: 1gb`
- `egebese/dataseo-mcp` 抓的是 **Ahrefs 免费页**,不是 DataForSEO

### 测试

56 个单元测试 + 12 项 selfcheck 全绿。核心用例是**断源无分数**:
无凭证时流水线跑完但 `m_t is None`、不写历史库、不固化技能、AEO 不补零。
