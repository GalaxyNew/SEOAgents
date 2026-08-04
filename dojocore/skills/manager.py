"""SkillManager + RuntimeSkillCompiler (L5).

The manual's self-evolution core: high-performing multi-step traces are
"distilled" into static YAML skills that replay deterministically against the
L4 executor — zero LLM tokens on subsequent runs. Skills live in
``~/.dojo/skills`` (configurable) alongside built-in rule/template skills.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import yaml

from dojocore.logging import LOGGER
from dojocore.agent.models import ToolCall
from dojocore.tools.executor import ToolExecutor

# 框架不自带技能。内置技能是部门内容 —— EEATSignalRules 之类只对 SEO 成立,
# 检索部有自己的一套。由部门在构造时传进来,框架对「技能该长什么样」没有意见。
# 这和 12 号文里工作流模板的处理是同一条原则。


class SkillManager:
    """Loads and lists compiled + built-in skills."""

    def __init__(
        self,
        skills_dir: str | os.PathLike[str],
        *,
        built_in_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.skills_dir = Path(os.path.expanduser(str(skills_dir)))
        self.built_in_dir = Path(os.path.expanduser(str(built_in_dir))) if built_in_dir else None
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        # 提案单独一个目录。做成同目录下的状态字段是不够的 —— replay 时
        # 只要有一处没查那个字段,门禁就形同虚设。物理隔开,扫不到就执行不了。
        self.proposals_dir = self.skills_dir / "proposals"
        self.proposals_dir.mkdir(parents=True, exist_ok=True)

    def _skill_files(self) -> list[Path]:
        """只返回**已签字**的技能。proposals/ 不在其中,所以提案无法被 replay。"""
        files = sorted(self.skills_dir.glob("*.yaml"))
        if self.built_in_dir and self.built_in_dir.is_dir():
            files += sorted(self.built_in_dir.glob("*.yaml"))
        return files

    def list_proposals(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in sorted(self.proposals_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                LOGGER.warning(f"提案 {path.name} 解析失败: {exc}")
                continue
            data["_path"] = str(path)
            out.append(data)
        return out

    def get_proposal(self, skill_id: str) -> dict[str, Any] | None:
        path = self.proposals_dir / f"{skill_id}.yaml"
        if not path.is_file():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return None
        data["_path"] = str(path)
        return data

    def list_skills(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for path in self._skill_files():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                out.append(
                    {
                        "id": data.get("id", path.stem),
                        "kind": data.get("kind", "compiled"),
                        "description": data.get("description", ""),
                        "steps": len(data.get("steps", [])),
                        "usage_count": data.get("stats", {}).get("usage_count", 0),
                        "path": str(path),
                        "built_in": self.built_in_dir is not None and path.parent == self.built_in_dir,
                    }
                )
            except yaml.YAMLError:
                LOGGER.warning(f"Skipping unparseable skill file: {path}")
        return out

    def get(self, skill_id: str) -> dict[str, Any] | None:
        for path in self._skill_files():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if data.get("id") == skill_id or path.stem == skill_id:
                data["_path"] = str(path)
                return data
        return None

    def _bump_usage(self, skill: dict[str, Any]) -> None:
        path = Path(skill.get("_path", ""))
        if not path.exists() or (self.built_in_dir and path.parent == self.built_in_dir):
            return
        stats = skill.setdefault("stats", {})
        stats["usage_count"] = int(stats.get("usage_count", 0)) + 1
        stats["last_used_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        persistable = {k: v for k, v in skill.items() if not k.startswith("_")}
        path.write_text(
            yaml.safe_dump(persistable, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


class RuntimeSkillCompiler:
    """Distills successful agent traces into replayable static skills."""

    def __init__(self, manager: SkillManager) -> None:
        self.manager = manager

    # -- distillation ------------------------------------------------------
    def auto_distill_trace(
        self,
        *,
        skill_id: str,
        trace_history: list[dict[str, Any]],
        description: str = "",
        m_t: float | None = None,
    ) -> str:
        """把轨迹编译成**提案**,落到 ``<skills_dir>/proposals/<skill_id>.yaml``。

        不再直接生成可执行技能。02 号文 §5.3 要求「技能编译改为提案制、
        由 HM 参数化后签字固化」—— 自动固化的风险是:一次偶然跑通的轨迹
        会被当成经验永久保留,之后每次重放都在复制那次偶然。

        返回提案文件路径。它在 ``proposals/`` 下,``_skill_files()`` 扫不到,
        因此在签字之前**无法被 replay**。
        """
        steps = [
            {
                "action": step.get("action", step.get("tool", "unknown")),
                "tool": step.get("tool", ""),
                "arguments": step.get("arguments", {}),
                "output_hint": str(step.get("output", ""))[:200],
            }
            for step in trace_history
            if step.get("ok", True) and step.get("tool")
        ]
        if not steps:
            raise ValueError("Cannot distill an empty/failed trace into a skill")

        doc = {
            "id": skill_id,
            "kind": "compiled",
            "status": "proposed",
            "description": description
            or f"由一段高绩效轨迹自动蒸馏({len(steps)} 步),待签字",
            "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": {"m_t": m_t, "trace_len": len(trace_history)},
            "steps": steps,
            "stats": {"usage_count": 0},
        }
        path = self.manager.proposals_dir / f"{skill_id}.yaml"
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        LOGGER.info(
            f"技能提案 '{skill_id}' 已生成({len(steps)} 步),待签字后才可重放: {path}"
        )
        return str(path)

    # -- 签字 --------------------------------------------------------------
    def approve_proposal(
        self,
        skill_id: str,
        *,
        approved_by: str,
        description: str = "",
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """签字固化:提案 → 可执行技能。

        ``overrides`` 就是方案里说的「参数化」:把轨迹里写死的实参(某个具体
        站点、某个具体日期)换成这次要固定下来的值。不给的话原样固化。
        """
        doc = self.manager.get_proposal(skill_id)
        if doc is None:
            raise KeyError(f"没有这个提案: {skill_id}")
        if overrides:
            for step in doc.get("steps", []):
                tool = step.get("tool", "")
                if tool in overrides:
                    step["arguments"] = {**(step.get("arguments") or {}), **overrides[tool]}
        doc["status"] = "active"
        doc["approved_by"] = approved_by
        doc["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if description:
            doc["description"] = description
        if overrides:
            doc["parameterized"] = overrides
        doc.pop("_path", None)

        target = self.manager.skills_dir / f"{skill_id}.yaml"
        target.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        (self.manager.proposals_dir / f"{skill_id}.yaml").unlink(missing_ok=True)
        LOGGER.info(f"技能 '{skill_id}' 已由 {approved_by} 签字固化 → {target}")
        return str(target)

    def reject_proposal(self, skill_id: str, *, rejected_by: str, reason: str = "") -> None:
        path = self.manager.proposals_dir / f"{skill_id}.yaml"
        if not path.is_file():
            raise KeyError(f"没有这个提案: {skill_id}")
        path.unlink()
        LOGGER.info(f"技能提案 '{skill_id}' 被 {rejected_by} 否决: {reason or '(未写理由)'}")

    # -- replay ------------------------------------------------------------
    async def execute_skill(
        self,
        skill_id: str,
        executor: ToolExecutor,
        *,
        overrides: dict[str, dict[str, Any]] | None = None,
        session_id: str = "skill-replay",
    ) -> list[dict[str, Any]]:
        """Replay a compiled skill step-by-step through the L4 executor (no LLM)."""
        skill = self.manager.get(skill_id)
        if skill is None:
            raise KeyError(f"Skill '{skill_id}' not found")
        results: list[dict[str, Any]] = []
        for step in skill.get("steps", []):
            tool = step.get("tool", "")
            if not tool:
                continue
            arguments = dict(step.get("arguments", {}))
            if overrides and tool in overrides:
                arguments.update(overrides[tool])
            res = await executor.execute_one(
                ToolCall(name=tool, arguments=arguments), session_id=session_id
            )
            results.append(
                {"tool": tool, "ok": res.ok, "output": res.as_text()[:2000], "latency_ms": res.latency_ms}
            )
            if not res.ok:
                LOGGER.warning(f"Skill '{skill_id}' step '{tool}' failed — aborting replay")
                break
        self.manager._bump_usage(skill)
        return results


__all__ = ["RuntimeSkillCompiler", "SkillManager"]
