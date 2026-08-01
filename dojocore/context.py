"""Config provider hook — how the framework reaches the host application.

Framework modules must not import a department package: that would make
``dojocore`` depend on ``seoagents``, and the next department could not use it
without dragging SEO along. Instead the host registers a provider once at
startup, and the framework asks for configuration through it.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

__all__ = ["get_config", "reset_config_provider", "set_config_provider"]

_lock = threading.Lock()
_provider: Callable[[], Any] | None = None


def set_config_provider(provider: Callable[[], Any]) -> None:
    """Register how to fetch the active configuration object."""
    global _provider
    with _lock:
        _provider = provider


def reset_config_provider() -> None:
    global _provider
    with _lock:
        _provider = None


def get_config() -> Any:
    if _provider is None:
        raise RuntimeError(
            "尚未注册配置提供者。宿主应用应在启动时调用 "
            "dojocore.context.set_config_provider(lambda: <config>)"
        )
    return _provider()
