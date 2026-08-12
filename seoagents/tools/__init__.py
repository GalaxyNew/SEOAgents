"""L4 tool layer — specs, registry, executor, sandbox."""
from __future__ import annotations

from seoagents.config.models import SeoAgentsConfig
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools.aeo_monitor import AeoVisibilitySpec
from seoagents.tools.asset_hub_tool import AssetHubSpec
from seoagents.tools.base import BaseToolSpec, ToolRegistry
from seoagents.tools.environments.sandbox import SandboxPolicy
from seoagents.tools.executor import ToolExecutor
from seoagents.tools.indexing import IndexingOpsSpec
from seoagents.tools.content_publisher import ContentPublisherSpec
from seoagents.tools.keyword_discovery import KeywordDiscoverySpec
from seoagents.tools.internal_linker import InternalLinkerSpec
from seoagents.tools.lighthouse import LighthouseAuditSpec
from seoagents.tools.platform_ops import PlatformOpsSpec
from seoagents.tools.seo_trends import GoogleSEOMonitorSpec
from seoagents.tools.serp_tracker import SerpTrackerSpec
from seoagents.tools.site_auditor import SiteAuditorSpec
from seoagents.tools.system_ops import SystemOpsSpec


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
    # AEO 探针来自 DataForSEO;没凭证时 build_probes 返回空,
    # AeoVisibilitySpec 会如实报 UNAVAILABLE 而不是估算一个可见度。
    from seoagents.tools.probes import build_probes

    registry.register(AeoVisibilitySpec(config, store, build_probes(config)))
    registry.register(IndexingOpsSpec(config, store))
    registry.register(ContentPublisherSpec(config))
    registry.register(SystemOpsSpec())
    registry.register(KeywordDiscoverySpec(config, store))
    registry.register(AssetHubSpec(config, store))
    # 部门主管除了管站点,也要能管自己这套平台
    registry.register(PlatformOpsSpec(config))


__all__ = [
    "AeoVisibilitySpec",
    "AssetHubSpec",
    "BaseToolSpec",
    "GoogleSEOMonitorSpec",
    "IndexingOpsSpec",
    "KeywordDiscoverySpec",
    "PlatformOpsSpec",
    "InternalLinkerSpec",
    "LighthouseAuditSpec",
    "SandboxPolicy",
    "SerpTrackerSpec",
    "SiteAuditorSpec",
    "SystemOpsSpec",
    "ToolExecutor",
    "ToolRegistry",
    "register_default_tools",
]
