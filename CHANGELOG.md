# Changelog

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
