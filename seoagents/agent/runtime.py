"""Runtime (L3) — the main object graph, wired from ConfigStore.

``Runtime.from_config_store()`` is the single composition root (DojoAgents
convention): config -> sandbox -> registry+tools -> executor -> provider ->
agent loop -> skills -> orchestrator -> gateway -> scoring -> history store.
"""
from __future__ import annotations

from pathlib import Path

import threading
from dataclasses import dataclass
from urllib.parse import urlparse

from dojocore.context import set_config_provider
from dojocore.logging import LOGGER
from seoagents.agent.loop import UniversalAgentLoop
from seoagents.agent.providers import BaseLLMProvider, build_provider
from seoagents.config import ConfigStore
from seoagents.config.models import SeoAgentsConfig
from seoagents.gateway.adapters.feishu_seo_notifier import FeishuSeoNotifierAdapter
from seoagents.multi_agent.orchestrator import MultiAgentOrchestrator
from seoagents.quant.scoring import SeoScoreEngine
from seoagents.skills.manager import RuntimeSkillCompiler, SkillManager
from seoagents.storage.sqlite_store import SeoHistoryStore
from seoagents.tools import ToolRegistry, register_default_tools
from seoagents.tools.environments.sandbox import SandboxPolicy
from seoagents.tools.executor import ToolExecutor
from seoagents.utils.event_bus import EventBus

_runtime_lock = threading.Lock()
_runtime: Runtime | None = None


@dataclass
class Runtime:
    config_store: ConfigStore
    config: SeoAgentsConfig
    sandbox: SandboxPolicy
    registry: ToolRegistry
    executor: ToolExecutor
    provider: BaseLLMProvider
    loop: UniversalAgentLoop
    skill_manager: SkillManager
    skill_compiler: RuntimeSkillCompiler
    orchestrator: MultiAgentOrchestrator
    notifier: FeishuSeoNotifierAdapter
    score_engine: SeoScoreEngine
    store: SeoHistoryStore
    event_bus: EventBus

    @classmethod
    def from_config_store(cls, config_store: ConfigStore | None = None) -> Runtime:
        config_store = config_store or ConfigStore.get_instance()
        config = config_store.snapshot()

        # Tell the framework how to reach configuration, and make sure this
        # department's vocabulary is registered before anything queries it.
        set_config_provider(lambda: ConfigStore.get_instance().snapshot())
        import seoagents.department  # noqa: F401 - registers the SEO profile


        sandbox = SandboxPolicy(config.sandbox)
        # The audited property itself is always a legal target.
        site_host = urlparse(config.sites.site_url).hostname
        if site_host:
            sandbox.allow_host(site_host)

        store = SeoHistoryStore(config.storage.data_dir)
        registry = ToolRegistry()
        register_default_tools(registry, config, sandbox, store)

        executor = ToolExecutor(registry, sandbox)
        provider = build_provider(config.llm_providers)
        event_bus = EventBus()
        loop = UniversalAgentLoop(provider, executor, event_bus=event_bus)

        skill_manager = SkillManager(
        config.storage.skills_dir,
        # 内置技能是部门内容,由部门指给框架 —— EEATSignalRules 之类
        # 只对 SEO 成立,检索部会有自己的一套
        built_in_dir=Path(__file__).resolve().parent.parent / "skills" / "built_in",
    )
        skill_compiler = RuntimeSkillCompiler(skill_manager)
        orchestrator = MultiAgentOrchestrator(loop, config)
        notifier = FeishuSeoNotifierAdapter(config.gateway.feishu_webhook_url)
        score_engine = SeoScoreEngine(config.scoring)

        LOGGER.info(
            f"Runtime assembled: provider={provider.name} tools={len(registry.names())} "
            f"site={config.sites.site_url}"
        )
        return cls(
            config_store=config_store,
            config=config,
            sandbox=sandbox,
            registry=registry,
            executor=executor,
            provider=provider,
            loop=loop,
            skill_manager=skill_manager,
            skill_compiler=skill_compiler,
            orchestrator=orchestrator,
            notifier=notifier,
            score_engine=score_engine,
            store=store,
            event_bus=event_bus,
        )

    async def mount_mcp(self) -> int:
        """Mount configured MCP servers (async, called from app lifespan)."""
        from seoagents.tools.mcp_client import mount_mcp_servers

        return await mount_mcp_servers(self.registry, self.config.mcp_servers)

    def reload_config(self) -> Runtime:
        """Reload configuration snapshot and rebuild runtime sub-objects."""
        self.config_store.reload()
        new_rt = Runtime.from_config_store(self.config_store)
        self.config = new_rt.config
        self.sandbox = new_rt.sandbox
        self.registry = new_rt.registry
        self.executor = new_rt.executor
        self.provider = new_rt.provider
        self.loop = new_rt.loop
        self.skill_manager = new_rt.skill_manager
        self.skill_compiler = new_rt.skill_compiler
        self.orchestrator = new_rt.orchestrator
        self.notifier = new_rt.notifier
        self.score_engine = new_rt.score_engine
        return self


def get_runtime(refresh: bool = False) -> Runtime:
    """Process-wide runtime accessor."""
    global _runtime
    with _runtime_lock:
        if _runtime is None or refresh:
            _runtime = Runtime.from_config_store()
        return _runtime


def reset_runtime() -> None:
    global _runtime
    with _runtime_lock:
        _runtime = None


__all__ = ["Runtime", "get_runtime", "reset_runtime"]
