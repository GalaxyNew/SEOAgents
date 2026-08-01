"""Typed configuration schema (L7).

Frozen dataclasses, following the DojoAgents ``config/models.py`` convention:
config is read through ``ConfigStore.snapshot()`` as an immutable object graph.
Unknown YAML keys are ignored so the file may carry forward-compat sections.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _get(d: Mapping[str, Any] | None, key: str, default: Any = None) -> Any:
    if not isinstance(d, Mapping):
        return default
    return d.get(key, default)


@dataclass(frozen=True)
class AppConfig:
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> AppConfig:
        return cls(host=str(_get(d, "host", cls.host)), port=int(_get(d, "port", cls.port)))


@dataclass(frozen=True)
class LLMProviderConfig:
    api_key: str = ""
    model: str = ""
    base_url: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> LLMProviderConfig:
        return cls(
            api_key=str(_get(d, "api_key", "") or ""),
            model=str(_get(d, "model", "") or ""),
            base_url=str(_get(d, "base_url", "") or ""),
        )

    @property
    def has_key(self) -> bool:
        key = self.api_key.strip()
        return bool(key) and not key.startswith("sk-ant-...") and key.lower() not in {"", "none", "mock"}


@dataclass(frozen=True)
class LLMProvidersConfig:
    default_provider: str = "anthropic"
    anthropic: LLMProviderConfig = field(default_factory=LLMProviderConfig)
    openai_compat: LLMProviderConfig = field(default_factory=LLMProviderConfig)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> LLMProvidersConfig:
        return cls(
            default_provider=str(_get(d, "default_provider", "anthropic")),
            anthropic=LLMProviderConfig.from_dict(_get(d, "anthropic")),
            openai_compat=LLMProviderConfig.from_dict(_get(d, "openai_compat")),
        )

    def active(self) -> LLMProviderConfig:
        return getattr(self, self.default_provider, self.anthropic)


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, d: Mapping[str, Any] | None) -> MCPServerConfig:
        return cls(
            name=name,
            command=str(_get(d, "command", "")),
            args=tuple(str(a) for a in (_get(d, "args", []) or [])),
            env={str(k): str(v) for k, v in (_get(d, "env", {}) or {}).items()},
        )


@dataclass(frozen=True)
class CollabConfig:
    """Which department this instance speaks for in cross-department requests."""

    dept: str = "seo"
    display_name: str = "SEO 部"
    endpoint: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> CollabConfig:
        return cls(
            dept=str(_get(d, "dept", cls.dept)),
            display_name=str(_get(d, "display_name", cls.display_name)),
            endpoint=str(_get(d, "endpoint", "") or ""),
        )


@dataclass(frozen=True)
class GSCCredentialsConfig:
    """Search Console credentials.

    Two mutually exclusive auth modes, both explicit:

    * **service account** — ``service_account_path`` points at the JSON key.
      Preferred for unattended servers: no browser consent, no token refresh.
      The service-account email must be added as a user on the GSC property.
    * **user OAuth** — ``client_secrets_path`` + ``token_path``, for local
      interactive use.

    ``service_account_email`` is optional and only used for display (so the
    dashboard can tell you *which* identity to authorise on the property).
    """

    service_account_path: str = ""
    client_secrets_path: str = "~/.dojo/gsc_client_secrets.json"
    token_path: str = "~/.dojo/gsc_token.json"
    service_account_email: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> GSCCredentialsConfig:
        return cls(
            service_account_path=str(_get(d, "service_account_path", "") or ""),
            client_secrets_path=str(_get(d, "client_secrets_path", cls.client_secrets_path)),
            token_path=str(_get(d, "token_path", cls.token_path)),
            service_account_email=str(_get(d, "service_account_email", "") or ""),
        )


@dataclass(frozen=True)
class SeoCredentialsConfig:
    google_search_console: GSCCredentialsConfig = field(default_factory=GSCCredentialsConfig)
    google_pagespeed_api_key: str = ""
    openserp_endpoint: str = "http://localhost:7000"
    seonaut_endpoint: str = "http://localhost:8080"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SeoCredentialsConfig:
        return cls(
            google_search_console=GSCCredentialsConfig.from_dict(_get(d, "google_search_console")),
            google_pagespeed_api_key=str(_get(d, "google_pagespeed_api_key", "") or ""),
            openserp_endpoint=str(_get(d, "openserp_endpoint", cls.openserp_endpoint)),
            seonaut_endpoint=str(_get(d, "seonaut_endpoint", cls.seonaut_endpoint)),
        )


@dataclass(frozen=True)
class ContentPageConfig:
    url: str
    anchor_candidates: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ContentPageConfig:
        return cls(
            url=str(_get(d, "url", "")),
            anchor_candidates=tuple(str(a) for a in (_get(d, "anchor_candidates", []) or [])),
        )


@dataclass(frozen=True)
class SiteItemConfig:
    """Individual site definition in multi-site monitoring."""

    site_url: str = "https://example.com"
    gsc_property: str = "sc-domain:example.com"
    brand_name: str = "Example"
    tracked_keywords: tuple[str, ...] = ("seo agent", "aeo monitoring")

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SiteItemConfig:
        if not isinstance(d, Mapping):
            return cls()
        kws = tuple(str(k) for k in (_get(d, "tracked_keywords", []) or [])) or ("seo agent", "aeo monitoring")
        return cls(
            site_url=str(_get(d, "site_url", cls.site_url)).rstrip("/"),
            gsc_property=str(_get(d, "gsc_property", cls.gsc_property)),
            brand_name=str(_get(d, "brand_name", cls.brand_name)),
            tracked_keywords=kws,
        )


@dataclass(frozen=True)
class SitesConfig:
    """Target property under optimization."""

    site_url: str = "https://example.com"
    gsc_property: str = "sc-domain:example.com"
    brand_name: str = "Example"
    tracked_keywords: tuple[str, ...] = ("seo agent", "aeo monitoring")
    content_pages: tuple[ContentPageConfig, ...] = ()
    monitored_sites: tuple[SiteItemConfig, ...] = ()

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SitesConfig:
        pages = tuple(
            ContentPageConfig.from_dict(p) for p in (_get(d, "content_pages", []) or []) if isinstance(p, Mapping)
        )
        kws = tuple(str(k) for k in (_get(d, "tracked_keywords", []) or [])) or cls.tracked_keywords
        raw_monitored = _get(d, "monitored_sites", []) or []
        sites_list = []
        if isinstance(raw_monitored, list):
            for s in raw_monitored:
                if isinstance(s, Mapping):
                    sites_list.append(SiteItemConfig.from_dict(s))

        primary_site = SiteItemConfig(
            site_url=str(_get(d, "site_url", cls.site_url)).rstrip("/"),
            gsc_property=str(_get(d, "gsc_property", cls.gsc_property)),
            brand_name=str(_get(d, "brand_name", cls.brand_name)),
            tracked_keywords=kws,
        )

        if not sites_list:
            sites_list.append(primary_site)

        return cls(
            site_url=primary_site.site_url,
            gsc_property=primary_site.gsc_property,
            brand_name=primary_site.brand_name,
            tracked_keywords=primary_site.tracked_keywords,
            content_pages=pages,
            monitored_sites=tuple(sites_list),
        )



@dataclass(frozen=True)
class ScoringConfig:
    """Weights of the daily M_t self-evolution score (manual §6.1)."""

    alpha: float = 0.4   # organic clicks C_t
    beta: float = 0.2    # index coverage I_t
    gamma: float = 0.3   # sum_i W_i / R_(i,t)  (trend-weighted inverse SERP position)
    delta: float = 0.1   # technical error penalty E_t
    skill_compile_threshold: float = 150.0

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> ScoringConfig:
        return cls(
            alpha=float(_get(d, "alpha", cls.alpha)),
            beta=float(_get(d, "beta", cls.beta)),
            gamma=float(_get(d, "gamma", cls.gamma)),
            delta=float(_get(d, "delta", cls.delta)),
            skill_compile_threshold=float(_get(d, "skill_compile_threshold", cls.skill_compile_threshold)),
        )


@dataclass(frozen=True)
class AEOConfig:
    """GEO/AEO visibility model V_t = sum_e S_e * M_e (manual §6.1)."""

    engine_shares: Mapping[str, float] = field(
        default_factory=lambda: {"chatgpt": 0.42, "claude": 0.18, "perplexity": 0.22, "google_aio": 0.18}
    )

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> AEOConfig:
        shares = _get(d, "engine_shares")
        if isinstance(shares, Mapping) and shares:
            return cls(engine_shares={str(k): float(v) for k, v in shares.items()})
        return cls()


@dataclass(frozen=True)
class SandboxConfig:
    allow_network_hosts: tuple[str, ...] = (
        "localhost",
        "127.0.0.1",
        "www.googleapis.com",
        "trends.google.com",
    )
    restricted_builtins: bool = True
    execution_timeout_seconds: int = 60
    denied_tools: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SandboxConfig:
        hosts = tuple(str(h) for h in (_get(d, "allow_network_hosts", []) or [])) or cls.allow_network_hosts
        return cls(
            allow_network_hosts=hosts,
            restricted_builtins=bool(_get(d, "restricted_builtins", True)),
            execution_timeout_seconds=int(_get(d, "execution_timeout_seconds", 60)),
            denied_tools=tuple(str(t) for t in (_get(d, "denied_tools", []) or [])),
        )


@dataclass(frozen=True)
class GatewayConfig:
    feishu_webhook_url: str = ""
    slack_webhook_url: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> GatewayConfig:
        return cls(
            feishu_webhook_url=str(_get(d, "feishu_webhook_url", "") or ""),
            slack_webhook_url=str(_get(d, "slack_webhook_url", "") or ""),
        )


@dataclass(frozen=True)
class SchedulerConfig:
    evolution_hour: int = 2
    evolution_minute: int = 0
    enabled: bool = True

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SchedulerConfig:
        return cls(
            evolution_hour=int(_get(d, "evolution_hour", 2)),
            evolution_minute=int(_get(d, "evolution_minute", 0)),
            enabled=bool(_get(d, "enabled", True)),
        )


@dataclass(frozen=True)
class StorageConfig:
    data_dir: str = "~/.dojo/seoagents"
    skills_dir: str = "~/.dojo/skills"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> StorageConfig:
        return cls(
            data_dir=str(_get(d, "data_dir", cls.data_dir)),
            skills_dir=str(_get(d, "skills_dir", cls.skills_dir)),
        )


@dataclass(frozen=True)
class SeoAgentsConfig:
    app: AppConfig = field(default_factory=AppConfig)
    llm_providers: LLMProvidersConfig = field(default_factory=LLMProvidersConfig)
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    seo_credentials: SeoCredentialsConfig = field(default_factory=SeoCredentialsConfig)
    sites: SitesConfig = field(default_factory=SitesConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    aeo: AEOConfig = field(default_factory=AEOConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    collab: CollabConfig = field(default_factory=CollabConfig)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SeoAgentsConfig:
        d = d or {}
        mcp_raw = _get(d, "mcp_servers", {}) or {}
        mcp = tuple(
            MCPServerConfig.from_dict(name, spec) for name, spec in mcp_raw.items() if isinstance(spec, Mapping)
        )
        return cls(
            app=AppConfig.from_dict(_get(d, "app")),
            llm_providers=LLMProvidersConfig.from_dict(_get(d, "llm_providers")),
            mcp_servers=mcp,
            seo_credentials=SeoCredentialsConfig.from_dict(_get(d, "seo_credentials")),
            sites=SitesConfig.from_dict(_get(d, "sites")),
            scoring=ScoringConfig.from_dict(_get(d, "scoring")),
            aeo=AEOConfig.from_dict(_get(d, "aeo")),
            sandbox=SandboxConfig.from_dict(_get(d, "sandbox")),
            gateway=GatewayConfig.from_dict(_get(d, "gateway")),
            scheduler=SchedulerConfig.from_dict(_get(d, "scheduler")),
            storage=StorageConfig.from_dict(_get(d, "storage")),
            collab=CollabConfig.from_dict(_get(d, "collab")),
        )
