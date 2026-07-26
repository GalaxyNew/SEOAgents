"""GoogleSEOMonitorSpec (L4) — GSC performance + Google Trends rising keywords.

Fixed rewrite of manual §4.1:
  * broken ``flat_data =`` / ``summary_output =`` assignments completed
  * ``r["keys"][0] / [1]`` indexing corrected (via quant.frames)
  * ``pd.Timestamp.now().sub(...)`` replaced with valid timestamp arithmetic
  * real Google API / pytrends imports are lazy & optional; without credentials
    the spec produces deterministic mock datasets so the loop stays closed.
"""
from __future__ import annotations

import hashlib
import os
from typing import Any

import pandas as pd

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.quant.frames import gsc_rows_to_frame
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec

_GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def _stable_int(seed: str, lo: int, hi: int) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    span = max(hi - lo, 1)
    return lo + int.from_bytes(digest[:4], "big") % span


class GoogleSEOMonitorSpec(BaseToolSpec):
    """整合 Google Trends 趋势探测与 GSC 流量表现指标 (真实 API / 无密钥 mock 双模)."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
        gsc = config.seo_credentials.google_search_console
        self.token_path = os.path.expanduser(gsc.token_path)
        self.secrets_path = os.path.expanduser(gsc.client_secrets_path)
        self.default_site = config.sites.gsc_property
        self.tracked_keywords = list(config.sites.tracked_keywords)
        self.store = store
        self._gsc_service: Any = None
        self._pytrends: Any = None

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

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        action = arguments.get("action")
        target_site = arguments.get("target_site") or self.default_site
        keywords = list(arguments.get("keywords") or self.tracked_keywords)
        days_limit = int(arguments.get("days_limit", 30))
        LOGGER.info(f"SEO Monitor action={action} session={session_id}")

        if action == "query_gsc_performance":
            return self._query_gsc_performance(target_site, days_limit)
        if action == "query_rising_keywords":
            return self._query_rising_keywords(keywords)
        return f"Error: unknown action '{action}'"

    # -- GSC ---------------------------------------------------------------
    def _init_gsc_client(self) -> Any:
        if self._gsc_service is not None:
            return self._gsc_service
        if not os.path.exists(self.token_path):
            raise FileNotFoundError(f"Missing GSC OAuth token at: {self.token_path}")
        from google.oauth2.credentials import Credentials  # lazy optional import
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(self.token_path, scopes=_GSC_SCOPES)
        self._gsc_service = build("searchconsole", "v1", credentials=creds)
        return self._gsc_service

    def _query_gsc_performance(self, target_site: str, days_limit: int) -> str:
        if not target_site:
            return "Error: target_site must be provided for GSC query."
        rows = None
        source = "gsc_api"
        try:
            gsc = self._init_gsc_client()
            end = pd.Timestamp.now()
            start = end - pd.Timedelta(days=days_limit)
            request_body = {
                "startDate": start.strftime("%Y-%m-%d"),
                "endDate": end.strftime("%Y-%m-%d"),
                "dimensions": ["query", "page"],
                "rowLimit": 1000,
            }
            response = (
                gsc.searchanalytics().query(siteUrl=target_site, body=request_body).execute()
            )
            rows = response.get("rows", [])
        except FileNotFoundError as exc:
            LOGGER.warning(f"GSC credentials missing ({exc}); using deterministic mock dataset")
            rows, source = self._mock_gsc_rows(target_site), "mock"
        except ImportError:
            LOGGER.warning(
                "google-api-python-client not installed (pip install 'seoagents[google]'); "
                "using deterministic mock dataset"
            )
            rows, source = self._mock_gsc_rows(target_site), "mock"
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("GSC query failed; degrading to mock dataset")
            rows, source = self._mock_gsc_rows(target_site), f"mock (api error: {exc})"

        if not rows:
            return (
                f"GSC 接口返回成功,但在 {days_limit} 天范围内,站点 {target_site} "
                f"没有可导出的展现与点击数据。"
            )
        df = gsc_rows_to_frame(rows)
        total_clicks = float(df["Clicks"].sum())
        header = (
            f"[source={source}] site={target_site} days={days_limit} "
            f"total_clicks={total_clicks:.0f} rows={len(df)}\n\n"
        )
        return header + df.head(15).to_markdown(index=False)

    def _mock_gsc_rows(self, target_site: str) -> list[dict[str, Any]]:
        rows = []
        site_slug = target_site.replace("sc-domain:", "https://")
        for kw in self.tracked_keywords or ["seo agent"]:
            clicks = _stable_int(f"clicks::{target_site}::{kw}", 40, 400)
            impressions = clicks * _stable_int(f"imp::{kw}", 8, 25)
            position = _stable_int(f"pos::{kw}", 2, 18) + _stable_int(f"posf::{kw}", 0, 9) / 10
            rows.append(
                {
                    "keys": [kw, f"{site_slug}/{kw.replace(' ', '-')}"],
                    "clicks": clicks,
                    "impressions": impressions,
                    "ctr": clicks / impressions,
                    "position": position,
                }
            )
        return rows

    # -- Trends ------------------------------------------------------------
    def _query_rising_keywords(self, keywords: list[str]) -> str:
        if not keywords:
            return "Error: keywords list cannot be empty for trend analysis."
        summary_output: list[str] = []
        related: dict[str, Any] = {}
        source = "pytrends"
        try:
            if self._pytrends is None:
                from pytrends.request import TrendReq  # lazy optional import

                self._pytrends = TrendReq(hl="en-US", tz=360)
            self._pytrends.build_payload(keywords[:5], cat=0, timeframe="today 3-m", geo="US")
            related = self._pytrends.related_queries() or {}
        except ImportError:
            LOGGER.warning(
                "pytrends not installed (pip install 'seoagents[trends]'); using mock trends"
            )
            related, source = self._mock_related(keywords), "mock"
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("pytrends query failed; degrading to mock trends")
            related, source = self._mock_related(keywords), f"mock (api error: {exc})"

        for kw in keywords:
            kw_trend = related.get(kw) or {}
            rising_df = kw_trend.get("rising")
            if rising_df is not None and hasattr(rising_df, "empty") and not rising_df.empty:
                summary_output.append(
                    f"### 关键词 '{kw}' 飙升相关搜索 (过去90天) [source={source}]:\n"
                    + rising_df.head(5).to_markdown(index=False)
                )
            else:
                summary_output.append(f"### 关键词 '{kw}': 暂未检测到显著飙升的搜索趋势指标。")
        return "\n\n".join(summary_output)

    def _mock_related(self, keywords: list[str]) -> dict[str, Any]:
        related: dict[str, Any] = {}
        for kw in keywords:
            values = [_stable_int(f"trend::{kw}::{s}", 120, 5000) for s in ("a", "b", "c")]
            related[kw] = {
                "rising": pd.DataFrame(
                    {
                        "query": [f"{kw} tools", f"best {kw}", f"{kw} pricing"],
                        "value": sorted(values, reverse=True),
                    }
                )
            }
        return related

    def trend_weight(self, keyword: str) -> float:
        """Deterministic W_i in [0.6, 2.0] for the scoring engine (mock path)."""
        return round(0.6 + _stable_int(f"weight::{keyword}", 0, 140) / 100, 2)


__all__ = ["GoogleSEOMonitorSpec"]
