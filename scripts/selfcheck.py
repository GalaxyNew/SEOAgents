#!/usr/bin/env python3
"""SEOAgents dependency-light end-to-end selfcheck.

Runs the full mock-mode closed loop without pytest — useful as a smoke test on
any machine (``python scripts/selfcheck.py``). Checks that need an optional
dependency (fastapi/apscheduler) are skipped with a note instead of failing.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
RESULTS: list[tuple[str, str, str]] = []


def record(name: str, status: str, note: str = "") -> None:
    RESULTS.append((name, status, note))
    mark = {"PASS": "✔", "FAIL": "✘", "SKIP": "○"}[status]
    print(f"  {mark} [{status}] {name}" + (f" — {note}" if note else ""))


def check(name: str):
    def deco(fn):
        def wrapper(*args, **kwargs):
            try:
                result = fn(*args, **kwargs)
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
                record(name, PASS)
            except SkipCheck as exc:
                record(name, SKIP, str(exc))
            except Exception as exc:  # noqa: BLE001
                record(name, FAIL, f"{type(exc).__name__}: {exc}")
                traceback.print_exc()
        return wrapper
    return deco


class SkipCheck(Exception):
    pass


def make_temp_config(tmp: Path) -> None:
    config_path = tmp / "agents.yaml"
    config_path.write_text(
        textwrap.dedent(
            f"""
            llm_providers: {{default_provider: anthropic, anthropic: {{api_key: ""}}}}
            sites:
              site_url: "https://example.com"
              brand_name: "Example"
              tracked_keywords: ["seo agent", "aeo monitoring"]
              content_pages:
                - url: "https://example.com/features"
                  anchor_candidates: ["seo agent", "features"]
                - url: "https://example.com/pricing"
                  anchor_candidates: ["pricing"]
            scheduler: {{enabled: false}}
            sandbox: {{allow_network_hosts: ["localhost"], execution_timeout_seconds: 30}}
            storage: {{data_dir: "{tmp / 'data'}", skills_dir: "{tmp / 'skills'}"}}
            """
        ),
        encoding="utf-8",
    )
    os.environ["SEOAGENTS_CONFIG"] = str(config_path)


# ---------------------------------------------------------------------------
@check("L7 ConfigStore: env expansion / deep merge / redaction / persistence")
def check_config():
    from seoagents.config import ConfigStore, deep_merge, expand_env

    os.environ["SC_TEST_SECRET"] = "abc123"
    assert expand_env({"k": "${SC_TEST_SECRET}"}) == {"k": "abc123"}
    assert deep_merge({"a": {"b": 1}}, {"a": {"c": 2}}) == {"a": {"b": 1, "c": 2}}

    store = ConfigStore.get_instance()
    assert store.snapshot().app.port == 8765
    store.update({"llm_providers": {"anthropic": {"api_key": "sk-ant-real-key-xyz"}}})
    assert store.redacted()["llm_providers"]["anthropic"]["api_key"] == "sk-a***"
    store.update({"llm_providers": {"anthropic": {"api_key": ""}}})  # back to mock mode


@check("L6 scoring: M_t formula + AEO V_t weighted sum")
def check_scoring():
    from seoagents.config.models import ScoringConfig
    from seoagents.quant.scoring import SeoScoreEngine

    engine = SeoScoreEngine(ScoringConfig())
    b = engine.compute_m_t(
        clicks=450.0, index_ratio=0.98, positions={"kw": 4.2},
        trend_weights={"kw": 1.2}, error_count=0,
    )
    expected = 0.4 * 450 + 0.2 * 0.98 + 0.3 * (1.2 / 4.2)
    assert abs(b.m_t - expected) < 1e-9, f"{b.m_t} != {expected}"

    v = SeoScoreEngine.compute_aeo_visibility({"a": 0.5, "b": 0.5}, {"a": 1.0, "b": 0.0})
    assert abs(v["v_t"] - 0.5) < 1e-9


@check("L6 frames: GSC row unpacking (keys[0]/keys[1])")
def check_frames():
    from seoagents.quant.frames import gsc_rows_to_frame

    df = gsc_rows_to_frame(
        [{"keys": ["kw", "https://x/p"], "clicks": 10, "impressions": 100, "ctr": 0.1,
          "position": 3.2}]
    )
    assert df.iloc[0]["Keyword"] == "kw" and df.iloc[0]["LandingPage"] == "https://x/p"


@check("L4 executor: golden pattern (timeout / deny / unregistered / coercion)")
async def check_executor():
    from seoagents.agent.models import ToolCall
    from seoagents.config.models import SandboxConfig
    from seoagents.tools.base import BaseToolSpec, ToolRegistry
    from seoagents.tools.environments.sandbox import SandboxPolicy
    from seoagents.tools.executor import ToolExecutor

    class Echo(BaseToolSpec):
        def get_name(self): return "echo"
        def get_schema(self): return {"name": "echo", "description": "", "parameters": {}}
        async def execute(self, arguments, session_id): return {"ok": True}

    class Slow(BaseToolSpec):
        def get_name(self): return "slow"
        def get_schema(self): return {"name": "slow", "description": "", "parameters": {}}
        async def execute(self, arguments, session_id):
            await asyncio.sleep(3)
            return "late"

    reg = ToolRegistry()
    reg.register(Echo()); reg.register(Slow())
    ex = ToolExecutor(reg, SandboxPolicy(SandboxConfig(execution_timeout_seconds=1,
                                                       denied_tools=("echo2",))))
    ok = await ex.execute_one(ToolCall(name="echo"))
    assert ok.ok and '"ok": true' in ok.content
    slow = await ex.execute_one(ToolCall(name="slow"))
    assert not slow.ok and "exceeded" in slow.error
    missing = await ex.execute_one(ToolCall(name="ghost"))
    assert not missing.ok and "not registered" in missing.error


@check("L4 internal linker: TF-IDF injection + double-link guard")
async def check_linker():
    from seoagents.tools.internal_linker import InternalLinkerSpec

    spec = InternalLinkerSpec()
    out = json.loads(await spec.execute(
        {"source_html": "<p>Try our seo agent with flexible pricing.</p>",
         "target_pages": [
             {"url": "/features", "anchor_candidates": ["seo agent"]},
             {"url": "/pricing", "anchor_candidates": ["pricing"]}]},
        "sc",
    ))
    assert out["linked_links_injected"] == 2, out
    assert '<a href="/features"' in out["optimized_html"]

    out2 = json.loads(await spec.execute(
        {"source_html": '<a href="/f">seo agent</a>',
         "target_pages": [{"url": "/x", "anchor_candidates": ["seo agent"]}]},
        "sc",
    ))
    assert out2["linked_links_injected"] == 0


@check("L3 runtime + mock agent loop: auditor plays real tools")
async def check_agent_loop():
    from seoagents.agent.runtime import get_runtime
    from seoagents.multi_agent.orchestrator import AUDITOR

    rt = get_runtime(refresh=True)
    assert rt.provider.name == "mock"
    result = await rt.loop.run("审计站点", system=AUDITOR.system_prompt,
                               allowed_tools=set(AUDITOR.allowed_tools))
    assert result.ok and result.final_text
    used = {t.tool for t in result.trace}
    assert {"site_technical_auditor", "lighthouse_audit"} <= used, used


@check("L3 multi-agent: Auditor→Writer→Linker content pipeline")
async def check_pipeline():
    from seoagents.agent.runtime import get_runtime

    rt = get_runtime()
    pipe = await rt.orchestrator.run_content_pipeline()
    assert pipe.auditor.ok and pipe.writer.ok and pipe.linker.ok
    assert "<a href=" in pipe.optimized_html, pipe.optimized_html[:200]


@check("L2+L5+L6+L7 evolution pipeline: score, persist, fix links, compile & replay skill")
async def check_evolution():
    from seoagents.agent.runtime import Runtime
    from seoagents.config import ConfigStore
    from seoagents.cron.seo_evo_jobs import FIX_SKILL_ID, run_seo_self_evolution_pipeline

    ConfigStore.get_instance().update({"scoring": {"skill_compile_threshold": 1.0}})
    rt = Runtime.from_config_store(ConfigStore.get_instance())
    summary = await run_seo_self_evolution_pipeline(rt)

    assert summary["clicks"] > 0
    assert summary["dead_links"] >= 1 and summary["links_fixed"] == summary["dead_links"]
    assert summary["v_t"] is not None
    assert summary["compiled_skill"] == FIX_SKILL_ID

    runs = rt.store.recent_audit_runs()
    assert runs and runs[0]["m_t"] == summary["m_t"]
    assert rt.store.latest_serp_positions() and rt.store.latest_aeo_visibility()

    replay = await rt.skill_compiler.execute_skill(FIX_SKILL_ID, rt.executor)
    assert replay and all(step["ok"] for step in replay)


@check("L7 storage: AtomicJsonStore / AtomicJsonlStore")
def check_stores():
    from seoagents.storage import AtomicJsonlStore, AtomicJsonStore

    tmp = Path(tempfile.mkdtemp())
    js = AtomicJsonStore(tmp / "doc.json")
    js.save({"a": 1})
    assert js.load() == {"a": 1}
    jl = AtomicJsonlStore(tmp / "log.jsonl")
    jl.append({"x": 1}); jl.append({"x": 2})
    assert [r["x"] for r in jl.iter_records()] == [1, 2]


@check("L2 gateway: feishu card build + dry-run broadcast")
async def check_gateway():
    from seoagents.gateway.adapters.feishu_seo_notifier import FeishuSeoNotifierAdapter

    adapter = FeishuSeoNotifierAdapter("")
    card = adapter._build_card(m_t_score=180.5, performance=92, links_fixed=2,
                               extra={"v_t": 0.44, "compiled_skill": "X"})
    elements = card["card"]["elements"]
    assert elements and elements[0]["tag"] == "markdown"
    assert "180.50" in elements[0]["content"]
    assert await adapter.broadcast_evolution_alert(m_t_score=1, performance=1, links_fixed=0)


@check("L2 dashboard API (fastapi)")
async def check_dashboard():
    try:
        import fastapi  # noqa: F401
    except ImportError:
        raise SkipCheck("fastapi not installed in this environment")
    import httpx

    from seoagents.dashboard.server import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/healthz")).json()["ok"] is True
        summary = (await client.get("/api/metrics/summary")).json()
        assert summary["provider"] == "mock"
        audit = (await client.post("/api/audit/run", json={})).json()
        assert audit["ok"] and audit["data"]["dead_link_count"] >= 1
        cfg = (await client.get("/api/config")).json()
        assert "site_technical_auditor" in cfg["resolved"]["tools"]
        assert "SEOAgents" in (await client.get("/")).text


@check("CLI parser: all subcommands wired")
def check_cli():
    from seoagents.cli import build_parser

    parser = build_parser()
    for argv in (["evolve"], ["audit"], ["agent", "task"], ["pipeline"],
                 ["skills", "list"], ["config", "init"], ["dashboard"]):
        args = parser.parse_args(argv)
        assert callable(args.func)


def main() -> int:
    print("SEOAgents selfcheck (mock mode)\n" + "=" * 46)
    with tempfile.TemporaryDirectory() as tmp:
        make_temp_config(Path(tmp))
        from seoagents.agent.runtime import reset_runtime
        from seoagents.config import ConfigStore

        ConfigStore.reset_instance(); reset_runtime()

        check_config()
        check_scoring()
        check_frames()
        check_executor()
        check_linker()
        check_agent_loop()
        check_pipeline()
        check_evolution()
        check_stores()
        check_gateway()
        check_dashboard()
        check_cli()

    print("=" * 46)
    passed = sum(1 for _, s, _ in RESULTS if s == PASS)
    failed = sum(1 for _, s, _ in RESULTS if s == FAIL)
    skipped = sum(1 for _, s, _ in RESULTS if s == SKIP)
    print(f"selfcheck: {passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
