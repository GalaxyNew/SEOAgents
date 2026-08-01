"""Self-managed agent time — a timeline the agent keeps for itself.

Distinct from cron: cron is a fixed rhythm imposed from outside, a timeline is
what the agent commits to after looking at what it has already promised. Both
feed the same queue; only the author differs.
"""
from __future__ import annotations

import threading
from typing import Any

from dojocore.timeline.models import (
    UNREAD_STATES,
    NodeKind,
    NodeState,
    OnMiss,
    TimelineError,
    TimelineNode,
    new_node_id,
)
from dojocore.timeline.service import PlanLimits, TimelineService
from dojocore.timeline.store import TimelineStore

_lock = threading.Lock()
_service: TimelineService | None = None


def get_timeline(config: Any = None, *, owner: str = "hm") -> TimelineService:
    global _service
    with _lock:
        if _service is None:
            if config is None:
                from dojocore.context import get_config
                config = get_config()
            _service = TimelineService(
                TimelineStore(config.storage.data_dir, owner=owner), owner=owner
            )
        return _service


def reset_timeline() -> None:
    """Test hook."""
    global _service
    with _lock:
        _service = None


__all__ = [
    "UNREAD_STATES",
    "NodeKind",
    "NodeState",
    "OnMiss",
    "PlanLimits",
    "TimelineError",
    "TimelineNode",
    "TimelineService",
    "TimelineStore",
    "get_timeline",
    "new_node_id",
    "reset_timeline",
]
