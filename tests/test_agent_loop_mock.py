"""L3 loop + multi-agent pipeline in keyless mock mode (real tools, scripted LLM)."""
from __future__ import annotations

from seoagents.agent.runtime import Runtime
from seoagents.multi_agent.orchestrator import AUDITOR


async def test_mock_provider_selected(runtime: Runtime):
    assert runtime.provider.name == "mock"


async def test_auditor_loop_runs_real_tools(runtime: Runtime):
    result = await runtime.loop.run(
        "对站点执行技术审计",
        system=AUDITOR.system_prompt,
        allowed_tools=set(AUDITOR.allowed_tools),
    )
    assert result.ok
    tools_used = {t.tool for t in result.trace}
    assert "site_technical_auditor" in tools_used
    assert "lighthouse_audit" in tools_used
    assert result.final_text  # mock summary produced
    # demo snapshot audit must find the seeded dead links
    audit_step = next(t for t in result.trace if t.tool == "site_technical_auditor")
    assert audit_step.ok
    assert "dead_link" in audit_step.output


async def test_content_pipeline_end_to_end(runtime: Runtime):
    pipeline = await runtime.orchestrator.run_content_pipeline()
    assert pipeline.auditor is not None and pipeline.auditor.ok
    assert pipeline.writer is not None and pipeline.writer.ok
    assert pipeline.linker is not None and pipeline.linker.ok
    # Linker must have injected at least one internal link into writer HTML
    assert pipeline.optimized_html
    assert "<a href=" in pipeline.optimized_html
    assert len(pipeline.merged_trace) >= 3
