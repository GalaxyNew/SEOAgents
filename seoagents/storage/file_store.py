"""Atomic JSON/JSONL persistence primitives (L7).

Port of the DojoAgents ``file_store_base`` contract: every store in the project
that persists JSON MUST go through ``AtomicJsonStore`` / ``AtomicJsonlStore``
and raise ``FileStoreError`` on failure — no ad-hoc ``open()`` + ``json.dump``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator

from seoagents.logging import LOGGER
from seoagents.storage.locks import file_lock


class FileStoreError(RuntimeError):
    """Raised when a file store operation fails."""


class _BaseStore:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(os.path.expanduser(str(path)))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def _lock_path(self) -> str:
        return str(self.path) + ".lock"

    def _atomic_write(self, text: str) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with file_lock(self._lock_path, timeout=10):
                tmp.write_text(text, encoding="utf-8")
                os.replace(tmp, self.path)
        except Exception as exc:  # noqa: BLE001 - boundary translation
            LOGGER.exception(f"Atomic write failed for {self.path}")
            raise FileStoreError(f"write failed for {self.path}: {exc}") from exc


class AtomicJsonStore(_BaseStore):
    """Whole-document JSON store with atomic replace semantics."""

    def load(self, default: Any = None) -> Any:
        if not self.path.exists():
            return default
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise FileStoreError(f"read failed for {self.path}: {exc}") from exc

    def save(self, data: Any) -> None:
        self._atomic_write(json.dumps(data, ensure_ascii=False, indent=2))


class AtomicJsonlStore(_BaseStore):
    """Append-oriented JSONL store."""

    def append(self, record: dict[str, Any]) -> None:
        try:
            with file_lock(self._lock_path, timeout=10):
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            raise FileStoreError(f"append failed for {self.path}: {exc}") from exc

    def append_many(self, records: Iterable[dict[str, Any]]) -> None:
        for rec in records:
            self.append(rec)

    def iter_records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    LOGGER.warning(f"Skipping corrupt JSONL line in {self.path}")

    def tail(self, n: int) -> list[dict[str, Any]]:
        return list(self.iter_records())[-n:]
