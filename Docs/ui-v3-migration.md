# SEOAgents Dashboard UI v3 正式迁移方案

> 版本：v1.0 · 2026-08-19 · 撰写：Hermes（总经理）
> 概念稿已确认：`gtmac/方案-Hermes联邦架构/preview/seoag-ui-v3-preview.html`（v2 侧导航+⌘K → v3 增 GA4+全模块抽屉）
> 落位：`SEOAgents/docs/ui-v3-migration.md`（本文件）；执行走 GitHub issue + 分阶段 PR

---

## 0. 一句话

把 dashboard 从「顶部 9 tab + 数据平铺」迁移到「侧导航 + 决策台首页 + ⌘K 命令面板 + 全模块详情抽屉 + GA4 数据层」，**面板业务逻辑零重写**，dashboard-kit token 体系原样保留。

## 1. 迁移原则（红线）

1. **换壳不换脏器**：14 个既有 Panel 组件（Metrics/GscOverview/Kanban/Timeline/Workflow/Capability/Storage/Department/KeywordPool/SeoAudit/Config…）内部逻辑不动，只改挂载方式与外层布局
2. **22 号文全量继承**：OKLCH 单变量主题、6 主题环、明暗模式、audit.mjs 六项门禁（硬编码色 0 / 入口 ≤200KB gz / AA 对比度 / reduced-motion）每个 PR 必须全绿
3. **URL 兼容**：现有 `#kanban` `#gsc_overview` 等 hash 路由继续可用（旧链接、飞书里发过的链接不能断）
4. **分阶段可回滚**：每阶段独立 PR，任何一阶段出问题 revert 单个 PR 即可，不影响其他阶段
5. **生产验收铁律**：每 PR 合并 → CN2 部署 → 公网实测 → 截图证据，四步缺一不算完成

## 2. 阶段划分（4 个 PR）

### Phase 1 — 布局壳：侧导航 + 顶栏（PR-A，改动最大但纯视觉）

**改什么**
- `App.tsx`（676 行）拆出三个新组件：
  - `layout/SideNav.tsx` — 216px 侧导航：logo、搜索入口、4 组导航（工作台/生产/协同/系统）、主题环+明暗+用户区（从现 App.tsx 顶栏迁入）
  - `layout/TopBar.tsx` — 50px 顶栏：面包屑+副标题、站点选择器（现有 site 切换逻辑迁入）、数据新鲜度、全局操作按钮
  - `layout/AppShell.tsx` — `grid-template-columns: 216px 1fr` 骨架 + 移动端（<768px 侧栏折叠为抽屉）
- tab 状态机不动：`activeTab` + `VALID_TABS` + hash 同步原样保留，只是渲染位置从顶部横排变成侧栏竖排
- 导航徽标数据：任务卡数 `/api/kanban/summary`、词池总数 `/api/keywords/pool?limit=1`（都是现成端点，挂载时拉一次）

**不做什么**：不动任何 Panel 内部；不动路由语义；不加新页面

**验收**：9 个 tab 全部可达且渲染同前 · 6 主题×明暗 12 组回归 · audit 6/6 · 移动端侧栏可折叠

### Phase 2 — 决策台首页 + 详情抽屉框架（PR-B，核心交付）

**改什么**
- 新 `components/OverviewPanel.tsx` 替换 dashboard tab 的默认内容（现 MetricsPanel+SeoAuditPanel 平铺）：
  - KPI 行 1（SEO）：健康分 M_t（现 summary.latest_m_t）、首页词数（serp_positions 计算）、词池总数、死链/告警数 —— **全部现有数据，零新后端**
  - 主网格：排名趋势（serp_positions 历史）、机会词/转化词（`/api/keywords/pool` 现成参数）、今日动态（timeline API 现成）、内容产线（workflow API 现成）
  - 快捷操作 chips
- 新 `components/DetailDrawer.tsx` 通用抽屉框架：
  - 470px 右滑 + scrim 遮罩 + Esc/点击关闭 + `prefers-reduced-motion` 降级为直接显隐
  - 内容插槽化：`<DetailDrawer id="ga4-users">` 按 id 懒加载对应明细组件（React.lazy，不进首屏）
  - 7d/28d/90d 时间段切换状态提供给插槽（context）
- 原 MetricsPanel/SeoAuditPanel 不删：移到抽屉「站点健康分」明细 + 独立入口保留

**验收**：首页一屏回答三问（状态/动态/下一步）· 8 个 SEO 模块点击有抽屉 · 抽屉内数据与模块一致 · CLS 0（抽屉懒加载预留尺寸）

### Phase 3 — ⌘K 命令面板（PR-C，独立无依赖，可与 Phase 2 并行）

**改什么**
- 新 `components/CommandPalette.tsx`：
  - 全局 ⌘K/Ctrl+K 唤起（挂 AppShell）
  - 三段结果：关键词（防抖 250ms 查 `/api/keywords/pool?q=`，显示量/KD/意图）、页面跳转（9 个 tab 模糊匹配）、操作（刷新排名/生成文章/GSC 同步——复用现有按钮的 handler）
  - 键盘导航（↑↓ 选择、↵ 执行、Esc 关）
- 「用 X 词生成文章」动作：调 workflow API 现有的创建入口，词名作为参数传入

**验收**：任意 tab 下 ⌘K 可用 · 查词结果与词池页一致 · 跳页动作正确 · 无焦点陷阱（Esc 后焦点还原）

