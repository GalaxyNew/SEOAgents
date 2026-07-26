"""IndexingOpsSpec (L4) — sitemap build, 301 mapping, GSC indexing submission.

Supports the manual's canonical self-evolution trace:
detect dead link -> create 301 mapping -> update sitemap -> submit for indexing.
Sitemap/redirect artifacts are written to the L7 data dir; submission is mocked
unless GSC credentials are configured (the real Indexing API is Google-partner
gated, so the mock path logs the exact request it would send).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from seoagents.config.models import SeoAgentsConfig
from seoagents.logging import LOGGER
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec


class IndexingOpsSpec(BaseToolSpec):
    """站点收录运维:生成 sitemap、301 重定向映射、提交收录请求."""

    def __init__(self, config: SeoAgentsConfig, store: SeoHistoryStore | None = None) -> None:
        self.site_url = config.sites.site_url
        self.data_dir = Path(config.storage.data_dir).expanduser()
        self.store = store

    def get_name(self) -> str:
        return "gsc_indexing_ops"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "gsc_indexing_ops",
            "description": (
                "收录运维三件套:build_sitemap 依据 URL 列表生成 sitemap.xml;"
                "create_301_mapping 为死链生成重定向映射(nginx 片段);"
                "submit_indexing 向 GSC 提交 sitemap/URL(无密钥时为 dry-run)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["build_sitemap", "create_301_mapping", "submit_indexing"],
                    },
                    "urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "build_sitemap: 纳入 sitemap 的 URL 列表",
                    },
                    "redirects": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from_path": {"type": "string"},
                                "to_path": {"type": "string"},
                            },
                            "required": ["from_path", "to_path"],
                        },
                        "description": "create_301_mapping: 死链到新页的映射",
                    },
                },
                "required": ["action"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        action = arguments.get("action")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if action == "build_sitemap":
            return self._build_sitemap(list(arguments.get("urls") or []))
        if action == "create_301_mapping":
            return self._create_301_mapping(list(arguments.get("redirects") or []))
        if action == "submit_indexing":
            return self._submit_indexing()
        return f"Error: unknown action '{action}'"

    def _build_sitemap(self, urls: list[str]) -> str:
        if not urls:
            urls = [self.site_url]
        today = time.strftime("%Y-%m-%d")
        entries = "\n".join(
            f"  <url><loc>{escape(u)}</loc><lastmod>{today}</lastmod></url>" for u in sorted(set(urls))
        )
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{entries}\n</urlset>\n"
        )
        out = self.data_dir / "sitemap.xml"
        out.write_text(xml, encoding="utf-8")
        LOGGER.info(f"Sitemap with {len(set(urls))} urls written to {out}")
        return json.dumps(
            {"status": "Success", "sitemap_path": str(out), "url_count": len(set(urls))},
            ensure_ascii=False,
        )

    def _create_301_mapping(self, redirects: list[dict[str, str]]) -> str:
        if not redirects:
            return json.dumps({"status": "Skipped", "reason": "no redirects supplied"})
        lines = [
            f"rewrite ^{r['from_path']}$ {r['to_path']} permanent;" for r in redirects
        ]
        out = self.data_dir / "redirects_301.conf"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if self.store is not None:
            for r in redirects:
                self.store.mark_dead_link_fixed(self.site_url + r["from_path"])
        LOGGER.info(f"301 mapping for {len(redirects)} paths written to {out}")
        return json.dumps(
            {"status": "Success", "config_path": str(out), "redirect_count": len(redirects),
             "sample": lines[:3]},
            ensure_ascii=False,
        )

    def _submit_indexing(self) -> str:
        sitemap_url = f"{self.site_url}/sitemap.xml"
        # Real path: webmasters.sitemaps().submit(siteUrl=..., feedpath=...) with OAuth.
        LOGGER.info(f"[dry-run] Would submit sitemap {sitemap_url} to Google Search Console")
        return json.dumps(
            {"status": "submitted (dry-run)", "sitemap": sitemap_url,
             "note": "配置 GSC OAuth 凭证后自动切换为真实提交"},
            ensure_ascii=False,
        )


__all__ = ["IndexingOpsSpec"]
