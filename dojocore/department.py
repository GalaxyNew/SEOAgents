"""Department profile — everything a department declares to become one.

Building the next department should mean writing one of these, not forking the
framework. A profile answers five questions:

    who am I            id, display name
    what can I do       capability vocabulary
    what do I do it with tool specs
    how do I work       workflow templates
    how do I score      metric engine

Everything else — the data-status contract, the inbox/outbox protocol, the
workflow engine, the tool executor and sandbox, config, storage, the dashboard
shell — is framework and is not re-implemented per department.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from dojocore.capability import Capability, capabilities

__all__ = ["DepartmentBuilder", "DepartmentProfile", "active_department", "departments"]


@runtime_checkable
class ToolProvider(Protocol):
    """Anything that can register tool specs into a registry."""

    def __call__(self, registry: Any, config: Any, sandbox: Any, store: Any = None) -> None:
        ...


@dataclass(frozen=True)
class DepartmentProfile:
    id: str
    display_name: str
    description: str = ""

    # what it can be asked to do
    capabilities: tuple[Capability, ...] = ()

    # how its tools get registered (called by the runtime composition root)
    register_tools: ToolProvider | None = None

    # where its pipeline templates live
    template_dir: Path | None = None

    # how it scores itself; None means "this department has no headline metric"
    metric_engine_factory: Callable[[Any], Any] | None = None

    # third-party tool catalog shown on its dashboard
    catalog_file: Path | None = None

    metadata: Mapping[str, Any] = field(default_factory=dict)

    def install(self) -> DepartmentProfile:
        """Contribute this department's vocabulary to the shared registry."""
        capabilities.register_many(self.capabilities)
        return self

    def capability_ids(self) -> list[str]:
        return sorted(c.id for c in self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "has_tools": self.register_tools is not None,
            "has_templates": self.template_dir is not None and self.template_dir.exists(),
            "has_metric_engine": self.metric_engine_factory is not None,
            "has_catalog": self.catalog_file is not None and self.catalog_file.exists(),
            **dict(self.metadata),
        }


class DepartmentBuilder:
    """Small helper so a department file reads as a declaration."""

    def __init__(self, dept_id: str, display_name: str, description: str = "") -> None:
        self._id = dept_id
        self._name = display_name
        self._desc = description
        self._caps: list[Capability] = []
        self._tools: ToolProvider | None = None
        self._templates: Path | None = None
        self._metric: Callable[[Any], Any] | None = None
        self._catalog: Path | None = None
        self._meta: dict[str, Any] = {}

    def capability(
        self, cap_id: str, label: str, *, description: str = "",
        result_schema: str = "", sla_hours: int = 24, comparable: bool = True,
        **metadata: Any,
    ) -> DepartmentBuilder:
        self._caps.append(
            Capability(
                id=cap_id, label=label, dept=self._id, description=description,
                result_schema=result_schema or cap_id, default_sla_hours=sla_hours,
                comparable=comparable, metadata=metadata,
            )
        )
        return self

    def tools(self, provider: ToolProvider) -> DepartmentBuilder:
        self._tools = provider
        return self

    def templates(self, path: Path | str) -> DepartmentBuilder:
        self._templates = Path(path)
        return self

    def metrics(self, factory: Callable[[Any], Any]) -> DepartmentBuilder:
        self._metric = factory
        return self

    def catalog(self, path: Path | str) -> DepartmentBuilder:
        self._catalog = Path(path)
        return self

    def meta(self, **kw: Any) -> DepartmentBuilder:
        self._meta.update(kw)
        return self

    def build(self) -> DepartmentProfile:
        return DepartmentProfile(
            id=self._id, display_name=self._name, description=self._desc,
            capabilities=tuple(self._caps), register_tools=self._tools,
            template_dir=self._templates, metric_engine_factory=self._metric,
            catalog_file=self._catalog, metadata=self._meta,
        )


class _DepartmentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, DepartmentProfile] = {}
        self._active: str | None = None
        self._lock = threading.Lock()

    def register(self, profile: DepartmentProfile, *, activate: bool = False) -> DepartmentProfile:
        with self._lock:
            self._items[profile.id] = profile.install()
            if activate or self._active is None:
                self._active = profile.id
        return profile

    def get(self, dept_id: str) -> DepartmentProfile | None:
        return self._items.get(dept_id)

    def list(self) -> list[DepartmentProfile]:
        return sorted(self._items.values(), key=lambda d: d.id)

    def activate(self, dept_id: str) -> DepartmentProfile:
        if dept_id not in self._items:
            raise KeyError(f"未注册的部门 '{dept_id}';已注册: {sorted(self._items)}")
        with self._lock:
            self._active = dept_id
        return self._items[dept_id]

    @property
    def active(self) -> DepartmentProfile | None:
        return self._items.get(self._active) if self._active else None

    def clear(self) -> None:
        """Test hook."""
        with self._lock:
            self._items.clear()
            self._active = None


departments = _DepartmentRegistry()


def active_department() -> DepartmentProfile:
    profile = departments.active
    if profile is None:
        raise RuntimeError(
            "当前进程未注册任何部门。部门包应在 import 时调用 "
            "departments.register(profile)"
        )
    return profile
