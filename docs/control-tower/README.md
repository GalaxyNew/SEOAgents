# SEO 总控大屏 V1 增强版：模块化开发契约

状态：已批准进入开发，生产部署尚未批准。

本文是 SEO 总控大屏 V1 增强版模块化改造的唯一入口文档。代码、工作流、数据库和测试必须遵守本目录的契约；若实现与文档冲突，先更新设计决策并完成评审，不得在前端临时补字段或编造兜底值。

## 1. 产品目标

1. 用户可见文字全部使用简体中文；GSC、GA4、PSI、URL、HTTP 等官方缩写可保留，首次出现时给出中文名称。
2. 按业务模块逐一完成开发和验收，不以一次大改替换现有 V1 增强版。
3. 每个数据模块拥有独立、可视化、可版本化的 YAML 工作流模板。
4. “今日巡检报告”只做聚合，不重复采集；它必须联动所有模块卡片及详情。
5. Timeline 保存周期计划；Hermes Cron/Pulse 是唯一可靠时钟。不得再启动 SEOAgents 内部调度器。
6. 卡片摘要只显示关键指标；放大详情显示趋势、维度、证据、分析、建议与执行轨迹。
7. 每次模块运行及其可比较指标写入历史数据库；大型原始响应和截图归档 Asset Hub。
8. GitHub 是版本管理和评审入口。生产发布必须来自已验证提交，不允许直接在运行目录热改后不回写源码。

## 2. 模块目录

| 模块 ID | 中文名称 | 数据来源 | 工作流模板 |
|---|---|---|---|
| `gsc` | Google 搜索表现 | Google Search Console Search Analytics API | `daily_gsc_performance` |
| `ga4` | 网站用户行为 | GA4 Data API（按 hostName 精确过滤） | `daily_ga4_behavior` |
| `psi` | 页面体验与性能 | PageSpeed Insights API；CrUX 单独标注 | `daily_psi_cwv` |
| `technical` | 技术 SEO | 同域 crawl、robots、sitemap、直接 HTTP 验证 | `daily_technical_seo` |
| `indexing` | 收录健康 | GSC URL Inspection、sitemap、线上 HTTP | `daily_indexing_health` |
| `content` | 内容健康 | CMS/数据库、sitemap、线上页面、内链检查 | `daily_content_health` |
| `execution` | 执行与调度 | WorkflowStore、TimelineStore、Hermes runtime/Cron | `daily_execution_health` |
| `aeo` | AI 搜索可见度 | 尚未配置真实探测器 | 暂不启用 |
| `inspection` | 今日巡检汇总 | 当日各模块已持久化结果 | `daily_inspection_aggregate` |

复合模块必须拆开：技术、收录和内容拥有独立状态；工作流和 Timeline 也应在详情中分别呈现。一个子模块不可用时，不得隐藏其他子模块的真实状态。

## 3. 数据铁律

每个模块结果必须携带：

- `module_id`
- `site_id`
- `business_date`
- `data_status`: `REAL | DEGRADED | UNAVAILABLE | DISPUTED`
- `source`
- `data_window`
- `reason`（非 REAL 时必填）
- `known_limitations`
- `cross_validation`
- `single_source_risk`
- `collected_at`
- `workflow_instance_id`
- `timeline_node_id`
- `asset_id`
- `schema_version`
- `metrics`
- `dimensions`
- `findings`

规则：

- 只有 `REAL` 可进入评分和业务结论。
- `DEGRADED` 仅展示，必须说明降级原因。
- `UNAVAILABLE` 原样展示，不补零、不拿旧数据顶替。
- `DISPUTED` 展示各方原值，不取平均、不自行选赢家。
- GSC、GA4、PSI 等来源分别确定 D0，不强制对齐。
- GSC 平均位置必须显示为“加权平均位置”，不能写成实测 SERP 排名。
- 前端只渲染服务端结果，不计算业务口径、阈值、状态或替代值。

详见 [模块数据合同](module-data-contract.md)。

## 4. 工作流与实例语义

