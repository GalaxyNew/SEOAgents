"""TechnicalSeoSandboxExecutor (L4) — heavyweight audits in isolated subprocesses.

Fixed and hardened version of manual §5:
  * ``json`` imported (missing in the manual)
  * proper returncode handling
  * Lighthouse runs through the LocalEnvironmentAdapter under a hard timeout
  * graceful degradation: when Node/Lighthouse (or the network) is unavailable
    the executor returns a deterministic offline estimate so the evolution
    pipeline still closes its loop in keyless/mock mode.
"""
from __future__ import annotations

import json
import shutil
from typing import Any
from urllib.parse import urlencode

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable
from seoagents.tools.environments import LocalEnvironmentAdapter


class TechnicalSeoSandboxExecutor:
    """Safely runs Lighthouse / analyzer subprocesses inside the L4 sandbox."""

    def __init__(
        self,
        timeout_seconds: int = 60,
        *,
        allow_mock_fallback: bool = False,
        pagespeed_api_key: str = "",
    ) -> None:
        self.timeout = timeout_seconds
        self.allow_mock_fallback = allow_mock_fallback
        key = (pagespeed_api_key or "").strip()
        # 未展开的 ${VAR} 占位符不是 key —— 当成没配,免得每轮都白打一次 400
        self.pagespeed_api_key = "" if key.startswith("${") else key
        self.env = LocalEnvironmentAdapter()

    # -- Lighthouse --------------------------------------------------------
    async def run_lighthouse_audit(self, target_url: str) -> dict[str, Any]:
        """Core Web Vitals,优先用 PageSpeed Insights API,其次本地 Lighthouse。

        PSI 跑的就是 Lighthouse,由 Google 侧执行:不需要本机装 Node/Chromium,
        数据同样是真实测量而非估算。只有 PSI 不可用时才退回本地 npx。
        """
        if self.pagespeed_api_key:
            psi = await self._run_pagespeed(target_url)
            if psi is not None:
                return psi
            LOGGER.info("PageSpeed API 不可用,尝试本地 Lighthouse")

        npx = shutil.which("npx")
        if npx is None:
            return self._fallback(
                target_url,
                reason="PageSpeed API 不可用且本机无 npx (Node.js)",
            )

        cmd = [
            npx, "--yes", "lighthouse", target_url,
            "--output=json",
            "--quiet",
            "--chrome-flags=--headless --disable-gpu --no-sandbox",
            "--only-categories=performance,seo",
        ]
        LOGGER.info(f"Sandbox launching Lighthouse subprocess for: {target_url}")
        try:
            result = await self.env.run(cmd, timeout=self.timeout)
        except (TimeoutError, asyncio.TimeoutError):
            LOGGER.error(f"Lighthouse timeout threshold breached for: {target_url}")
            return self._fallback(
                target_url, reason=f"Execution exceeded sandbox limit of {self.timeout}s"
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Lighthouse audit failed inside sandbox")
            return self._fallback(target_url, reason=str(exc))

        if not result.ok:
            return self._fallback(target_url, reason=result.stderr.strip()[:500] or "non-zero exit")

        try:
            lighthouse_data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return self._fallback(target_url, reason=f"unparseable Lighthouse output: {exc}")

        categories = lighthouse_data.get("categories", {})
        perf_score = (categories.get("performance", {}).get("score") or 0) * 100
        seo_score = (categories.get("seo", {}).get("score") or 0) * 100
        audits = lighthouse_data.get("audits", {})
        lcp = audits.get("largest-contentful-paint", {}).get("displayValue", "N/A")
        cls_val = audits.get("cumulative-layout-shift", {}).get("displayValue", "N/A")

        return real(
            {
                "performance_score": round(perf_score, 1),
                "seo_score": round(seo_score, 1),
                "largest_contentful_paint": lcp,
                "cumulative_layout_shift": cls_val,
                "target_url": target_url,
            },
            source="lighthouse",
        )

    # -- unavailable path --------------------------------------------------

    async def _run_pagespeed(self, target_url: str) -> dict[str, Any] | None:
        """调 PageSpeed Insights v5;失败返回 None 交给调用方决定下一步。"""
        import httpx

        params = {
            "url": target_url,
            "key": self.pagespeed_api_key,
            "strategy": "MOBILE",
        }
        qs = urlencode(params) + "&category=PERFORMANCE&category=SEO"
        url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?{qs}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                LOGGER.warning(f"PageSpeed API {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - 网络问题不该炸掉整条流水线
            LOGGER.warning(f"PageSpeed API 调用失败: {type(exc).__name__}: {exc}")
            return None

        lh = data.get("lighthouseResult") or {}
        cats = lh.get("categories") or {}
        perf = (cats.get("performance") or {}).get("score")
        seo = (cats.get("seo") or {}).get("score")
        if perf is None:
            LOGGER.warning("PageSpeed 返回里没有 performance 分,视为不可用")
            return None
        audits = lh.get("audits") or {}
        return real(
            {
                "performance_score": round(float(perf) * 100, 1),
                "seo_score": round(float(seo) * 100, 1) if seo is not None else None,
                "largest_contentful_paint": (audits.get("largest-contentful-paint") or {}).get("displayValue", "N/A"),
                "cumulative_layout_shift": (audits.get("cumulative-layout-shift") or {}).get("displayValue", "N/A"),
                "target_url": target_url,
                "strategy": "MOBILE",
                "lighthouse_version": lh.get("lighthouseVersion"),
            },
            source="pagespeed_insights_api",
        )

    def _fallback(self, target_url: str, *, reason: str) -> dict[str, Any]:
        """No synthetic Core Web Vitals.

        The old fallback returned ``performance_score`` derived from
        ``sha256(url)`` in the 62-95 range, labelled ``source:
        "offline_estimate"``. Downstream, ``seo_evo_jobs`` compares that number
        against 90 and adds a technical-defect penalty when it falls short — so
        a machine with no Node installed silently produced a CWV verdict.

        ``allow_mock_fallback=True`` is retained only for fixtures that need a
        deterministic shape; it is off by default and still reports DEGRADED.
        """
        if not self.allow_mock_fallback:
            LOGGER.warning(f"Lighthouse unavailable for {target_url}: {reason}")
            return unavailable(
                source="lighthouse", reason=reason, target_url=target_url
            )
        LOGGER.warning(
            f"Lighthouse unavailable ({reason}); emitting DEGRADED placeholder for {target_url}"
        )
        return {
            "performance_score": None,
            "seo_score": None,
            "largest_contentful_paint": None,
            "cumulative_layout_shift": None,
            "target_url": target_url,
            "data_status": "DEGRADED",
            "source": "lighthouse:placeholder",
            "data_window": "",
            "degraded_reason": reason,
        }


__all__ = ["TechnicalSeoSandboxExecutor"]
