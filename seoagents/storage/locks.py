"""Cross-process file locking with graceful degradation (L7).

Uses portalocker when installed (multi-process safety). Falls back to a
process-local lock table so single-process deployments (and slim installs)
keep working — a one-time warning is emitted in that case.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from seoagents.logging import LOGGER

try:  # pragma: no cover - environment dependent
    import portalocker as _portalocker
except ImportError:  # pragma: no cover
    _portalocker = None

_local_locks: dict[str, threading.RLock] = {}
_registry_guard = threading.Lock()
_warned = False


@contextmanager
def file_lock(path: str, timeout: float = 10.0) -> Iterator[None]:
    """Serialize access to ``path`` across processes (or threads as fallback)."""
    global _warned
    if _portalocker is not None:
        with _portalocker.Lock(path, timeout=timeout):
            yield
        return
    if not _warned:
        LOGGER.warning(
            "portalocker not installed — falling back to in-process locks "
            "(fine for single-process runs; install portalocker for multi-process safety)"
        )
        _warned = True
    with _registry_guard:
        lock = _local_locks.setdefault(path, threading.RLock())
    with lock:
        yield


__all__ = ["file_lock"]
