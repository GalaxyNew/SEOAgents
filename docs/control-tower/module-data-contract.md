# 模块数据合同 v1

本合同约束采集器、历史存储、模块 API、卡片摘要、详情视图和今日巡检。任何一层不得私自创造第二套字段名。

## 1. 标准信封

```json
{
  "schema_version": "1.0",
  "module_id": "gsc",
  "site_id": "mejorsiptv.shop",
  "business_date": "2026-08-07",
  "data_status": "REAL",
  "source": "Google Search Console Search Analytics API",
  "data_window": {
    "d0": "2026-08-05",
    "d1": "2026-08-04",
    "timezone": "UTC"
  },
  "reason": null,
  "known_limitations": [
    "GSC 通常延迟 2–3 日",
    "查询维度可能受隐私阈值影响"
  ],
  "cross_validation": "单源，未经外部 SERP 交叉验证",
  "single_source_risk": true,
  "collected_at": "2026-08-07T12:00:00Z",
  "workflow_instance_id": "WF-...",
  "timeline_node_id": "TL-...",
  "asset_id": "asset_...",
  "metrics": {},
  "dimensions": {},
  "findings": []
}
```

## 2. 状态规则

- `REAL`：真实来源成功采集，可显示、对比、评分和生成结论。
- `DEGRADED`：来自真实来源但存在明确缺陷；`reason` 必填，只展示，不评分。
- `UNAVAILABLE`：没有可用数据；`reason` 必填，指标值必须为 `null` 或省略，不允许填 0。
- `DISPUTED`：多个来源超出容差；`reason` 和 `dimensions.disputes` 必填，不平均、不裁定。

### 零值与缺失值

真实 API 明确返回 0 时可保存 0，但必须有成功响应及窗口证据。请求失败、字段缺失、隐私阈值或权限不足一律保存 `null`，不得转换成 0。

## 3. 运行键与幂等

逻辑唯一键：

```text
(site_id, module_id, business_date)
```

每次实际重跑增加 `attempt_no`，并以以下键唯一：

```text
(module_run_id, attempt_no)
```

同一业务日重跑更新逻辑运行的“最新 attempt 指针”，但不删除旧 attempt。工作流 UI 默认聚合显示逻辑运行，详情可展开 attempts。

## 4. 指标点

所有可对比值使用统一结构：

```json
{
  "metric_key": "clicks",
  "metric_label": "自然搜索点击",
  "period_key": "d0",
  "window_start": "2026-08-05",
  "window_end": "2026-08-05",
  "value_num": 1,
  "value_text": null,
  "unit": "次",
  "dimensions": {},
  "data_status": "REAL"
}
```

规则：

- 数值和格式化字符串分离；数据库保存原始数值，前端负责中文格式化。
- 比例统一保存小数（如 `0.0526`），前端显示 `5.26%`。
- 时间统一 ISO 8601 UTC；业务窗口保留来源日期和来源时区。
- 维度使用 JSON 对象，但必须有明确键，如 `country=ESP`、`device=MOBILE`。

## 5. 发现与建议

```json
{
  "finding_key": "high_impression_low_ctr",
  "severity": "P1",
  "title": "高展示、低点击查询",
  "conclusion": "待验证",
  "evidence": {
    "metric_keys": ["impressions", "ctr", "position"],
    "asset_id": "asset_..."
  },
  "recommendation": "检查搜索意图与标题摘要是否匹配",
  "expected_benefit": "待验证，不能在没有实验数据时量化",
  "verification_method": "修改获批后观察 14/28 日同口径 CTR",
  "approval_required": true
}
```

不允许把相关性写成因果，不允许无依据量化收益。

## 6. GSC 模块字段

### `metrics.periods`

必须支持：

- `d0`
- `d1`
- `cur7`
- `prev7`
- `cur30`
- `prev30`

每个窗口包含：

- `clicks`
- `impressions`
- `ctr`
- `weighted_position`

缺失窗口为 `null`，不得改用更旧窗口。

### `dimensions`

- `daily`
- `queries`
- `pages`
- `countries`
- `devices`
- `opportunities`

每一维度行都必须携带该维度的真实来源窗口。查询行受 GSC 隐私阈值影响，不能要求其点击/展示加总等于站点总量。

### D0 规则

从采集时刻的 `today-2` 开始向前探测，找到最近一个成功且有完整响应的日期作为 D0。D-1 固定为 D0 前一日；若不可用，保持 `UNAVAILABLE`，不得改用 D0-2。

### GSC 单源标记

- `single_source_risk = true`
- `cross_validation = "单源，未经外部 SERP 交叉验证"`
- 加权平均位置不得命名为“排名”或“SERP 实测排名”。

## 7. 公共只读 API

基础路径：

```text
GET /api/public/seo-control-tower/v1/sites/{site_id}/modules/{module_id}
GET /api/public/seo-control-tower/v1/sites/{site_id}/modules/{module_id}/history
GET /api/public/seo-control-tower/v1/sites/{site_id}/inspection/today
```

要求：

- 仅允许 `GET`/`HEAD` 匿名访问；任何写方法继续要求登录。
- `site_id` 必须在配置白名单中，禁止把路径直接拼进文件系统或 SQL。
- 响应仅包含展示所需字段，不得返回凭证、内部绝对路径、完整 prompt、Cookie、服务令牌或原始敏感响应。
- 历史接口限制日期范围和最大行数。
- 尚未采集时返回合法的 `UNAVAILABLE` 信封，而不是 404、空对象或伪造数据。

## 8. 中文显示

后端继续保存稳定机器枚举；前端使用统一词典：

| 枚举 | 中文 |
|---|---|
| `REAL` | 真实数据 |
| `DEGRADED` | 降级数据 |
| `UNAVAILABLE` | 数据不可用 |
| `DISPUTED` | 数据分歧 |
| `PENDING` | 待执行 |
| `RUNNING` | 执行中 |
| `DONE` | 已完成 |
| `FAILED` | 执行失败 |
| `BLOCKED` | 已阻塞 |
| `D0` | 最新完整数据日（D0） |

不得直接把内部枚举当成主要用户界面文案。
