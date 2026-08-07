# 第一阶段实施计划：基础层与 Google 搜索表现模块

## 范围

本阶段只实现：

1. 模块结果数据模型与校验；
2. 独立历史存储 `control_tower.db`；
3. GSC 工作流模板 `daily_gsc_performance@1.0`；
4. GSC 采集/标准化的确定性边界；
5. GSC 最新结果与历史只读 API；
6. 单元、集成与鉴权测试。

本阶段不包含：

- 生产部署；
- 生产数据库迁移；
- 新增 Cron；
- 修改当前 V1 增强版视觉布局；
- 调用 DataForSEO；
- AEO 探测；
- GA4、PSI、技术、收录、内容模块实现；
- 自动发布、外联或任何对外副作用。

## 代码所有权

| 文件/目录 | 作用 |
|---|---|
| `seoagents/control_tower/models.py` | 数据状态、运行、指标、发现的类型模型 |
| `seoagents/control_tower/store.py` | SQLite schema、迁移、幂等写入和查询 |
| `seoagents/control_tower/gsc.py` | GSC 结果标准化和确定性派生，不直接持有凭证 |
| `seoagents/dashboard/routers/control_tower_modules.py` | 认证范围内的模块只读 API |
| `seoagents/workflows/daily_gsc_performance.yaml` | 独立可视化工作流模板 |
| `tests/test_control_tower_store.py` | schema、幂等、重试、状态规则测试 |
| `tests/test_control_tower_gsc.py` | D0、窗口、缺失值、维度和状态测试 |
| `tests/test_control_tower_modules_api.py` | GET/HEAD/写方法/站点白名单/脱敏测试 |
| `tests/test_workflow_engine.py` | shipped GSC 模板加载与 DAG 测试 |

## GSC 工作流 DAG

```text
input
  -> preflight
  -> detect_d0
      -> collect_periods
      -> collect_dimensions
          -> normalize
          -> analyze
          -> persist
          -> archive
          -> verify_persisted
          -> output
```

其中 `collect_periods` 和 `collect_dimensions` 在锁定同一个 D0 后并行；`normalize` 必须等待两者完成。

### 节点定义

1. `input`：站点、GSC property、业务日期、Timeline 节点 ID。
2. `preflight`：验证站点白名单、GSC 凭证路径可用、工具存在；不输出凭证内容。
3. `detect_d0`：从 today-2 向前探测，锁定来源 D0。
4. `collect_periods`：D0、D-1、7/7、30/30 总量。
5. `collect_dimensions`：日、查询、页面、国家、设备。
6. `normalize`：统一字段、状态、窗口和单源风险；不得补零或生成模拟行。
7. `analyze`：只基于 REAL 数据生成确定性候选问题；无足够数据时输出“待验证”。
8. `persist`：写入逻辑运行、attempt、指标点和 findings。
9. `archive`：将原始证据先存 Asset Hub，写回 `asset_id`。
10. `verify_persisted`：通过只读命令/API 回读该逻辑运行和 asset_id。
11. `output`：结束并提供模块运行 ID。

## 兼容性要求

当前 `google_seo_monitor` 的公开 schema 仅声明 `query_gsc_performance` 和 `query_rising_keywords`。首阶段不得在 YAML 中引用不存在的 action。若需要完整窗口采集，应先：

1. 为工具增加独立的 `collect_gsc_module` action；
2. 在工具层完成 D0 与多个窗口采集；
3. 增加不触网的 fake client 单元测试；
4. 保持旧 action 行为兼容；
5. 禁止无凭证时进入 mock/demo 路径作为模块结果。

## Git 提交拆分

建议保持以下原子提交：

1. `docs: 定义总控大屏模块化开发契约`
2. `feat: 新增总控大屏模块历史存储`
3. `feat: 新增 Google 搜索表现模块工作流`
4. `feat: 新增 Google 搜索表现模块只读接口`
5. `test: 覆盖模块状态、幂等与鉴权门禁`

每个提交完成局部测试后立即推送当前功能分支。未获生产批准前不合并主分支、不部署。
