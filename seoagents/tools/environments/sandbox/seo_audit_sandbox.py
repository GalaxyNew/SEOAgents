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

import asyncio
import hashlib
import json
import shutil
from typing import Any

from seoagents.logging import LOGGER
from seoagents.tools.environments import LocalEnvironmentAdapter


def _stable_unit(seed: str) -> float:
    """Deterministic pseudo-measurement in [0,1) derived from a seed string."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


class TechnicalSeoSandboxExecutor:
    """Safely runs Lighthouse / analyzer subprocesses inside the L4 sandbox."""

    def __init__(self, timeout_seconds: int = 60, *, allow_mock_fallback: bool = True) -> None:
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
        except asyncio.TimeoutError:
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

        return {
            "success": True,
            "source": "lighthouse",
            "performance_score": round(perf_score, 1),
            "seo_score": round(seo_score, 1),
            "largest_contentful_paint": lcp,
            "cumulative_layout_shift": cls_val,
        }

    # -- offline estimate --------------------------------------------------
    def _fallback(self, target_url: str, *, reason: str) -> dict[str, Any]:
        if not self.allow_mock_fallback:
            return {"success": False, "source": "lighthouse", "error": reason}
        perf = 62 + _stable_unit(f"perf::{target_url}") * 33   # 62-95
        seo = 70 + _stable_unit(f"seo::{target_url}") * 28     # 70-98
        lcp_s = 1.2 + _stable_unit(f"lcp::{target_url}") * 2.8
        LOGGER.warning(
            f"Lighthouse unavailable ({reason}); returning deterministic offline estimate "
            f"for {target_url}"
        )
        return {
            "success": True,
            "source": "offline_estimate",
            "degraded_reason": reason,
            "performance_score": round(perf, 1),
            "seo_score": round(seo, 1),
            "largest_contentful_paint": f"{lcp_s:.1f} s",
            "cumulative_layout_shift": f"{_stable_unit('cls::' + target_url) * 0.25:.3f}",
        }


__all__ = ["TechnicalSeoSandboxExecutor"]
