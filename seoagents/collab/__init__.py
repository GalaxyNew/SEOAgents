"""Cross-department collaboration — inbox / outbox contract.

Departments are autonomous. Collaboration happens through a contract every
department implements, not through a shared task table: a request lands in the
recipient's inbox, the deliverable travels through the Asset Hub, and neither
side can write the other's copy.
"""
from __future__ import annotations

import threading
from typing import Any

from seoagents.collab.models import (
    CollabRequest,
    ExpectedDeliverable,
    Party,
    Priority,
    ProtocolError,
    RequestStatus,
    new_request_id,
)
from seoagents.collab.service import CollabService
from seoagents.collab.store import CollabStore

_lock = threading.Lock()
_service: CollabService | None = None


def get_collab_service(config: Any = None) -> CollabService:
    """Process-wide service, built from the active config on first use."""
    global _service
    with _lock:
        if _service is None:
            if config is None:
                from seoagents.agent.runtime import get_runtime
                config = get_runtime().config
            dept = getattr(getattr(config, "collab", None), "dept", "") or "seo"
            _service = CollabService(CollabStore(config.storage.data_dir), own_dept=dept)
        return _service


def reset_collab_service() -> None:
    """Test hook."""
    global _service
    with _lock:
        _service = None


__all__ = [
    "CollabRequest",
    "CollabService",
    "CollabStore",
    "ExpectedDeliverable",
    "Party",
    "Priority",
    "ProtocolError",
    "RequestStatus",
    "get_collab_service",
    "new_request_id",
    "reset_collab_service",
]
