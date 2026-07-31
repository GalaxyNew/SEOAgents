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

from seoagents.logging import LOGGER
from seoagents.quality import real, unavailable
from seoagents.tools.environments import LocalEnvironmentAdapter


class TechnicalSeoSandboxExecutor:
    """Safely runs Lighthouse / analyzer subprocesses inside the L4 sandbox."""

    def __init__(self, timeout_seconds: int = 60, *, allow_mock_fallback: bool = False) -> None:
        self.timeout = timeout_seconds
        self.allow_mock_fallback = allow_mock_fallback
        self.env = LocalEnvironmentAdapter()

    # -- Lighthouse --------------------------------------------------------
    async def run_lighthouse_audit(self, target_url: str) -> dict[str, Any]:
        """Launch a headless Lighthouse process; fall back to offline estimate."""
        npx = shutil.which("npx")
        if npx is None:
            return self._fallback(target_url, reason="npx (Node.js) not found on PATH")

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
        except (TimeoutError, asyncio.TimeoutError):  # noqa: UP041 - 3.10 compat
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
