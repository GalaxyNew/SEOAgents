"""L4 tool layer — specs, registry, executor, sandbox."""
from __future__ import annotations

from seoagents.config.models import SeoAgentsConfig
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.aeo_monitor import AeoVisibilitySpec
from seoagents.tools.base import BaseToolSpec, ToolRegistry
from seoagents.tools.environments.sandbox import SandboxPolicy
from seoagents.tools.executor import ToolExecutor
from seoagents.tools.indexing import IndexingOpsSpec
from seoagents.tools.internal_linker import InternalLinkerSpec
from seoagents.tools.lighthouse import LighthouseAuditSpec
from seoagents.tools.platform_ops import PlatformOpsSpec
from seoagents.tools.seo_trends import GoogleSEOMonitorSpec
from seoagents.tools.serp_tracker import SerpTrackerSpec
from seoagents.tools.site_auditor import SiteAuditorSpec


def register_default_tools(
    registry: ToolRegistry,
    config: SeoAgentsConfig,
    sandbox: SandboxPolicy,
    store: SeoHistoryStore | None = None,
) -> None:
    """Register the built-in SEO tool suite into the central registry."""
    registry.register(GoogleSEOMonitorSpec(config, store))
    registry.register(SerpTrackerSpec(config, store))
    registry.register(SiteAuditorSpec(config, sandbox, store))
    registry.register(LighthouseAuditSpec(config))
    registry.register(InternalLinkerSpec())
    registry.register(AeoVisibilitySpec(config, store))
    registry.register(IndexingOpsSpec(config, store))
    # The department head manages its own platform, not just the sites.
    registry.register(PlatformOpsSpec(config))


__all__ = [
    "AeoVisibilitySpec",
    "BaseToolSpec",
    "GoogleSEOMonitorSpec",
    "IndexingOpsSpec",
    "PlatformOpsSpec",
    "InternalLinkerSpec",
    "LighthouseAuditSpec",
    "SandboxPolicy",
    "SerpTrackerSpec",
    "SiteAuditorSpec",
    "ToolExecutor",
    "ToolRegistry",
    "register_default_tools",
]
