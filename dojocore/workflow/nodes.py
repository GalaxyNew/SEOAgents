"""Workflow node types — a deliberately small, closed set.

A department's pipeline is composed from generic nodes rather than written as
code. Five types cover every SEO process we have, and keeping the set closed is
the point: an engine that accepts arbitrary node types becomes a programming
language, and then nobody can look at a pipeline and know what it will do.

    agent_task    HM does it itself — free-text requirement, its own judgement
    tool_call     deterministic tool invocation, no judgement involved
    dept_request  hand off to another department (inbox/outbox contract)
    human_gate    a person must approve; agents may not self-approve
    verify        must carry a re-runnable command — evidence, not assertion

Order comes from ``depends_on``, not from list position. Nodes at the same
depth with no dependency between them run in parallel; anything that consumes
another node's output is serialised automatically. This encodes the rule the
SEO department operates under: read-only work can run in parallel, writes queue
up.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "NODE_SPECS",
    "FailurePolicy",
    "NodeType",
    "NodeValidationError",
    "WorkflowNode",
]

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class NodeValidationError(ValueError):
    """A node is malformed or misses something its type requires."""


class NodeType(str, Enum):
    AGENT_TASK = "agent_task"
    TOOL_CALL = "tool_call"
    DEPT_REQUEST = "dept_request"
    HUMAN_GATE = "human_gate"
    VERIFY = "verify"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def runs_externally(self) -> bool:
        """Whether completion depends on someone outside this department."""
        return self in (NodeType.DEPT_REQUEST, NodeType.HUMAN_GATE)


_LABELS = {
    NodeType.AGENT_TASK: "Agent 任务",
    NodeType.TOOL_CALL: "工具调用",
    NodeType.DEPT_REQUEST: "部门任务",
    NodeType.HUMAN_GATE: "人工审批",
    NodeType.VERIFY: "验证",
}


class FailurePolicy(str, Enum):
    STOP = "stop"            # halt the whole instance
    CONTINUE = "continue"    # mark failed, let independent branches proceed
    ESCALATE = "escalate"    # hand to the general manager


# Per-type required config keys, and a one-line reason used in error messages.
NODE_SPECS: dict[NodeType, dict[str, Any]] = {
    NodeType.AGENT_TASK: {
        "required": ("instruction",),
        "why": "Agent 任务必须写清楚要做什么(instruction)",
    },
    NodeType.TOOL_CALL: {
        "required": ("tool",),
        "why": "工具调用必须指定 tool 名",
    },
    NodeType.DEPT_REQUEST: {
        "required": ("dept", "capability"),
        "why": "部门任务必须指定目标部门(dept)与能力(capability);"
               "能力清单从对方 /api/v1/capabilities 动态获取",
    },
    NodeType.HUMAN_GATE: {
        "required": ("prompt",),
        "why": "人工审批必须说明请人判断什么(prompt)",
    },
    NodeType.VERIFY: {
        "required": ("command",),
        "why": "验证节点必须给可重跑命令(command)—— 断言不算证据",
    },
}


@dataclass(frozen=True)
class WorkflowNode:
    id: str
    type: NodeType
    title: str
    depends_on: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    config: Mapping[str, Any] = field(default_factory=dict)
    on_failure: FailurePolicy = FailurePolicy.STOP
    timeout_hours: int = 24
    optional: bool = False

    # -- validation --------------------------------------------------------
    def validate(self) -> None:
        if not _ID_RE.match(self.id):
            raise NodeValidationError(
                f"节点 id 非法: '{self.id}';应为小写字母开头的 2-40 位标识"
            )
        if not self.title.strip():
            raise NodeValidationError(f"节点 {self.id} 缺 title")

        spec = NODE_SPECS[self.type]
        missing = [k for k in spec["required"] if not self.config.get(k)]
        if missing:
            raise NodeValidationError(
                f"节点 {self.id}({self.type.label})缺少配置 {missing} —— {spec['why']}"
            )

        # Acceptance is what makes a node checkable rather than merely done.
        # Only human gates are exempt: the human *is* the criterion.
        if not self.acceptance and self.type is not NodeType.HUMAN_GATE:
            raise NodeValidationError(
                f"节点 {self.id} 缺 acceptance —— "
                f"没有验收标准的节点只能靠自述完成,这正是「标了 PASSED 但没做」的来源"
            )

        if self.type is NodeType.DEPT_REQUEST and not (
            self.config.get("spec_template") or self.config.get("spec_asset_id")
        ):
            raise NodeValidationError(
                f"节点 {self.id}: 部门任务需要 spec_template 或 spec_asset_id —— "
                f"需求正文要落成资产,不能塞在消息体里"
            )
        if self.type is NodeType.VERIFY:
            cmd = str(self.config.get("command", ""))
            if any(t in cmd for t in ("echo ", "true", "exit 0")) and "curl" not in cmd:
                raise NodeValidationError(
                    f"节点 {self.id}: 验证命令看起来是空转({cmd!r});"
                    f"必须实际检查线上状态"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "type_label": self.type.label,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "acceptance": list(self.acceptance),
            "config": dict(self.config),
            "on_failure": self.on_failure.value,
            "timeout_hours": self.timeout_hours,
            "optional": self.optional,
            "runs_externally": self.type.runs_externally,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WorkflowNode:
        try:
            ntype = NodeType(d["type"])
        except (KeyError, ValueError) as exc:
            raise NodeValidationError(
                f"未知节点类型 {d.get('type')!r};可用: {[t.value for t in NodeType]}"
            ) from exc
        node = cls(
            id=str(d.get("id", "")),
            type=ntype,
            title=str(d.get("title", "")),
            depends_on=tuple(d.get("depends_on") or ()),
            acceptance=tuple(str(a) for a in (d.get("acceptance") or ())),
            config=dict(d.get("config") or {}),
            on_failure=FailurePolicy(d.get("on_failure", "stop")),
            timeout_hours=int(d.get("timeout_hours", 24)),
            optional=bool(d.get("optional", False)),
        )
        node.validate()
        return node
