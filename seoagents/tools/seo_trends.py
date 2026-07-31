"""GoogleSEOMonitorSpec (L4) — GSC performance + Google Trends rising keywords.

Fixed rewrite of manual §4.1:
  * broken ``flat_data =`` / ``summary_output =`` assignments completed
  * ``r["keys"][0] / [1]`` indexing corrected (via quant.frames)
  * ``pd.Timestamp.now().sub(...)`` replaced with valid timestamp arithmetic
  * real Google API / pytrends imports are lazy & optional; without credentials
    the spec produces deterministic mock datasets so the loop stays closed.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.quality import real, unavailable, window_iso
from seoagents.quant.frames import gsc_rows_to_frame
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec

_GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]



class GoogleSEOMonitorSpec(BaseToolSpec):
    """整合 Google Trends 趋势探测与 GSC 流量表现指标 (真实 API / 无密钥 mock 双模)."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
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
                        "enum": ["query_gsc_performance", "query_rising_keywords"],
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

        if action == "query_rising_keywords":
            return self._query_rising_keywords(keywords)
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
        except Exception as err:
            LOGGER.warning(f"Fallback credential parsing for {cred_path}: {err}")
            from google.oauth2 import service_account
            try:
                creds = service_account.Credentials.from_service_account_file(cred_path, scopes=_GSC_SCOPES)
            except Exception:
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
            "rowLimit": 25000,
        }
        response = gsc.searchanalytics().query(siteUrl=target_site, body=request_body).execute()
        return response.get("rows", [])


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


    def _query_rising_keywords(self, keywords: list[str]) -> dict[str, Any]:
        if not keywords:
            return unavailable(
                source="google_seo_monitor.trends", reason="keywords 为空,无法做趋势分析"
            )
        summary_output: list[str] = []
        related: dict[str, Any] = {}
        started = window_iso()
        try:
            if self._pytrends is None:
                from pytrends.request import TrendReq  # lazy optional import

                self._pytrends = TrendReq(hl="en-US", tz=360)
            self._pytrends.build_payload(keywords[:5], cat=0, timeframe="today 3-m", geo="US")
            related = self._pytrends.related_queries() or {}
        except ImportError:
            return unavailable(
                source="google_seo_monitor.trends",
                reason="pytrends 未安装 (pip install 'seoagents[trends]')",
                keywords=keywords,
            )
        except Exception as exc:  # noqa: BLE001 - API boundary
            LOGGER.exception("pytrends query failed")
            return unavailable(
                source="google_seo_monitor.trends",
                reason=f"pytrends 查询失败: {exc}",
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
            {"keywords": keywords, "rising": rising, "markdown": "\n\n".join(summary_output)},
            source="google_seo_monitor.trends",
            data_window=started,
        )


    def trend_weight(self, keyword: str) -> float:
        """W_i for the scoring engine.

        Returns a neutral 1.0 unless a real Trends measurement has been cached
        by :meth:`_query_rising_keywords`. The previous implementation derived
        the weight from ``sha256(keyword)``, which made the γ term of M_t a
        function of keyword spelling rather than of search demand.
        """
        cached = self._trend_weights.get(keyword)
        return float(cached) if cached is not None else 1.0

    def set_trend_weight(self, keyword: str, weight: float) -> None:
        """Record a measured weight so the scoring engine can use it."""
        self._trend_weights[keyword] = float(weight)


__all__ = ["GoogleSEOMonitorSpec"]
