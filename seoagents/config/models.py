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


# 框架级配置模型从 dojocore 取。它们不随部门变化 —— 换成检索部,
# 沙箱约束和 LLM 提供方的形状一模一样。
from dojocore.config.models import (  # noqa: F401
    AppConfig,
    LLMProviderConfig,
    LLMProvidersConfig,
    MCPServerConfig,
    CollabConfig,
    SandboxConfig,
    GatewayConfig,
    SchedulerConfig,
    StorageConfig,
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
    openserp_endpoint: str = "http://openserp:7000"
    seonaut_endpoint: str = "http://localhost:8080"
    # DataForSEO:Basic 认证串(base64 的 login:password),留空则不启用
    dataforseo_api_key: str = ""
    dataforseo_base_url: str = "https://api.dataforseo.com"
    cms_publish_token: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SeoCredentialsConfig:
        return cls(
            google_search_console=GSCCredentialsConfig.from_dict(_get(d, "google_search_console")),
            google_pagespeed_api_key=str(_get(d, "google_pagespeed_api_key", "") or ""),
            openserp_endpoint=str(_get(d, "openserp_endpoint", cls.openserp_endpoint)),
            seonaut_endpoint=str(_get(d, "seonaut_endpoint", cls.seonaut_endpoint)),
            dataforseo_api_key=str(_get(d, "dataforseo_api_key", "") or ""),
            dataforseo_base_url=str(_get(d, "dataforseo_base_url", cls.dataforseo_base_url)),
            cms_publish_token=str(_get(d, "cms_publish_token", "") or ""),
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
    # SERP 检索地域 —— 不给默认值就会落到数据商的默认地域(DataForSEO 是美国),
    # 那种错误不报错、数据看着正常,所以这里必须显式配置。
    serp_location_name: str = ""
    serp_language_code: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> SitesConfig:
        pages = tuple(
            ContentPageConfig.from_dict(p) for p in (_get(d, "content_pages", []) or []) if isinstance(p, Mapping)
        )
        kws = tuple(str(k) for k in (_get(d, "tracked_keywords", []) or [])) or cls.tracked_keywords
        _serp_loc = str(_get(d, "serp_location_name", "") or "")
        _serp_lang = str(_get(d, "serp_language_code", "") or "")
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
            serp_location_name=_serp_loc,
            serp_language_code=_serp_lang,
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
    # 首轮兜底阈值。150 是「C_t = 点击总量」时代的遗留 —— C_t 改成**增量**后
    # M_t 的实际量级降到 ±1(实测 -0.63:index 0.12 + serp 0.15 - 错误 0.9),
    # 150 需要 375 次点击增量,对任何正常站点都是永不触发。
    skill_compile_threshold: float = 0.5
    # 有历史基线时改看相对改善;小于这个幅度视为噪声,不固化。
    skill_improve_delta: float = 0.1

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> ScoringConfig:
        return cls(
            alpha=float(_get(d, "alpha", cls.alpha)),
            beta=float(_get(d, "beta", cls.beta)),
            gamma=float(_get(d, "gamma", cls.gamma)),
            delta=float(_get(d, "delta", cls.delta)),
            skill_compile_threshold=float(_get(d, "skill_compile_threshold", cls.skill_compile_threshold)),
            skill_improve_delta=float(_get(d, "skill_improve_delta", cls.skill_improve_delta)),
        )


@dataclass(frozen=True)
class AEOConfig:
    """GEO/AEO visibility model V_t = sum_e S_e * M_e (manual §6.1)."""

    engine_shares: Mapping[str, float] = field(
        default_factory=lambda: {"chatgpt": 0.42, "claude": 0.18, "perplexity": 0.22, "google_aio": 0.18}
    )
    # 探测用的品类问题。必须是「不含品牌名」的真实提问 —— 拿品牌词去问,
    # AI 复述问题就算命中,提及率恒为 100%,测的是自我复述而非可见度。
    queries: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> AEOConfig:
        shares = _get(d, "engine_shares")
        qs = tuple(str(q) for q in (_get(d, "queries", []) or []) if str(q).strip())
        if isinstance(shares, Mapping) and shares:
            return cls(engine_shares={str(k): float(v) for k, v in shares.items()}, queries=qs)
        return cls(queries=qs)


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
