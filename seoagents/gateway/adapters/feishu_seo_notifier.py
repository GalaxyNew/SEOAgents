"""FeishuSeoNotifierAdapter (L2) — 每日自进化简报推送 (飞书富文本卡片).

Fixed rewrite of manual §7.2: the interactive card's ``elements`` are actually
populated (they were empty in the manual). Without a configured webhook the
adapter runs dry — the card JSON is logged instead of posted, so pipelines
never block on notification config.
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from dojocore.logging import LOGGER
from seoagents.gateway.adapters import BaseGatewayAdapter


class FeishuSeoNotifierAdapter(BaseGatewayAdapter):
    platform = "feishu"

    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url.strip()

    def _build_card(
        self, *, m_t_score: float | None, performance: float | None, links_fixed: int,
        extra: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Render the evolution digest.

        ``None`` metrics are rendered as an explicit "not computable" line with
        the reason. They are never formatted as 0.00 — a zero here reads as
        "measured, and it is bad", which is a different and much worse message
        than "we could not measure".
        """
        extra = extra or {}
        healthy = m_t_score is not None and m_t_score > 100
        if m_t_score is None:
            excluded = ", ".join(extra.get("excluded_inputs", [])) or "未知"
            lines = [
                "**📈 综合演化评分 M_t:** 不可计算(DATA_UNAVAILABLE)",
                f"**⚠️ 原因:** 以下输入非 REAL —— {excluded}",
            ]
        else:
            lines = [f"**📈 综合演化评分 M_t:** {m_t_score:.2f}"]
        lines.append(
            f"**⚡ Lighthouse 性能分:** {performance:.0f} / 100"
            if performance is not None
            else "**⚡ Lighthouse 性能分:** 未采集到"
        )
        lines.append(f"**🔗 本轮已验证修复死链:** {links_fixed} 条")
        if extra.get("links_proposed"):
            lines.append(
                f"**📝 待部署 301 提案:** {extra['links_proposed']} 条(未部署前不计入修复)"
            )
        if extra.get("v_t") is not None:
            lines.append(f"**🤖 AEO 品牌可见度 V_t:** {extra['v_t']:.2%}")
        if "issues" in extra:
            lines.append(f"**🧪 技术审计问题数:** {extra['issues']}")
        if extra.get("compiled_skill"):
            lines.append(f"**🧬 新固化技能:** `{extra['compiled_skill']}`")
        lines.append(f"\n_生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}_")

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "text": "🚨 SEOAgents 自动化进化与技术审计简报",
                    },
                    "template": "blue" if healthy else "red",
                },
                "elements": [
                    {"tag": "markdown", "content": "\n".join(lines)},
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text",
                             "content": "SEOAgents · L2 Gateway · seo_self_evolution_pipeline"}
                        ],
                    },
                ],
            },
        }

    async def broadcast_evolution_alert(
        self, *, m_t_score: float | None, performance: float | None, links_fixed: int,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        payload = self._build_card(
            m_t_score=m_t_score, performance=performance, links_fixed=links_fixed, extra=extra
        )
        if not self.webhook_url:
            LOGGER.info(
                "[dry-run] Feishu webhook not configured; evolution card:\n"
                + json.dumps(payload, ensure_ascii=False)[:800]
            )
            return True
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.webhook_url, json=payload)
            if res.status_code == 200:
                LOGGER.info("SEO/AEO 每日演化通知已成功投递飞书群。")
                return True
            LOGGER.error(f"Feishu API returned error status: {res.status_code} {res.text[:200]}")
            return False
        except Exception as exc:  # noqa: BLE001 - notification must never break the pipeline
            LOGGER.exception(f"Failed to broadcast feishu gateway notification: {exc}")
            return False


__all__ = ["FeishuSeoNotifierAdapter"]