### Phase 4 — GA4 数据层（PR-D，唯一需要新后端的阶段）

**后端**（参照 GSC 已验证模式，`seo_trends.py:193` service_account 三步曲）
- 依赖：`google-analytics-data`（官方 GA4 Data API Python 客户端）
- 新 `seoagents/tools/ga4_client.py`：service account 认证 + `runReport` 封装，指标集：activeUsers / sessions(按 channel) / engagementRate / keyEvents / landingPage 维度
- 新 `seoagents/dashboard/routers/ga4_api.py`：
  - `GET /api/ga4/overview?days=28` — KPI 行 2 的四个数字 + 迷你趋势
  - `GET /api/ga4/channels?days=28` — 渠道分布
  - `GET /api/ga4/pages?days=28` — 落地页明细
  - `GET /api/ga4/detail/{metric}?days=` — 抽屉明细（设备/地区/漏斗）
  - 全部带 15 分钟内存缓存（GA4 API 配额：每属性每小时 5 万 tokens，够用但不挥霍）
- 配置：`seo_credentials.ga4.property_id` + `service_account_path`（**复用 GSC 同一个 SA 文件**，只需在 GA4 后台把 SA 邮箱加为查看者）
- 降级：GA4 未配置/不可达 → 端点返回 `{available:false}`，前端 KPI 行 2 显示「GA4 未接入」空态卡，**不报错不白屏**（裸数组兜底纪律）

**前端**
- OverviewPanel 增 KPI 行 2 + 流量渠道 + 热门落地页模块（GA4 徽标）
- 4 个 GA4 抽屉明细组件（懒加载）
- 侧栏「流量分析」新 tab：完整 GA4 页（渠道趋势对比 + 全落地页表 + 漏斗）

**验收**：真实 GA4 数据上屏 · 未配置时优雅空态 · 缓存命中（连续刷新不打 API）· 底栏新鲜度含 GA4

## 3. 工作量与节奏

| 阶段 | 改动规模 | 预估 | 依赖 |
|---|---|---|---|
| PR-A 布局壳 | App.tsx 拆分 + 3 新组件，~600 行 | 1 天 | 无 |
| PR-B 决策台+抽屉 | 2 新组件 + 8 明细插槽，~800 行 | 1.5 天 | PR-A |
| PR-C ⌘K | 1 组件 ~300 行 | 0.5 天 | PR-A（可与 B 并行） |
| PR-D GA4 | 后端 2 文件 + 前端 5 组件，~900 行 | 1.5 天 | PR-B + **用户侧授权** |
| 总计 | | **4-5 天** | |

顺序：A → B/C 并行 → D。每阶段合并即部署即验收，全程站点可用（无 feature branch 长期漂移）。

## 4. 需要你（用户）提供的（只 Phase 4 要）

| # | 事项 | 怎么做 |
|---|---|---|
| 1 | GA4 Property ID | GA4 后台 → 管理 → 媒体资源设置，形如 `properties/123456789`；mejorsiptv.shop 与 igoriptv2.com 各一个（若都要） |
| 2 | 站点已装 GA4 跟踪码 | 若未装：把 G-XXXX gtag 片段加进站点 `<head>`（我可代做，需站点部署权限——igoriptv2 的 VPS 已有备份铁令流程） |
| 3 | SA 授权 | GA4 后台 → 管理 → 媒体资源访问管理 → 添加 `igoriptv2-gsc-reader@grounded-style-501621-k3.iam.gserviceaccount.com` 为「查看者」（复用 GSC 的 SA，零新密钥） |
| 4 | 转化事件定义 | 确认关键事件口径：WhatsApp 点击 / 试用表单 / 订阅按钮（需在 GA4 里标记为 key event；我出 gtag 事件代码，站侧埋点） |

Phase 1-3 零等待，确认方案即可开工。

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| App.tsx 拆分引入回归 | Phase 1 纯移动不改逻辑；12 组主题回归脚本（/tmp/dk_full.py 模式）跑全 |
| 抽屉懒加载 CLS | fallback 预留 min-height（G1-F 已验证的手法） |
| GA4 配额/延迟 | 15 分钟缓存 + 降级空态；GA4 数据天然延迟 24-48h，底栏如实标注 |
| GA4 未授权阻塞整体 | Phase 4 独立在最后，前 3 阶段不依赖；授权没到位就先上「未接入」空态 |
| 移动端侧导航适配 | <768px 折叠为汉堡抽屉（概念稿已含断点），Phase 1 内完成 |
| 入口体积超 200KB 门禁 | 抽屉明细/GA4 页全部 React.lazy 独立 chunk；audit.mjs 每 PR 把关 |

## 6. 验收总清单（终验用）

- [ ] 9 旧 tab 全可达，旧 hash 链接不断
- [ ] 首页 = 决策台：KPI 两行 + 主网格 + 右栏，一屏无滚动看全（1440×900）
- [ ] 14 个模块点击有详情抽屉，Esc/遮罩可关
- [ ] ⌘K：查词/跳页/操作三段可用
- [ ] GA4 四端点真实数据（或未配置空态）
- [ ] audit.mjs 6/6 · 6主题×明暗 12 组回归 · Lighthouse 真实宽带 ≥95
- [ ] CN2 生产部署 + 公网 200 + 截图
- [ ] CHANGELOG + 进度表更新

---
*方案确认后流程：建 GitHub issue（含本文链接）→ PR-A 开工。*