- 每个模块只有一个当前工作流模板 ID；模板通过 `version` 版本化。
- 每个站点、模块、业务日期只有一个逻辑运行键：`site_id + module_id + business_date`。
- 当天重新执行记为同一逻辑运行下的新 `attempt_no`，不得在列表里堆出多个同名平级实例。
- 每次 attempt 仍保留独立工作流实例 ID、Hermes run ID、节点证据和时间戳，不能覆盖审计历史。
- 工作流实例创建后保持 `PENDING`；只有 Timeline 到点或用户明确启动后才写入 `start_authorized=true`。
- Hermes 进程 `completed` 只说明进程结束。只有节点验收、持久化和线上/资产回读符合要求，业务状态才能进入 `DONE`。

## 5. 调度语义

```text
Timeline 周期规则
  -> Timeline Pulse（Hermes Cron 唯一时钟）
  -> 创建/定位当天逻辑运行
  -> 显式授权工作流实例
  -> Hermes 执行节点
  -> 节点验收与结果持久化
  -> Timeline ACK
```

不得：

- 为每个模块额外创建独立的第二套调度器；
- 让 SEOAgents APScheduler 与 Hermes Cron 同时触发；
- 把“已排期”显示成“已执行”；
- 在同一站点同一天重复创建无关联实例。

## 6. 今日巡检联动

`inspection` 工作流等待当天所有必需模块进入终态后读取数据库，不再调用 GSC/GA4/PSI 等采集工具。它负责：

1. 汇总模块状态、数据日和阻塞原因；
2. 生成各模块门禁；
3. 归档报告到 Asset Hub 并取得 `asset_id`；
4. 创建飞书文档并回读验证；
5. 将巡检快照提供给大屏；
6. 在每个门禁和对应卡片间建立双向定位。

AEO 在真实探测器接入前状态为“未启用”，不进入完成率或总状态。

## 7. 数据库与资产边界

结构化历史写入独立 `control_tower.db`；工作流、Timeline 和资产数据库不混写。数据库包含：

- `module_runs`：逻辑运行及状态；
- `module_attempts`：每次实际执行；
- `metric_points`：可比较指标和维度；
- `module_findings`：问题、证据和建议；
- `inspection_runs`：每日汇总；
- `inspection_gates`：巡检与模块运行关联；
- `schema_migrations`：数据库版本。

原始 API 响应、截图和报告正文不塞入 SQLite；先 PUT Asset Hub，数据库仅保存 `asset_id`、摘要和内容哈希。

## 8. GitHub 开发与发布门禁

每一批功能遵循：

1. 从最新 `origin/main` 创建独立 `feat/*` 分支和 worktree；
2. 先更新契约与测试，再写实现；
3. 不混入原工作树已有未提交改动；
4. 不提交 `.env`、凭证、数据库、备份、构建产物；
5. 完成 Python 测试、前端类型检查、生产构建、敏感信息扫描和契约测试；
6. 每个可独立回滚的功能单独 commit，并立即推送 GitHub；
7. 未经明确批准，只能达到 `CODE_READY`/`INTEGRATED`，不得部署生产；
8. 部署后还需 API、页面、数据状态、站点隔离及线上回读验证，才可标 `LIVE_VERIFIED`。

状态术语：

- `CODE_READY`：模块代码和局部测试通过；
- `INTEGRATED`：跨模块测试、构建和安全门禁通过；
- `DEPLOYED`：已部署但尚未完成线上验收；
- `LIVE_VERIFIED`：线上 API/UI/数据与隔离均回读通过；
- `BUSINESS_COMPLETE`：资产、验收、报告和交付全部闭环。

## 9. 分阶段顺序

1. 基础数据合同、历史存储、公共只读模块 API；
2. Google 搜索表现（首个标准模块）；
3. 网站用户行为；
4. 页面体验与性能；
5. 技术 SEO；
6. 收录健康；
7. 内容健康；
8. 执行与调度；
9. 今日巡检总联动；
10. 获批并接入真实探测器后再做 AI 搜索可见度。

每个阶段必须满足 [验收门禁](acceptance-gates.md) 后才能进入下一阶段。
