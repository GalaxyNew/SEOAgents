"""Capability vocabulary — a registry, not a fixed enum.

A capability is the unit that makes two tools interchangeable and comparable:
tools declaring the same capability answer the same question and must emit the
same normalised shape, so they can be run side by side and cross-checked.

This started life as an ``Enum`` listing SEO's capabilities. That works for
exactly one department. A search department needs ``web_search``, ``ai_scrape``,
``index_ingest``, ``rerank``; a content department needs something else again —
and none of them should have to edit the framework to say so.

So the vocabulary is registered at import time by each department, and the
framework only knows the *shape* of a capability, never the list.
"""
from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = ["Capability", "CapabilityRegistry", "UnknownCapability", "capabilities"]


class UnknownCapability(KeyError):
    """Referenced a capability no department has registered."""


@dataclass(frozen=True)
class Capability:
    """One question a department can answer.

    ``result_schema`` names the normalised output shape. Two tools claiming the
    same capability but returning different shapes cannot be compared, which
    defeats the purpose — so the schema name is part of the declaration rather
    than an afterthought.
    """

    id: str
    label: str
    dept: str
    description: str = ""
    result_schema: str = ""
    default_sla_hours: int = 24
    comparable: bool = True          # can multiple providers be cross-checked?
    # Excluded from eq/hash: a dict field would make Capability unhashable,
    # and identity here is the id + its declared shape, not free-form extras.
    metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "dept": self.dept,
            "description": self.description, "result_schema": self.result_schema,
            "default_sla_hours": self.default_sla_hours,
            "comparable": self.comparable, **dict(self.metadata),
        }


class CapabilityRegistry:
    """Process-wide capability vocabulary, contributed by departments."""

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self._lock = threading.Lock()

    def register(self, cap: Capability, *, replace: bool = False) -> Capability:
        with self._lock:
            existing = self._items.get(cap.id)
            if existing is not None and not replace and existing != cap:
                raise ValueError(
                    f"能力 '{cap.id}' 已由部门 '{existing.dept}' 注册且定义不同;"
                    f"跨部门复用同一能力 id 时,定义必须一致(否则无法互相对比)"
                )
            self._items[cap.id] = cap
            return cap

    def register_many(self, caps: Iterable[Capability], *, replace: bool = False) -> None:
        for cap in caps:
            self.register(cap, replace=replace)

    def get(self, cap_id: str) -> Capability:
        try:
            return self._items[cap_id]
        except KeyError as exc:
            known = sorted(self._items)
            raise UnknownCapability(
                f"未知能力 '{cap_id}';已注册: {known or '(空 —— 部门尚未注册能力词汇)'}"
            ) from exc

    def has(self, cap_id: str) -> bool:
        return cap_id in self._items

    def list(self, *, dept: str | None = None) -> list[Capability]:
        items = self._items.values()
        if dept:
            items = [c for c in items if c.dept == dept]
        return sorted(items, key=lambda c: c.id)

    def ids(self) -> list[str]:
        return sorted(self._items)

    def clear(self) -> None:
        """Test hook."""
        with self._lock:
            self._items.clear()


capabilities = CapabilityRegistry()
