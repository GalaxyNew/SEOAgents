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

from seoagents.agent.models import ToolCall
from seoagents.logging import LOGGER
from seoagents.tools.executor import ToolExecutor

_BUILT_IN_DIR = Path(__file__).parent / "built_in"


class SkillManager:
    """Loads and lists compiled + built-in skills."""

    def __init__(self, skills_dir: str | os.PathLike[str]) -> None:
        self.skills_dir = Path(os.path.expanduser(str(skills_dir)))
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def _skill_files(self) -> list[Path]:
        files = sorted(self.skills_dir.glob("*.yaml"))
        files += sorted(_BUILT_IN_DIR.glob("*.yaml"))
        return files

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
                        "built_in": path.parent == _BUILT_IN_DIR,
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
        if not path.exists() or path.parent == _BUILT_IN_DIR:
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
        """Compile a trace into ``<skills_dir>/<skill_id>.yaml`` and return the path."""
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
            "description": description
            or f"Auto-distilled from a high-performance trace ({len(steps)} steps)",
            "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "source": {"m_t": m_t, "trace_len": len(trace_history)},
            "steps": steps,
            "stats": {"usage_count": 0},
        }
        path = self.manager.skills_dir / f"{skill_id}.yaml"
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        LOGGER.info(f"Skill '{skill_id}' compiled to {path} ({len(steps)} static steps)")
        return str(path)

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
