# SEOAgents 工具手册(hm 专用)

> 本手册的每一条状态都来自 **2026-08-02 的实调**,不是抄文档。
> 标注「✅ 实测可用」的,是真的调通并拿到 REAL 数据;标注「❌」的,是真的调了但拿不到。
> 工具行为会变(封禁、配额、凭证过期),**结论存疑时用 `system_ops(action=status)` 或直接试调一次,不要凭本手册想当然**。

---

## 〇、最高优先级的三条纪律

1. **查任何地域相关数据,必须显式传 `location_name` 与 `language_code`。**
   DataForSEO 的 `location_name` 默认值是 `"United States"`。不传 = 查美国。
   我们要的是西班牙:`location_name: "Spain"`, `language_code: "es"`。
   这条最容易出错,且错了不报错 —— 你会拿到一份看起来正常、实际上是美国的数据。

2. **拿不到就说拿不到。** 工具返回 `data_status: UNAVAILABLE` 时,不要用估算、常识或旧印象填补。
   评分引擎有硬门禁:任一输入非 REAL,`M_t` 直接拒绝计算。这是设计,不是故障。

3. **DataForSEO 按次计费。** 批量调用前先想清楚要什么。
   `ai_optimization_llm_models` 这类 `cost: 0` 的可以随便调,SERP/Labs 类每次都花钱。

---

## 一、内置工具(9 个,已逐个实调)

### ✅ `site_technical_auditor` — 技术审计爬虫
- **什么时候用**:想知道站点有哪些技术问题、死链在哪。这是每轮诊断的起点。
- **参数**:`start_url`(缺省用配置站点)
- **返回**:`pages_crawled` / `issues` / `dead_links` / `issue_count`
- **实测**:REAL,26 页,17 个问题,1 条死链
- **注意**:只发现问题,不修。修死链要接 `gsc_indexing_ops`。

### ✅ `lighthouse_audit` — Core Web Vitals / 性能
- **什么时候用**:要 performance / SEO 评分、LCP、CLS。改版前后对比性能必用。
- **参数**:`target_url`
- **返回**:`performance_score` / `seo_score` / `largest_contentful_paint` / `cumulative_layout_shift`
- **实测**:REAL,performance 47,SEO 100,LCP 11.2s,CLS 0.016
- **注意**:单次约 **25-35 秒**,别在一轮里对几十个页面循环调。
  优先走 PageSpeed API(目前 key 未配),回落到容器内本地 Lighthouse 13.4.1。

### ✅ `google_seo_monitor` — GSC 真实流量
两个 action,都实测 REAL:
- `action: "query_gsc_performance"` — 点击/展示/排名。**唯一可信的自家流量来源**,数据来自 Google Search Console 官方 API。
- `action: "query_rising_keywords"` — 上升词(走 pytrends)。曾被 429 封,现已恢复,**用前留意是否又被封**。

### ✅ `gsc_indexing_ops` — 收录与重定向操作
- **什么时候用**:发现死链后做 301 提案、生成 sitemap、提交收录。
- **action**:`create_301_mapping` / `build_sitemap` / `submit_indexing` / `verify_301_live`
- **实测**:`build_sitemap` REAL
- **重要**:`create_301_mapping` **只是写提案,不会真的生效**。
  死链要等配置部署上线、`verify_301_live` 在真实主机上观测到 301,才算修复。
  汇报时必须说清「已提案 N 条」而不是「已修复 N 条」。

### ✅ `nlp_internal_linker` — 内链植入
- **什么时候用**:文章写完后往正文里植入指向其他页面的内链。
- **参数**(容易传错,注意):
  ```json
  {"source_html": "<p>...</p>",
   "target_pages": [{"url": "/blog/x", "anchor_candidates": ["关键词1","关键词2"]}],
   "max_links": 5}
  ```
  是 `target_pages` 不是 `targets`;每项要 `url` + `anchor_candidates`。
- **返回**:`optimized_html` / `injections` / `linked_links_injected`
- **实测**:REAL

### ✅ `system_ops` — 你的系统管理面板(hm 专用)
见下方第四节。

### ❌ `serp_rank_tracker` — 当前不可用
- **状态**:UNAVAILABLE。底层 openserp 全部 429/503,出口 IP 被 Google 风控。
- **替代方案**:改用 `mcp_dataforseo_serp_organic_live_advanced`(见下)。
- **别做的事**:不要因为它返回空就说「排名掉了」——那是采集失败,不是排名变化。

### ❌ `aeo_visibility_monitor` — 当前不可用
- **状态**:UNAVAILABLE,未配置任何 AI 引擎探针。
- **替代方案**:DataForSEO 的 `ai_opt_llm_ment_*` 系列(见下,参数结构较复杂)。

---

## 二、DataForSEO(89 个工具,前缀 `mcp_dataforseo_`)

托管 MCP,已挂载可用。**所有地域相关调用记得传 `location_name: "Spain"`。**

### 最常用的四个

| 工具 | 用途 | 实测 |
|---|---|---|
| `serp_organic_live_advanced` | **查关键词排名**,替代失效的 serp_rank_tracker | ✅ 已验证能锁西班牙 |
| `dataforseo_labs_google_keyword_ideas` | 拓关键词,找新机会 | 未单测 |
| `dataforseo_labs_google_ranked_keywords` | 查某域名已经排上的所有词(含竞品) | 未单测 |
| `dataforseo_labs_google_competitors_domain` | 找竞品域名 | 未单测 |

