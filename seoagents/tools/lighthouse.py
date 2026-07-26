"""LighthouseAuditSpec (L4) — agent-facing wrapper over the sandbox executor."""
from __future__ import annotations

import json
from typing import Any

from seoagents.config.models import SeoAgentsConfig
from seoagents.tools.base import BaseToolSpec
from seoagents.tools.environments.sandbox.seo_audit_sandbox import TechnicalSeoSandboxExecutor


class LighthouseAuditSpec(BaseToolSpec):
    """Core Web Vitals / 性能 / SEO 评分审计 (Lighthouse 无头子进程)."""

    def __init__(self, config: SeoAgentsConfig) -> None:
        self.site_url = config.sites.site_url
        self.executor = TechnicalSeoSandboxExecutor(
            timeout_seconds=config.sandbox.execution_timeout_seconds
        )

    def get_name(self) -> str:
        return "lighthouse_audit"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "lighthouse_audit",
            "description": (
                "在隔离沙箱中运行 Lighthouse 无头审计,返回 performance/SEO 评分与 "
                "LCP/CLS 核心指标;Node 或网络不可用时返回确定性离线估算。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_url": {"type": "string", "description": "审计目标 URL;缺省用配置站点"}
                },
                "required": [],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> str:
        target = str(arguments.get("target_url") or self.site_url)
        result = await self.executor.run_lighthouse_audit(target)
        return json.dumps(result, ensure_ascii=False)


__all__ = ["LighthouseAuditSpec"]
