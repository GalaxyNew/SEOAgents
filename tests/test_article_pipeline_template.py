"""G1-O 文章产线 — 跨部门原子工序定版。

产线的价值不在"能跑"，而在"不许跳步"：每条 acceptance 都是对一次真实
事故的防御。这些测试钉住结构本身——依赖闭合、跨部门键完整、人审与
verify 缺一不可。结构松了，运行时怎么补都是补丁。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dojocore.workflow.template import WorkflowTemplate

YAML_PATH = (
    Path(__file__).resolve().parents[1]
    / "seoagents" / "workflows" / "article_pipeline.yaml"
)


@pytest.fixture(scope="module")
def tpl() -> WorkflowTemplate:
    raw = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))
    return WorkflowTemplate.from_dict(raw)  # from_dict 内部调用 validate()


class TestStructure:
    def test_template_id_and_dept(self, tpl):
        assert tpl.id == "article_pipeline"
        assert tpl.dept == "seo"

    def test_engine_validate_passes(self, tpl):
        """from_dict 不抛错即 validate 通过 —— 引擎级结构合法性。"""
        assert len(tpl.nodes) >= 10

    def test_dependencies_close_over_declared_nodes(self, tpl):
        ids = {n.id for n in tpl.nodes}
        dangling = [
            (n.id, d) for n in tpl.nodes for d in (n.depends_on or []) if d not in ids
        ]
        assert dangling == [], f"依赖指向不存在的节点: {dangling}"

    def test_single_input_single_output(self, tpl):
        ins = [n for n in tpl.nodes if n.type.value == "input"]
        outs = [n for n in tpl.nodes if n.type.value == "output"]
        assert len(ins) == 1 and len(outs) == 1


class TestFederationContract:
    """跨部门节点是本产线存在的理由 —— 键不完整就是废节点。"""

    def test_three_departments_are_cross_dept(self, tpl):
        dr = {n.id: n.config for n in tpl.nodes if n.type.value == "dept_request"}
        assert set(dr) == {"intel_research", "draft", "localize"}
        assert dr["intel_research"]["dept"] == "intel"
        # 实测契约：creative.article_draft（ContentAgents /api/v1/capabilities 确认）
        assert dr["draft"]["dept"] == "creative"
        assert dr["draft"]["capability"] == "article_draft"
        assert dr["localize"]["dept"] == "localization"
        for nid, cfg in dr.items():
            assert cfg.get("capability"), f"{nid} 缺 capability —— dept_request 必填"
            assert cfg.get("timeout_hours"), f"{nid} 缺 timeout_hours —— 跨部门无超时会永久挂起"

    def test_draft_depends_on_brief_and_intel(self, tpl):
        """撰文吃 brief 与资讯包 —— 少一个依赖就会写出无据可依的稿。"""
        draft = next(n for n in tpl.nodes if n.id == "draft")
        assert "brief" in (draft.depends_on or [])
        assert "intel_research" in (draft.depends_on or [])

    def test_localize_after_draft(self, tpl):
        loc = next(n for n in tpl.nodes if n.id == "localize")
        assert "draft" in (loc.depends_on or [])


class TestHardGates:
    """两条铁律：人审在发布前，verify 在发布后。"""

    def test_human_gate_precedes_publish(self, tpl):
        gate = next(n for n in tpl.nodes if n.id == "approve_publish")
        pub = next(n for n in tpl.nodes if n.id == "publish")
        assert "approve_publish" in (pub.depends_on or [])
        assert gate.type.value == "human_gate"

    def test_verify_after_publish_and_runs_real_command(self, tpl):
        v = next(n for n in tpl.nodes if n.id == "verify")
        assert "publish" in (v.depends_on or [])
        cmd = (v.config or {}).get("command", "")
        assert cmd.strip(), "verify 无命令 —— 口头验收的老路"
        assert "curl" in cmd, "verify 不真打线上 —— 假完成的老路"

    def test_output_terminal_after_verify(self, tpl):
        done = next(n for n in tpl.nodes if n.id == "done")
        assert "verify" in (done.depends_on or [])
        assert (done.config or {}).get("output_mode") == "end"

    def test_every_agent_task_has_acceptance(self, tpl):
        """无验收标准的节点 = 下一个『写完六篇但四步从未执行』事故。"""
        for n in tpl.nodes:
            if n.type.value in ("agent_task", "dept_request", "tool_call"):
                assert (n.acceptance or n.config.get("acceptance")) or n.type.value == "tool_call", \
                    f"{n.id} 无 acceptance"