`serp_organic_live_advanced` 标准调用:
```json
{"keyword": "mejorsiptv", "location_name": "Spain",
 "language_code": "es", "depth": 20}
```
必填 `keyword` + `language_code`。返回 `items[]`,每项有 `rank_absolute` / `domain` / `type`,
找自家排名就筛 `domain == "mejorsiptv.shop"`。

### 全部类别一览

- **SERP 抓取**(2):`serp_organic_live_advanced`、`serp_locations`(查地域代码)
- **Labs 关键词研究**(5):keyword_ideas / keyword_overview / keyword_suggestions / keywords_for_site / related_keywords
- **Labs 排名竞品**(8):ranked_keywords / competitors_domain / domain_intersection / domain_rank_overview / historical_rank_overview / historical_serps 等
- **搜索量与趋势**(11):kw_data_google_trends_explore / google_ads_search_volume / dfs_trends_demography 等
- **AI 可见度 AEO**(11):ai_opt_llm_ment_search / _agg_metrics / _top_domains / _top_pages、ai_optimization_chat_gpt_scraper、ai_optimization_llm_response
- **外链**(20):backlinks_backlinks / _anchors / _bulk_* / _competitors 等,**这是目前能力矩阵里标红「未覆盖」的一块,可以补上**
- **站点审计**(3):on_page_instant_pages / on_page_content_parsing / on_page_lighthouse
- **内容分析**(2):content_analysis_search / content_analysis_summary
- **域名分析**(4):whois_overview / domain_technologies 等
- **商业数据**(10):business_listings、Amazon 相关
- **YouTube**(5)

### 参数踩坑记录(实测撞到的)
- `ai_optimization_llm_models` 必填 `llm_type`(如 `"chat_gpt"`),`cost: 0` 免费
- `ai_opt_llm_ment_agg_metrics` 的 `target` 要**数组**不是字符串,且整体结构是 union 类型 —— 调之前先看 schema
- MCP 有严格的参数类型校验,类型错了直接拒绝并告诉你期望什么类型 —— 报错信息很有用,照着改

---

## 三、按任务场景选工具(决策树)

**「站点现在健康吗?」**
→ `site_technical_auditor` 拿问题清单 → `lighthouse_audit` 拿性能分 → 有死链就 `gsc_indexing_ops(create_301_mapping)` 提案

**「我们的词排第几?」**
→ `mcp_dataforseo_serp_organic_live_advanced`,记得 `location_name: "Spain"`
→ 不要用 `serp_rank_tracker`(当前失效)

**「流量涨了还是跌了?」**
→ `google_seo_monitor(query_gsc_performance)` —— 这是唯一可信的自家流量口径

**「该做哪些新词?」**
→ `dataforseo_labs_google_keyword_ideas` 拓词
→ `dataforseo_labs_google_competitors_domain` 找竞品 → `dataforseo_labs_google_ranked_keywords` 看竞品排了什么词

**「文章写完了,怎么发?」**
→ `nlp_internal_linker` 植内链 → `gsc_indexing_ops(build_sitemap)` → `gsc_indexing_ops(submit_indexing)`

**「AI 搜索里有没有提到我们?」**
→ `mcp_dataforseo_ai_opt_llm_ment_*` 系列(内置的 `aeo_visibility_monitor` 当前不可用)

**「系统本身怎么样?」**
→ `system_ops(action=status)`

---

## 四、`system_ops` — 你管理整个系统的入口

| action | 用途 |
|---|---|
| `status` | 系统总览:provider、模型、站点、已注册工具、技能数、时间线待办 |
| `tools_list` / `skills_list` | 列出可用工具与已沉淀技能 |
| `config_get` / `config_set` | 读写配置,落盘并即时重载。**改配置属高影响动作,先说明改什么、为什么、影响面** |
| `timeline_agenda` / `timeline_schedule` / `timeline_ack` / `timeline_cancel` | 排布自己的时间线 |
| `memory_read` / `memory_write` | 读写你自己的记忆(与 seohm 共用同一份) |
| `dispatch` | 把活派给专员:`auditor`(技术审计/死链)、`writer`(内容/E-E-A-T)、`linker`(内链) |
| `run_pipeline` | 触发 Auditor→Writer→Linker 整改流水线 |
| `tool_guide` | 读本手册全文 |

---

## 五、当前系统的已知缺口(2026-08-02)

自进化流水线的 `M_t` 目前**算不出来**,8 个数据源里 4 个是 REAL:

| 数据源 | 状态 | 缺的原因 |
|---|---|---|
| site_audit / cwv / traffic / trends | ✅ REAL | — |
| serp | ❌ | openserp 被封,需切到 DataForSEO |
| aeo | ❌ | 无探针,需切到 DataForSEO |
| index_coverage | ❌ | GSC 未返回收录数据,待查 |
| traffic_delta | ❌ | 无上一窗口基线 —— **要先成功落库一次才有** |

被问到「自进化跑得怎么样」时,如实说明卡在这里,不要说「运行正常」。
