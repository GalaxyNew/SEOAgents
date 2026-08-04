"""框架级配置模型 (L1) —— 部门无关的那部分。

判据是「换个部门还成不成立」:沙箱约束、LLM 提供方、MCP 服务器、协作端点、
网关、调度器、存储目录 —— 检索部照样需要,所以归框架。GSC 凭证、站点清单、
M_t 权重那些只有 SEO 有的,留在 ``seoagents.config.models``。

这么拆的实际后果:SearchAgents 只 import dojocore 就能拿到沙箱与 LLM 配置,
不必把一堆 GSC 字段一起拖进来。
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
    """一个 MCP 服务端:要么本地 stdio 进程,要么远端 HTTP 端点。

    托管型 MCP(如 DataForSEO)只给 URL,没有可执行命令 —— 早先的模型只有
    ``command`` 字段,导致这类服务端被 ``if not server.command: continue``
    静默跳过,配了等于没配。
    """

    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    url: str = ""
    transport: str = "stdio"
    headers: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, d: Mapping[str, Any] | None) -> MCPServerConfig:
        url = str(_get(d, "url", ""))
        transport = str(_get(d, "transport", "")) or ("streamable-http" if url else "stdio")
        return cls(
            name=name,
            command=str(_get(d, "command", "")),
            args=tuple(str(a) for a in (_get(d, "args", []) or [])),
            env={str(k): str(v) for k, v in (_get(d, "env", {}) or {}).items()},
            url=url,
            transport=transport,
            headers={str(k): str(v) for k, v in (_get(d, "headers", {}) or {}).items()},
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


