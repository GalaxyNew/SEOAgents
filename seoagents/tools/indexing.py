"""IndexingOpsSpec (L4) — sitemap build, 301 mapping, GSC indexing submission.

Supports the manual's canonical self-evolution trace:
detect dead link -> create 301 mapping -> update sitemap -> submit for indexing.
Sitemap/redirect artifacts are written to the L7 data dir; submission is mocked
unless GSC credentials are configured (the real Indexing API is Google-partner
gated, so the mock path logs the exact request it would send).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx

from dojocore.logging import LOGGER
from dojocore.quality import degraded, real, unavailable
from seoagents.config.models import SeoAgentsConfig
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
                        "enum": [
                            "build_sitemap",
                            "create_301_mapping",
                            "verify_301_live",
                            "submit_indexing",
                        ],
                    },
                    "urls_to_verify": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "verify_301_live: 要实测的原死链 URL 列表",
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

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        action = arguments.get("action")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if action == "build_sitemap":
            return self._build_sitemap(list(arguments.get("urls") or []))
        if action == "create_301_mapping":
            return self._create_301_mapping(list(arguments.get("redirects") or []))
        if action == "verify_301_live":
            return await self._verify_301_live(list(arguments.get("urls_to_verify") or []))
        if action == "submit_indexing":
            return self._submit_indexing()
        return unavailable(
            source="gsc_indexing_ops", reason=f"unknown action '{action}'"
        )

    def _build_sitemap(self, urls: list[str]) -> dict[str, Any]:
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
        return real(
            {"sitemap_path": str(out), "url_count": len(set(urls))},
            source="gsc_indexing_ops.build_sitemap",
        )

    def _create_301_mapping(self, redirects: list[dict[str, str]]) -> dict[str, Any]:
        """Generate an nginx snippet. This is state PROPOSED, nothing more.

        The previous version called ``mark_dead_link_fixed()`` right here, so the
        dashboard reported "0 unfixed dead links" the moment a .conf file was
        written to a local directory that nobody ever deployed. Writing a file is
        not a fix; only ``verify_301_live`` observing a real 301 on the live host
        is.
        """
        if not redirects:
            return unavailable(
                source="gsc_indexing_ops.create_301_mapping",
                reason="no redirects supplied",
            )
        lines = [f"rewrite ^{r['from_path']}$ {r['to_path']} permanent;" for r in redirects]
        out = self.data_dir / "redirects_301.conf"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        LOGGER.info(
            f"301 mapping for {len(redirects)} paths written to {out} "
            f"(state=PROPOSED — not deployed, not verified)"
        )
        return real(
            {
                "redirect_state": "PROPOSED",
                "config_path": str(out),
                "redirect_count": len(redirects),
                "sample": lines[:3],
                "next_action": (
                    "把该 .conf 部署到站点服务器并 reload,然后调用 "
                    "gsc_indexing_ops(action='verify_301_live') 实测确认。"
                    "未经 verify 之前,死链状态保持未修复。"
                ),
            },
            source="gsc_indexing_ops.create_301_mapping",
        )

    async def _verify_301_live(self, urls: list[str]) -> dict[str, Any]:
        """State PROPOSED/DEPLOYED -> VERIFIED. Only this may clear a dead link."""
        if not urls:
            return unavailable(
                source="gsc_indexing_ops.verify_301_live", reason="no urls supplied"
            )
        verified, failed = [], []
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            for url in urls:
                try:
                    resp = await client.head(url)
                except Exception as exc:  # noqa: BLE001 - network boundary
                    failed.append({"url": url, "reason": f"请求失败: {exc}"})
                    continue
                location = resp.headers.get("location", "")
                if resp.status_code in (301, 308):
                    verified.append({"url": url, "status": resp.status_code, "location": location})
                    if self.store is not None:
                        self.store.mark_dead_link_fixed(url)
                else:
                    failed.append({"url": url, "reason": f"期望 301/308,实际 {resp.status_code}"})
        payload = {
            "redirect_state": "VERIFIED" if verified and not failed else "PARTIAL",
            "verified": verified,
            "failed": failed,
        }
        if failed and not verified:
            return unavailable(
                source="gsc_indexing_ops.verify_301_live",
                reason="全部 URL 均未观察到 301,重定向未生效",
                **payload,
            )
        if failed:
            return degraded(
                payload,
                source="gsc_indexing_ops.verify_301_live",
                reason=f"{len(failed)} 条未生效,仅 {len(verified)} 条已验证",
            )
        return real(payload, source="gsc_indexing_ops.verify_301_live")

    def _submit_indexing(self) -> dict[str, Any]:
        """Dry run until GSC OAuth is configured.

        The old return value was ``{"status": "submitted (dry-run)"}``. Any
        downstream string check for "submitted" read that as success.
        """
        sitemap_url = f"{self.site_url}/sitemap.xml"
        # Real path: webmasters.sitemaps().submit(siteUrl=..., feedpath=...) with OAuth.
        LOGGER.info(f"[dry-run] Would submit sitemap {sitemap_url} to Google Search Console")
        return unavailable(
            source="gsc_indexing_ops.submit_indexing",
            reason="未配置 GSC OAuth 凭证,提交未真实发生(dry_run)",
            submission_state="dry_run",
            sitemap=sitemap_url,
        )


__all__ = ["IndexingOpsSpec"]
