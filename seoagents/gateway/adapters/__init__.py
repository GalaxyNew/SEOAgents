"""Gateway adapters (L2) — outbound alert channels.

Subclass ``BaseGatewayAdapter`` per platform (DojoAgents convention). SEOAgents
ships the Feishu rich-card notifier; adding Slack/Telegram means one subclass.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GatewayEvent:
    platform: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class BaseGatewayAdapter(abc.ABC):
    platform = "base"

    def normalize_message(self, raw: dict[str, Any]) -> GatewayEvent:
        return GatewayEvent(platform=self.platform, kind="message", payload=raw)

    @abc.abstractmethod
    async def broadcast_evolution_alert(
        self, *, m_t_score: float, performance: float, links_fixed: int,
        extra: dict[str, Any] | None = None,
    ) -> bool: ...


__all__ = ["BaseGatewayAdapter", "GatewayEvent"]
