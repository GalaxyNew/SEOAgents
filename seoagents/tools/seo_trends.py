"""GoogleSEOMonitorSpec (L4) — GSC performance + Google Trends rising keywords.

Legacy actions keep their existing behavior. ``collect_gsc_module`` is the strict
control-tower path: it never uses mock/demo data, detects an independent GSC D0,
and returns all contract windows and dimensions from the first-party API.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from typing import Any

import pandas as pd

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable, window_iso
from seoagents.config.models import SeoAgentsConfig
from seoagents.control_tower.gsc import period_windows
from seoagents.quant.frames import gsc_rows_to_frame
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec

_GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]



class GoogleSEOMonitorSpec(BaseToolSpec):
    """整合 Google Trends 趋势探测与 GSC 流量表现指标 (真实 API / 无密钥 mock 双模)."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
        self.config = config          # 趋势走 DataForSEO 时要读凭证与地域
        gsc = config.seo_credentials.google_search_console
        self.token_path = os.path.expanduser(gsc.token_path)
        self.service_account_path = config.seo_credentials.google_search_console.service_account_path
        self.secrets_path = os.path.expanduser(gsc.client_secrets_path)
        self.default_site = config.sites.gsc_property
        self.tracked_keywords = list(config.sites.tracked_keywords)
        self.store = store
        self._gsc_service: Any = None
        self._pytrends: Any = None
        self._trend_weights: dict[str, float] = {}

    # -- ToolSpec surface --------------------------------------------------
    def get_name(self) -> str:
        return "google_seo_monitor"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "google_seo_monitor",
            "description": (
                "拉取 Google Search Console 真实的点击率、展现量和平均排名数据,"
                "并交叉比对 Google Trends 的飙升词热度趋势。无密钥时返回确定性模拟数据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "query_gsc_performance",
                            "query_rising_keywords",
                            "collect_gsc_module",
                        ],
                        "description": "具体获取指标动作",
                    },
                    "target_site": {
                        "type": "string",
                        "description": "GSC 绑定的站点 (例如 'sc-domain:example.com');缺省用配置站点",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "分析和追踪趋势的目标关键词列表;缺省用配置关键词",
                    },
                    "days_limit": {
                        "type": "integer",
                        "default": 30,
                        "description": "GSC 历史统计回溯天数",
                    },
                    "business_date": {
                        "type": "string",
                        "description": "模块业务日期 YYYY-MM-DD；缺省为当前 UTC 日期",
                    },
                    "probe_days": {
                        "type": "integer",
                        "default": 10,
                        "description": "从 today-2 向前探测 D0 的最大天数",
                    },
                    "row_limit": {
                        "type": "integer",
                        "default": 25000,
                        "description": "每个维度最多返回的 API 行数",
                    },
                },
                "required": ["action"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        action = arguments.get("action")
        target_site = arguments.get("target_site") or self.default_site
        keywords = list(arguments.get("keywords") or self.tracked_keywords)
        days_limit = int(arguments.get("days_limit", 30))
        LOGGER.info(f"SEO Monitor action={action} session={session_id}")

        if action == "query_gsc_performance":
            dims = arguments.get("dimensions")
            return self._query_gsc_performance(target_site, days_limit, dimensions=dims)

        if action == "collect_gsc_module":
            business_date = str(
                arguments.get("business_date")
                or dt.datetime.now(dt.timezone.utc).date().isoformat()
            )
            return self._collect_gsc_module(
                target_site=target_site,
                business_date=business_date,
                probe_days=int(arguments.get("probe_days", 10)),
                row_limit=int(arguments.get("row_limit", 25000)),
            )

        if action == "query_rising_keywords":
            return await self._query_rising_keywords(keywords)
        return unavailable(
            source="google_seo_monitor", reason=f"unknown action '{action}'"
        )

    # -- GSC ---------------------------------------------------------------
    def _init_gsc_client(self) -> Any:
        if self._gsc_service is not None:
            return self._gsc_service

        # Credential resolution, in priority order. The previous version led
        # with two absolute paths on a developer's Windows box — dead on every
        # other machine, and they leaked the GCP project name into the repo.
        candidates = [
            ("service_account_path", self.service_account_path),
            ("SEOAGENTS_GSC_SERVICE_ACCOUNT (env)", os.environ.get("SEOAGENTS_GSC_SERVICE_ACCOUNT", "")),
            ("client_secrets_path", self.secrets_path),
            ("token_path", self.token_path),
        ]
        cred_path = None
        for label, raw in candidates:
            if not raw:
                continue
            expanded = os.path.expanduser(str(raw))
            if os.path.exists(expanded):
                cred_path = expanded
                LOGGER.info(f"GSC credentials resolved from {label}: {expanded}")
                break
        if not cred_path:
            tried = ", ".join(f"{lbl}={val or '(unset)'}" for lbl, val in candidates)
            raise FileNotFoundError(
                "未找到 GSC 凭证。请在 agents.yaml 的 "
                "seo_credentials.google_search_console.service_account_path 指向"
                "服务账号 JSON,或设置环境变量 SEOAGENTS_GSC_SERVICE_ACCOUNT。"
                f"已尝试: {tried}"
            )


        from googleapiclient.discovery import build

        # Auto-detect Service Account vs User OAuth Token
        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("type") == "service_account":
                from google.oauth2 import service_account
                creds = service_account.Credentials.from_service_account_file(cred_path, scopes=_GSC_SCOPES)
                LOGGER.info(f"Loaded GSC Service Account: {creds.service_account_email}")
            else:
                from google.oauth2.credentials import Credentials
                creds = Credentials.from_authorized_user_file(cred_path, scopes=_GSC_SCOPES)
        except Exception as err:  # noqa: BLE001 - credential format boundary
            LOGGER.warning(f"Fallback credential parsing for {cred_path}: {err}")
            from google.oauth2 import service_account
            try:
                creds = service_account.Credentials.from_service_account_file(cred_path, scopes=_GSC_SCOPES)
            except Exception:  # noqa: BLE001 - credential format boundary
                from google.oauth2.credentials import Credentials
                creds = Credentials.from_authorized_user_file(cred_path, scopes=_GSC_SCOPES)

        self._gsc_service = build("searchconsole", "v1", credentials=creds)
        return self._gsc_service

    def query_gsc_raw(
        self,
        target_site: str,
        days_limit: int,
        dimensions: list[str] | None = None,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
        row_limit: int = 25000,
        start_row: int = 0,
    ) -> list[dict[str, Any]]:
        if not target_site:
            return []
        dims = dimensions or ["query", "page"]
        gsc = self._init_gsc_client()
        if start_date_str and end_date_str:
            s_str, e_str = start_date_str, end_date_str
        else:
            end = pd.Timestamp.now() - pd.Timedelta(days=2)
            start = end - pd.Timedelta(days=days_limit)
            s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

        request_body = {
            "startDate": s_str,
            "endDate": e_str,
            "dimensions": dims,
            "rowLimit": row_limit,
            "startRow": start_row,
        }
        response = gsc.searchanalytics().query(siteUrl=target_site, body=request_body).execute()
        return response.get("rows", [])

    @staticmethod
    def _row_to_contract(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": str((raw.get("keys") or [""])[0]),
            "clicks": float(raw.get("clicks") or 0.0),
            "impressions": float(raw.get("impressions") or 0.0),
            "ctr": float(raw.get("ctr") or 0.0),
            "position": float(raw.get("position") or 0.0),
        }

    def _query_gsc_with_retry(
        self,
        *,
        target_site: str,
        start: str,
        end: str,
        dimensions: list[str],
        row_limit: int,
        max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                return self.query_gsc_raw(
                    target_site,
                    0,
                    dimensions=dimensions,
                    start_date_str=start,
                    end_date_str=end,
                    row_limit=row_limit,
                )
            except Exception as exc:  # noqa: BLE001 - first-party API boundary
                last_error = exc
                if attempt + 1 < max_attempts:
                    time.sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    def _collect_gsc_module(
        self,
        *,
        target_site: str,
        business_date: str,
        probe_days: int,
        row_limit: int,
    ) -> dict[str, Any]:
        """Strict, first-party collection for the modular control tower."""
        source = "Google Search Console Search Analytics API"
        if not target_site:
            return unavailable(source=source, reason="target_site 未提供，无法查询 GSC")
        try:
            business_day = dt.date.fromisoformat(business_date)
        except ValueError:
            return unavailable(source=source, reason="business_date 必须是 YYYY-MM-DD")
        probe_days = max(1, min(int(probe_days), 30))
        row_limit = max(1, min(int(row_limit), 25000))
        try:
            self._init_gsc_client()
            d0: dt.date | None = None
            probe_evidence: list[dict[str, Any]] = []
            for offset in range(2, 2 + probe_days):
                candidate = business_day - dt.timedelta(days=offset)
                rows = self._query_gsc_with_retry(
                    target_site=target_site,
                    start=candidate.isoformat(),
                    end=candidate.isoformat(),
                    dimensions=["date"],
                    row_limit=10,
                )
                probe_evidence.append({"date": candidate.isoformat(), "row_count": len(rows)})
                if rows:
                    d0 = candidate
                    break
            if d0 is None:
                return unavailable(
                    source=source,
                    reason=(
                        f"从 {business_day - dt.timedelta(days=2)} 向前探测 "
                        f"{probe_days} 日，未找到有数据的 GSC 完整日"
                    ),
                    site=target_site,
                    business_date=business_date,
                    probe_evidence=probe_evidence,
                )

            windows = period_windows(d0.isoformat())
            periods: dict[str, list[dict[str, Any]]] = {}
            for key, window in windows.items():
                raw_rows = self._query_gsc_with_retry(
                    target_site=target_site,
                    start=window.start,
                    end=window.end,
                    dimensions=["date"],
                    row_limit=row_limit,
                )
                periods[key] = [self._row_to_contract(row) for row in raw_rows]

            dimensions: dict[str, list[dict[str, Any]]] = {}
            dimension_windows: dict[str, dict[str, str]] = {}
            truncated: list[str] = []
            for output_key, api_dimension in {
                "daily": "date",
                "queries": "query",
                "pages": "page",
                "countries": "country",
                "devices": "device",
            }.items():
                start, end = windows["cur30"].start, windows["cur30"].end
                raw_rows = self._query_gsc_with_retry(
                    target_site=target_site,
                    start=start,
                    end=end,
                    dimensions=[api_dimension],
                    row_limit=row_limit,
                )
                if len(raw_rows) >= row_limit:
                    truncated.append(output_key)
                dimensions[output_key] = [self._row_to_contract(row) for row in raw_rows]
                dimension_windows[output_key] = {"start": start, "end": end}

            collected_at = dt.datetime.now(dt.timezone.utc).isoformat()
            return real(
                {
                    "site": target_site,
                    "business_date": business_date,
                    "d0": d0.isoformat(),
                    "period_rows": periods,
                    "dimension_rows": dimensions,
                    "dimension_windows": dimension_windows,
                    "truncated_dimensions": truncated,
                    "probe_evidence": probe_evidence,
                    "collected_at": collected_at,
                    "single_source_risk": True,
                    "cross_validation": "单源，未经外部 SERP 交叉验证",
                },
                source=source,
                data_window=f"{windows['prev30'].start}/{windows['d0'].end}",
            )
        except FileNotFoundError as exc:
            return unavailable(source=source, reason=f"GSC 凭证缺失: {exc}", site=target_site)
        except ImportError:
            return unavailable(
                source=source,
                reason="google-api-python-client 未安装 (pip install 'seoagents[google]')",
                site=target_site,
            )
        except Exception as exc:  # noqa: BLE001 - API boundary
            LOGGER.exception("GSC 模块采集失败")
            return unavailable(source=source, reason=f"GSC 模块采集失败: {exc}", site=target_site)


    def _query_gsc_performance(
        self, target_site: str, days_limit: int, dimensions: list[str] | None = None
    ) -> dict[str, Any]:

        if not target_site:
            return unavailable(
                source="google_seo_monitor.gsc",
                reason="target_site 未提供,无法查询 GSC",
            )
        rows = None
        started = window_iso()
        dims = dimensions or ["query", "page"]
        try:
            gsc = self._init_gsc_client()
            end = pd.Timestamp.now()
            start = end - pd.Timedelta(days=days_limit)
            request_body = {
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
                "dimensions": dims,
                "rowLimit": 25000,
            }
            response = (
                gsc.searchanalytics().query(siteUrl=target_site, body=request_body).execute()
            )
            rows = response.get("rows", [])

        except FileNotFoundError as exc:
            return unavailable(
                source="google_seo_monitor.gsc",
                reason=f"GSC 凭证缺失: {exc}",
                site=target_site,
            )
        except ImportError:
            return unavailable(
                source="google_seo_monitor.gsc",
                reason="google-api-python-client 未安装 (pip install 'seoagents[google]')",
                site=target_site,
            )
        except Exception as exc:  # noqa: BLE001 - API boundary
            LOGGER.exception("GSC query failed")
            return unavailable(
                source="google_seo_monitor.gsc",
                reason=f"GSC 查询失败: {exc}",
                site=target_site,
            )

        if not rows:
            # A real, successful query that returned nothing is genuinely
            # different from a failed one: the site exists in GSC but had no
            # impressions in the window. Report it as real, with zero rows —
            # never invent rows to fill the table.
            return real(
                {
                    "site": target_site,
                    "days": days_limit,
                    "total_clicks": 0.0,
                    "total_impressions": 0.0,
                    "rows": [],
                    "row_count": 0,
                    "note": (
                        f"GSC 查询成功,但 {days_limit} 天窗口内站点 {target_site} "
                        f"无展现与点击数据。"
                    ),
                },
                source="google_seo_monitor.gsc",
                data_window=started,
            )
        df = gsc_rows_to_frame(rows)
        total_clicks = float(df["Clicks"].sum())
        total_impr = float(df["Impressions"].sum()) if "Impressions" in df.columns else 0.0
        return real(
            {
                "site": target_site,
                "days": days_limit,
                "dimensions": dims,
                "total_clicks": total_clicks,
                "total_impressions": total_impr,
                "row_count": len(df),
                "rows": df.head(50).to_dict(orient="records"),
                "markdown": df.head(15).to_markdown(index=False),
            },
            source="google_seo_monitor.gsc",
            data_window=started,
        )


    # ── 趋势:优先 DataForSEO,pytrends 仅作兜底 ──────────────────────
    def _dfs_credentials(self) -> tuple[str, str, str, str]:
        cfg = self.config
        key = (cfg.seo_credentials.dataforseo_api_key or "").strip()
        base = cfg.seo_credentials.dataforseo_base_url.rstrip("/")
        loc = (getattr(cfg.sites, "serp_location_name", "") or "").strip()
        lang = (getattr(cfg.sites, "serp_language_code", "") or "").strip()
        return key, base, loc, lang

    @staticmethod
    def _weight_from_series(values: list[float]) -> float | None:
        """把一条兴趣度时间序列压成一个权重。

        取「近四周均值 ÷ 全期均值」:排在一个正在上升的词上,比排在一个正在
        消退的词上值钱 —— 这正是 M_t 的 γ 项里 W_i 该表达的意思。

        夹在 [0.5, 2.0] 之间。不夹的话,一个从 1 涨到 80 的季节性词会得到
        权重 20,单它一个就能主导整个 M_t。

        **「量到了零」和「量不到」是两回事**,这里必须分开:

        * 拿到足够样本、但全期搜索量为 0 → 这是一次**成功的测量**,结论是
          「这个词没有趋势信号」,返回中性的 1.0。品牌名常常就是这样。
        * 样本不足(接口没给够点位)→ 这才是量不到,返回 None,由上层报
          UNAVAILABLE。

        早先两种情况都返回 None,结果是「品牌词没人搜」这个完全正常的事实
        把整条自进化闭环判成了数据不可用。
        """
        clean = [float(v) for v in values if v is not None]
        if len(clean) < 8:
            return None                     # 样本太少 —— 这是「量不到」
        overall = sum(clean) / len(clean)
        if overall <= 0:
            return 1.0                      # 量到了,结论是没有搜索热度
        recent = sum(clean[-4:]) / 4
        return max(0.5, min(2.0, recent / overall))

    async def _query_rising_keywords(self, keywords: list[str]) -> dict[str, Any]:
        if not keywords:
            return unavailable(
                source="google_seo_monitor.trends", reason="keywords 为空,无法做趋势分析"
            )
        kws = keywords[:5]
        started = window_iso()

        dfs = await self._trends_via_dataforseo(kws)
        if dfs is not None:
            return dfs

        # 兜底:pytrends。它是同步库且经常 429,丢到线程里跑,别占着事件循环。
        import asyncio

        return await asyncio.to_thread(self._trends_via_pytrends, kws, started)

    async def _trends_via_dataforseo(self, keywords: list[str]) -> dict[str, Any] | None:
        """返回 None 表示「这条路走不通,请换下一条」;返回 envelope 表示已出结果。"""
        key, base, loc, lang = self._dfs_credentials()
        if not key:
            return None
        if not loc:
            # 不用默认地域兜底 —— 拿美国的趋势去解释西班牙站的排名,
            # 算出来的数字看着正常,其实毫无关系。
            LOGGER.warning("未配置 serp_location_name,跳过 DataForSEO 趋势")
            return None

        import httpx

        payload = [{"keywords": keywords, "location_name": loc,
                    "language_code": lang or "es"}]
        try:
            async with httpx.AsyncClient(timeout=90.0) as c:
                resp = await c.post(
                    f"{base}/v3/keywords_data/google_trends/explore/live",
                    headers={"Authorization": f"Basic {key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
                d = resp.json()
        except Exception as exc:  # noqa: BLE001 - API 边界
            LOGGER.warning(f"DataForSEO 趋势请求失败: {exc}")
            return None

        task = (d.get("tasks") or [{}])[0]
        if int(task.get("status_code", 0)) != 20000:
            LOGGER.warning(
                f"DataForSEO 趋势返回 {task.get('status_code')}: {task.get('status_message')}"
            )
            return None

        # 真实返回形态(已实测):result[].items[] 里 type=google_trends_graph,
        # data[] 每项是一周,values[] 与请求的 keywords 顺序一一对应。
        series: dict[str, list[float]] = {k: [] for k in keywords}
        got_graph = False
        for res in (task.get("result") or []):
            for item in (res.get("items") or []):
                if item.get("type") != "google_trends_graph":
                    continue
                got_graph = True
                order = item.get("keywords") or keywords
                for point in (item.get("data") or []):
                    if point.get("missing_data"):
                        continue
                    vals = point.get("values") or []
                    for i, kw in enumerate(order):
                        if i < len(vals) and vals[i] is not None and kw in series:
                            series[kw].append(float(vals[i]))

        if not got_graph:
            # 连图都没返回 —— 这才是真的量不到
            LOGGER.warning("DataForSEO 趋势没有返回 google_trends_graph,转 pytrends 兜底")
            return None

        measured: dict[str, float] = {}
        below_threshold: list[str] = []
        for kw, vals in series.items():
            w = self._weight_from_series(vals)
            if w is not None:
                measured[kw] = round(w, 4)
            else:
                # 图返回了但这个词一个点位都没有 —— Google Trends 对搜索量低于
                # 可报告阈值的词就是这样。这是**量到了**:结论是没有搜索热度,
                # 权重中性。把它当成「数据不可用」会让品牌词这种正常情况
                # 把整条自进化闭环判死。
                measured[kw] = 1.0
                below_threshold.append(kw)
            self.set_trend_weight(kw, measured[kw])

        if below_threshold:
            LOGGER.info(
                f"以下关键词搜索量低于 Google Trends 可报告阈值,权重取中性 1.0:"
                f"{below_threshold}"
            )

        lines = [
            f"- `{kw}`:权重 {w}" + (
                "(搜索量低于 Google Trends 可报告阈值,取中性值)"
                if kw in below_threshold else "(近四周 / 全期兴趣度之比)"
            )
            for kw, w in sorted(measured.items(), key=lambda x: -x[1])
        ]
        markdown = f"### 关键词趋势权重(地域:{loc})\n" + "\n".join(lines)
        return real(
            {
                "keywords": keywords,
                "trend_weights": measured,
                "below_threshold": below_threshold,
                "geo": loc,
                "provider": "dataforseo",
                "cost_usd": d.get("cost"),
                "markdown": markdown,
            },
            source="google_seo_monitor.trends",
            data_window=window_iso(),
        )

    def _trends_via_pytrends(self, keywords: list[str], started: str) -> dict[str, Any]:
        geo = (getattr(self.config.sites, "serp_location_code", "") or "").strip()
        summary_output: list[str] = []
        related: dict[str, Any] = {}
        try:
            if self._pytrends is None:
                from pytrends.request import TrendReq  # lazy optional import

                self._pytrends = TrendReq(hl="en-US", tz=360)
            # geo 此前写死 "US" —— 监控的是西班牙站点,用美国趋势解释它的排名
            # 毫无意义。留空表示全球,比错误地指定一个国家好。
            self._pytrends.build_payload(keywords, cat=0, timeframe="today 3-m", geo=geo)
            related = self._pytrends.related_queries() or {}
        except ImportError:
            return unavailable(
                source="google_seo_monitor.trends",
                reason="DataForSEO 不可用,且 pytrends 未安装",
                keywords=keywords,
            )
        except Exception as exc:  # noqa: BLE001 - API boundary
            return unavailable(
                source="google_seo_monitor.trends",
                reason=f"DataForSEO 不可用,pytrends 也失败: {exc}",
                keywords=keywords,
            )

        rising: dict[str, Any] = {}
        for kw in keywords:
            kw_trend = related.get(kw) or {}
            rising_df = kw_trend.get("rising")
            if rising_df is not None and hasattr(rising_df, "empty") and not rising_df.empty:
                rising[kw] = rising_df.head(5).to_dict(orient="records")
                summary_output.append(
                    f"### 关键词 '{kw}' 飙升相关搜索 (过去90天):\n"
                    + rising_df.head(5).to_markdown(index=False)
                )
            else:
                rising[kw] = []
                summary_output.append(f"### 关键词 '{kw}': 暂未检测到显著飙升的搜索趋势指标。")
        return real(
            {"keywords": keywords, "rising": rising, "provider": "pytrends",
             "markdown": "\n\n".join(summary_output)},
            source="google_seo_monitor.trends",
            data_window=started,
        )

    def trend_weight(self, keyword: str) -> float:
        """W_i for the scoring engine.

        权重由 :meth:`_trends_via_dataforseo` 从真实兴趣度序列算出并缓存:
        近四周均值 ÷ 全期均值,夹在 [0.5, 2.0]。取不到测量值时返回中性的 1.0。

        更早的实现是拿 ``sha256(keyword)`` 推权重 —— 那让 M_t 的 γ 项变成了
        关键词拼写的函数,而不是搜索需求的函数。
        """
        cached = self._trend_weights.get(keyword)
        return float(cached) if cached is not None else 1.0

    def set_trend_weight(self, keyword: str, weight: float) -> None:
        """Record a measured weight so the scoring engine can use it."""
        self._trend_weights[keyword] = float(weight)


__all__ = ["GoogleSEOMonitorSpec"]
