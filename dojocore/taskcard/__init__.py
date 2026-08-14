"""Task cards — the federation's shared ledger of work in flight.

Replaces the Mac frontmatter-markdown task ledger retired on 2026-08-12. Cards
live in the owning department's SQLite; the control tower aggregates by polling
each node's ``/api/v1/taskcards``, so a department keeps running when the tower
does not.

    from dojocore.taskcard import get_taskcards, CardStatus

    svc = get_taskcards(dept="seo")
    card = svc.open_card(
        title="修复 GSC overview 500",
        goal="GSC 概览端点恢复 200 并返回真实数据",
        acceptance=["curl /api/v1/gsc/overview 返回 200", "data_status=REAL"],
        verify_cmd="curl -sf localhost:8000/api/v1/gsc/overview",
        level="L2",
    )
    svc.assign(card.card_id, owner="seo-tech", actor="hermes")
    svc.move(card.card_id, CardStatus.IN_PROGRESS, actor="seo-tech")
    svc.submit_for_review(card.card_id, actor="seo-tech")
    svc.verify(card.card_id)                       # runs verify_cmd for real
    svc.approve(card.card_id, reviewer="hermes")   # refuses if reviewer == owner
"""
from __future__ import annotations

import threading
from typing import Any

from dojocore.taskcard.models import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    CardError,
    CardLevel,
    CardPriority,
    CardStatus,
    Evidence,
    TaskCard,
    new_card_id,
)
from dojocore.taskcard.service import TaskCardService, VerifyResult
from dojocore.taskcard.store import TaskCardStore

_lock = threading.Lock()
_service: TaskCardService | None = None


def get_taskcards(config: Any = None, *, dept: str = "hm") -> TaskCardService:
    """Process-wide service singleton, mirroring ``get_timeline``."""
    global _service
    with _lock:
        if _service is None:
            if config is None:
                from dojocore.context import get_config
                config = get_config()
            timeline = None
            try:
                from dojocore.timeline import get_timeline
                timeline = get_timeline(config)
            except Exception:  # pragma: no cover - timeline is optional
                timeline = None
            _service = TaskCardService(
                TaskCardStore(config.storage.data_dir, dept=dept),
                dept=dept,
                timeline=timeline,
            )
        return _service


def reset_taskcards() -> None:
    """Test hook."""
    global _service
    with _lock:
        _service = None


__all__ = [
    "ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "CardError",
    "CardLevel",
    "CardPriority",
    "CardStatus",
    "Evidence",
    "TaskCard",
    "TaskCardService",
    "TaskCardStore",
    "VerifyResult",
    "get_taskcards",
    "new_card_id",
    "reset_taskcards",
]
