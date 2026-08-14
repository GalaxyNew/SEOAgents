# Changelog

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
