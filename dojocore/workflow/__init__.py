"""Department workflow engine — pipelines composed from generic nodes."""
from __future__ import annotations

import threading
from typing import Any

from dojocore.workflow.engine import EngineError, WorkflowEngine
from dojocore.workflow.instance import InstanceStatus, NodeState, WorkflowInstance
from dojocore.workflow.nodes import (
    NODE_SPECS,
    FailurePolicy,
    NodeType,
    NodeValidationError,
    WorkflowNode,
)
from dojocore.workflow.registry import Department, DepartmentRegistry
from dojocore.workflow.store import WorkflowStore
from dojocore.workflow.template import TemplateError, WorkflowTemplate

_lock = threading.Lock()
_store: WorkflowStore | None = None
_registry: DepartmentRegistry | None = None


def get_workflow_store(config: Any = None) -> WorkflowStore:
    global _store
    with _lock:
        if _store is None:
            if config is None:
                from dojocore.context import get_config
                config = get_config()
            _store = WorkflowStore(config.storage.data_dir)
        return _store


def get_department_registry(config: Any = None) -> DepartmentRegistry:
    global _registry
    with _lock:
        if _registry is None:
            if config is None:
                from dojocore.context import get_config
                config = get_config()
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
