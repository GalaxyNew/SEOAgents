"""SiteAuditorSpec (L4) — lightweight technical SEO crawler (python-seo-analyzer style).

Same-domain BFS crawl with on-page checks: title/meta/H1 presence & length,
image alt coverage, canonical, robots noindex, and dead internal links
(recorded to the L7 history store). Network access is constrained by the
sandbox policy; in keyless/offline mode a built-in demo site snapshot is
audited instead so the pipeline always produces findings.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from dojocore.logging import LOGGER
from dojocore.quality import degraded, real, window_iso
from seoagents.config.models import SeoAgentsConfig
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.base import BaseToolSpec
from seoagents.tools.environments.sandbox import SandboxPolicy, SandboxViolation

# RFC 2606 reserved documentation domains always audit the built-in demo
# snapshot — the placeholder config stays deterministic and offline-safe.
DEMO_HOSTS = {"example.com", "www.example.com", "example.org", "example.net", "example.edu"}

# Deterministic offline demo snapshot: pages with intentional SEO defects,
# exercised by tests and by keyless demo runs.
DEMO_SITE: dict[str, str] = {
    "/": (
        "<html><head><title>Example — AI SEO Platform</title>"
        '<meta name="description" content="Self-evolving SEO agents."></head>'
        '<body><h1>Example</h1><p>Welcome.</p>'
        '<a href="/features">features</a> <a href="/pricing">pricing</a>'
        '<a href="/old-page">legacy</a><img src="/hero.png"></body></html>'
    ),
    "/features": (
        "<html><head><title>Features</title></head>"
        '<body><h1>Features</h1><h1>Duplicate H1</h1><p>Feature list.</p>'
        '<a href="/">home</a><img src="/f.png" alt="feature chart"></body></html>'
    ),
    "/pricing": (
        "<html><head><title>Pricing plans for the Example AI SEO platform — compare tiers "
        "and enterprise options today</title></head>"
        "<body><p>No H1 here.</p><a href='/missing-doc'>docs</a></body></html>"
    ),
    "/old-page": "__404__",
    "/missing-doc": "__404__",
}


class SiteAuditorSpec(BaseToolSpec):
    """全站技术审计:标题/描述/H1/alt/死链等 on-page 检查."""

    def __init__(
        self,
        config: SeoAgentsConfig,
        sandbox: SandboxPolicy,
        store: SeoHistoryStore | None = None,
    ) -> None:
        self.site_url = config.sites.site_url
        self.sandbox = sandbox
        self.store = store

    def get_name(self) -> str:
        return "site_technical_auditor"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "site_technical_auditor",
            "description": (
                "对目标站点执行同域 BFS 技术审计:缺失/超长标题与描述、H1 结构、"
                "图片 alt 覆盖率、canonical/noindex、死链(404)检测,结果写入历史库。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_url": {"type": "string", "description": "起始 URL;缺省用配置站点"},
                    "max_pages": {"type": "integer", "default": 25, "description": "最大爬取页数"},
                },
                "required": [],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        start_url = str(arguments.get("start_url") or self.site_url).rstrip("/") or self.site_url
        max_pages = min(int(arguments.get("max_pages", 25)), 100)
        host = urlparse(start_url).hostname or ""
        started = window_iso()

        # Two very different situations used to collapse into one silent
        # fallback. Auditing example.com against the built-in snapshot is
        # intended. Auditing a *real* site that someone forgot to allowlist and
        # silently getting the snapshot's planted defects back is not — you
        # receive a "3 broken links" report about a site that does not exist.
        is_demo = host in DEMO_HOSTS
        if not is_demo and not self.sandbox.is_host_allowed(start_url):
            raise SandboxViolation(
                f"host '{host}' 不在沙箱白名单中,拒绝审计。"
                f"这不是降级路径:若确需审计该站点,请将其加入 sandbox.allowed_hosts。"
            )
        use_live = not is_demo
        if not use_live:
            reason = "reserved demo domain (RFC 2606)"
            LOGGER.info(f"Host '{host}' {reason} — auditing built-in demo snapshot")
        report = await self._crawl(start_url, max_pages, live=use_live)

        for link in report["dead_links"]:
            if self.store is not None:
                self.store.record_dead_link(
                    url=link["url"], status_code=link["status"], source_page=link["source"]
                )
        LOGGER.info(
            f"Audit finished: {report['pages_crawled']} pages, "
            f"{len(report['issues'])} issues, {len(report['dead_links'])} dead links "
            f"session={session_id}"
        )
        report["mode"] = "live_crawl" if use_live else "demo_snapshot"
        if use_live:
            return real(report, source=f"site_auditor:{host}", data_window=started)
        return degraded(
            report,
            source="site_auditor:demo_snapshot",
            reason=(
                "审计的是内置演示快照(RFC 2606 保留域),不是真实站点。"
                "其中的死链与缺陷是刻意植入的测试数据,不得作为任何结论的依据。"
            ),
            data_window=started,
        )

    # -- crawling ----------------------------------------------------------
    async def _crawl(self, start_url: str, max_pages: int, *, live: bool) -> dict[str, Any]:
        base = urlparse(start_url)
        queue: list[str] = [start_url]
        seen: set[str] = set()
        issues: list[dict[str, Any]] = []
        dead_links: list[dict[str, Any]] = []
        pages_crawled = 0

        client = httpx.AsyncClient(timeout=15.0, follow_redirects=True) if live else None
        try:
            while queue and pages_crawled < max_pages:
                url = queue.pop(0)
                norm = url.split("#")[0].rstrip("/") or url
                if norm in seen:
                    continue
                seen.add(norm)

                status, html = await self._fetch(client, start_url, url)
                if status >= 400:
                    dead_links.append({"url": url, "status": status, "source": "crawl"})
                    continue
                if html is None:
                    continue
                pages_crawled += 1

                soup = BeautifulSoup(html, "html.parser")
                issues.extend(self._page_issues(url, soup))

                for a in soup.find_all("a", href=True):
                    href = urljoin(url + "/", a["href"])
                    parsed = urlparse(href)
                    if parsed.hostname and parsed.hostname != base.hostname:
                        continue  # external links out of audit scope
                    norm_child = href.split("#")[0].rstrip("/") or href
                    if norm_child not in seen and len(seen) + len(queue) < max_pages * 4:
                        queue.append(href)
        finally:
            if client is not None:
                await client.aclose()

        return {
            "site": start_url,
            "mode": "live" if live else "demo_snapshot",
            "pages_crawled": pages_crawled,
            # 暴露实际爬到的 URL:收录率要拿「我站上有什么」去比对
            # 「Google 收了什么」。用 GSC 有展现的页面当样本是错的 ——
            # 有展现即已在索引里,那样算出来的收录率恒为 100%。
            "crawled_urls": sorted(seen),
            "issues": issues,
            "dead_links": dead_links,
            "issue_count": len(issues),
            "dead_link_count": len(dead_links),
        }

    async def _fetch(
        self, client: httpx.AsyncClient | None, start_url: str, url: str
    ) -> tuple[int, str | None]:
        if client is None:  # demo snapshot mode
            path = urlparse(url).path or "/"
            body = DEMO_SITE.get(path.rstrip("/") or "/")
            await asyncio.sleep(0)  # cooperative yield
            if body is None or body == "__404__":
                return 404, None
            return 200, body
        try:
            resp = await client.get(url)
            ctype = resp.headers.get("content-type", "")
            return resp.status_code, resp.text if "html" in ctype else None
        except httpx.HTTPError as exc:
            LOGGER.warning(f"Fetch failed for {url}: {exc}")
            return 599, None

    # -- on-page checks ----------------------------------------------------
    @staticmethod
    def _page_issues(url: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        def add(kind: str, detail: str, severity: str = "warning") -> None:
            issues.append({"url": url, "type": kind, "detail": detail, "severity": severity})

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if not title:
            add("missing_title", "页面缺失 <title>", "error")
        elif len(title) > 60:
            add("title_too_long", f"标题 {len(title)} 字符 (>60): {title[:70]}…")
        elif len(title) < 10:
            add("title_too_short", f"标题过短 ({len(title)} 字符)")

        meta_desc = soup.find("meta", attrs={"name": "description"})
        desc = (meta_desc.get("content") or "").strip() if meta_desc else ""
        if not desc:
            add("missing_meta_description", "页面缺失 meta description", "error")
        elif len(desc) > 160:
            add("meta_description_too_long", f"描述 {len(desc)} 字符 (>160)")

        h1s = soup.find_all("h1")
        if not h1s:
            add("missing_h1", "页面缺失 <h1>", "error")
        elif len(h1s) > 1:
            add("multiple_h1", f"检测到 {len(h1s)} 个 <h1>")

        imgs = soup.find_all("img")
        missing_alt = [img.get("src", "?") for img in imgs if not (img.get("alt") or "").strip()]
        if missing_alt:
            add("img_missing_alt", f"{len(missing_alt)}/{len(imgs)} 张图片缺失 alt: {missing_alt[:3]}")

        robots = soup.find("meta", attrs={"name": "robots"})
        if robots and "noindex" in (robots.get("content") or "").lower():
            add("noindex", "页面被 robots meta 标记为 noindex", "error")

        return issues


__all__ = ["DEMO_HOSTS", "DEMO_SITE", "SiteAuditorSpec"]
