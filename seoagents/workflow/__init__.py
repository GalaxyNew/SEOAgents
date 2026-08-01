"""Department workflow engine — pipelines composed from generic nodes."""
from __future__ import annotations

import threading
from typing import Any

from seoagents.workflow.engine import EngineError, WorkflowEngine
from seoagents.workflow.instance import InstanceStatus, NodeState, WorkflowInstance
from seoagents.workflow.nodes import (
    NODE_SPECS,
    FailurePolicy,
    NodeType,
    NodeValidationError,
    WorkflowNode,
)
from seoagents.workflow.registry import Department, DepartmentRegistry
from seoagents.workflow.store import WorkflowStore
from seoagents.workflow.template import TemplateError, WorkflowTemplate

_lock = threading.Lock()
_store: WorkflowStore | None = None
_registry: DepartmentRegistry | None = None


def get_workflow_store(config: Any = None) -> WorkflowStore:
    global _store
    with _lock:
        if _store is None:
            if config is None:
                from seoagents.agent.runtime import get_runtime
                config = get_runtime().config
            _store = WorkflowStore(config.storage.data_dir)
        return _store


def get_department_registry(config: Any = None) -> DepartmentRegistry:
    global _registry
    with _lock:
        if _registry is None:
            if config is None:
                from seoagents.agent.runtime import get_runtime
                config = get_runtime().config
            raw = getattr(config, "raw", None) or {}
            _registry = DepartmentRegistry.from_config(raw.get("collab", {}))
        return _registry


def reset_workflow_state() -> None:
    """Test hook."""
    global _store, _registry
    with _lock:
        _store = None
        _registry = None


__all__ = [
    "NODE_SPECS",
    "Department",
    "DepartmentRegistry",
    "EngineError",
    "FailurePolicy",
    "InstanceStatus",
    "NodeState",
    "NodeType",
    "NodeValidationError",
    "TemplateError",
    "WorkflowEngine",
    "WorkflowInstance",
    "WorkflowNode",
    "WorkflowStore",
    "WorkflowTemplate",
    "get_department_registry",
    "get_workflow_store",
    "reset_workflow_state",
]
