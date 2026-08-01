"""Workflow templates — a department's pipeline, composed from generic nodes.

A template is a DAG. Execution order is derived from ``depends_on``, never from
the order nodes appear in the file: nodes at the same depth with no dependency
between them are parallel, and anything consuming another node's output is
serialised. That mirrors the operating rule the SEO department runs under —
read-only work in parallel, writes in a queue.

Templates are versioned and instances pin the version they started from.
Without pinning you cannot answer "did the revised process actually work
better", because the process changed underneath the comparison.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from seoagents.workflow.nodes import NodeType, NodeValidationError, WorkflowNode

__all__ = ["TemplateError", "WorkflowTemplate"]


class TemplateError(ValueError):
    """The pipeline as a whole is invalid (cycle, dangling edge, ...)."""


@dataclass(frozen=True)
class WorkflowTemplate:
    id: str
    name: str
    version: str = "1.0"
    description: str = ""
    dept: str = "seo"
    nodes: tuple[WorkflowNode, ...] = ()
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # -- validation --------------------------------------------------------
    def validate(self) -> None:
        if not self.nodes:
            raise TemplateError(f"模板 {self.id} 没有节点")
        ids = [n.id for n in self.nodes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise TemplateError(f"模板 {self.id} 存在重复节点 id: {sorted(dupes)}")

        known = set(ids)
        for node in self.nodes:
            node.validate()
            missing = [d for d in node.depends_on if d not in known]
            if missing:
                raise TemplateError(f"节点 {node.id} 依赖了不存在的节点: {missing}")
            if node.id in node.depends_on:
                raise TemplateError(f"节点 {node.id} 依赖了自己")
        self._detect_cycle()

    def _detect_cycle(self) -> None:
        by_id = {n.id: n for n in self.nodes}
        WHITE, GREY, BLACK = 0, 1, 2
        colour = dict.fromkeys(by_id, WHITE)
        stack: list[str] = []

        def visit(nid: str) -> None:
            colour[nid] = GREY
            stack.append(nid)
            for dep in by_id[nid].depends_on:
                if colour[dep] == GREY:
                    loop = stack[stack.index(dep):] + [dep]
                    raise TemplateError(f"模板 {self.id} 存在循环依赖: {' → '.join(loop)}")
                if colour[dep] == WHITE:
                    visit(dep)
            stack.pop()
            colour[nid] = BLACK

        for nid in by_id:
            if colour[nid] == WHITE:
                visit(nid)

    # -- topology ----------------------------------------------------------
    def layers(self) -> list[list[str]]:
        """Nodes grouped by depth. Everything inside one layer may run at once."""
        by_id = {n.id: n for n in self.nodes}
        depth: dict[str, int] = {}

        def compute(nid: str) -> int:
            if nid in depth:
                return depth[nid]
            deps = by_id[nid].depends_on
            depth[nid] = 0 if not deps else 1 + max(compute(d) for d in deps)
            return depth[nid]

        for nid in by_id:
            compute(nid)
        out: dict[int, list[str]] = {}
        for nid, d in depth.items():
            out.setdefault(d, []).append(nid)
        return [sorted(out[d]) for d in sorted(out)]

    def node(self, node_id: str) -> WorkflowNode:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def dependents(self, node_id: str) -> list[str]:
        return [n.id for n in self.nodes if node_id in n.depends_on]

    @property
    def external_nodes(self) -> list[WorkflowNode]:
        """Nodes whose completion depends on someone outside this department."""
        return [n for n in self.nodes if n.type.runs_externally]

    def summary(self) -> dict[str, Any]:
        layers = self.layers()
        return {
            "id": self.id, "name": self.name, "version": self.version,
            "dept": self.dept, "description": self.description,
            "node_count": len(self.nodes),
            "layer_count": len(layers),
            "max_parallel": max((len(l) for l in layers), default=0),
            "external_deps": [
                {"node": n.id, "dept": n.config.get("dept"), "capability": n.config.get("capability")}
                for n in self.external_nodes if n.type is NodeType.DEPT_REQUEST
            ],
            "human_gates": [n.id for n in self.nodes if n.type is NodeType.HUMAN_GATE],
            "tags": list(self.tags),
        }

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            **self.summary(),
            "nodes": [n.to_dict() for n in self.nodes],
            "layers": self.layers(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> WorkflowTemplate:
        try:
            nodes = tuple(WorkflowNode.from_dict(n) for n in (d.get("nodes") or ()))
        except NodeValidationError as exc:
            raise TemplateError(str(exc)) from exc
        tpl = cls(
            id=str(d.get("id", "")),
            name=str(d.get("name", "")),
            version=str(d.get("version", "1.0")),
            description=str(d.get("description", "")),
            dept=str(d.get("dept", "seo")),
            nodes=nodes,
            tags=tuple(d.get("tags") or ()),
            metadata=dict(d.get("metadata") or {}),
        )
        tpl.validate()
        return tpl

    def with_nodes(self, nodes: Iterable[WorkflowNode], *, version: str) -> WorkflowTemplate:
        """Derive a new version. Templates are immutable once instances exist."""
        tpl = WorkflowTemplate(
            id=self.id, name=self.name, version=version, description=self.description,
            dept=self.dept, nodes=tuple(nodes), tags=self.tags, metadata=self.metadata,
        )
        tpl.validate()
        return tpl
