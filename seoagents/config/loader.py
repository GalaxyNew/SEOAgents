"""ConfigStore (L7) — the single source of configuration truth.

DojoAgents contract honoured here:
  * typed reads  -> ``ConfigStore.snapshot()``
  * updates      -> ``raw()`` + ``deep_merge()`` + ``save_raw()``
  * dashboard    -> ``redacted()`` (secrets masked)
Default path ``~/.dojo/agents.yaml`` (override with env ``SEOAGENTS_CONFIG``).
``${ENV_VAR}`` references inside YAML values are expanded at load time.
File writes are serialized with portalocker to survive concurrent processes.
"""
from __future__ import annotations

import copy
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from dojocore.logging import LOGGER
from seoagents.config.models import SeoAgentsConfig
from seoagents.storage.locks import file_lock

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_KEY_PATTERN = re.compile(r"(api_key|password|secret|token|webhook_url)", re.IGNORECASE)

DEFAULT_CONFIG_PATH = "~/.dojo/agents.yaml"


def expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` references in strings."""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, Mapping):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict: ``patch`` merged over ``base`` recursively."""
    merged = copy.deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _redact(value: Any, key_hint: str = "") -> Any:
    if isinstance(value, Mapping):
        return {k: _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key_hint) for v in value]
    if isinstance(value, str) and value and _SECRET_KEY_PATTERN.search(key_hint):
        return value[:4] + "***" if len(value) > 4 else "***"
    return value


class ConfigStore:
    """Loads, caches, merges and persists ``agents.yaml``."""

    _instance: ConfigStore | None = None
    _instance_lock = threading.Lock()

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        env_path = os.environ.get("SEOAGENTS_CONFIG")
        self.path = Path(os.path.expanduser(str(path or env_path or DEFAULT_CONFIG_PATH)))
        self._lock = threading.RLock()
        self._raw: dict[str, Any] = {}
        self._snapshot: SeoAgentsConfig | None = None
        self.reload()

    # -- singleton access -------------------------------------------------
    @classmethod
    def get_instance(cls, path: str | os.PathLike[str] | None = None) -> ConfigStore:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(path)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            cls._instance = None

    # -- read paths --------------------------------------------------------
    def reload(self) -> None:
        with self._lock:
            if self.path.exists():
                try:
                    with open(self.path, "r", encoding="utf-8") as fh:
                        loaded = yaml.safe_load(fh) or {}
                    if not isinstance(loaded, dict):
                        raise ValueError(f"Config root must be a mapping, got {type(loaded).__name__}")
                    self._raw = loaded
                except Exception:
                    LOGGER.exception(f"Failed to parse config at {self.path}; using empty defaults")
                    self._raw = {}
            else:
                LOGGER.info(f"Config file {self.path} not found — running with built-in defaults (mock mode)")
                self._raw = {}
            self._snapshot = SeoAgentsConfig.from_dict(expand_env(self._raw))

    def snapshot(self) -> SeoAgentsConfig:
        """Typed, immutable configuration view. The ONLY sanctioned read path."""
        with self._lock:
            assert self._snapshot is not None
            return self._snapshot

    def raw(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._raw)

    def redacted(self) -> dict[str, Any]:
        """Raw config with secret-looking values masked — safe for dashboard exposure."""
        return _redact(self.raw())

    # -- write path --------------------------------------------------------
    def save_raw(self, data: Mapping[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            payload = yaml.safe_dump(dict(data), allow_unicode=True, sort_keys=False)
            with file_lock(str(self.path) + ".lock", timeout=10):
                tmp.write_text(payload, encoding="utf-8")
                os.replace(tmp, self.path)
            self._raw = copy.deepcopy(dict(data))
            self._snapshot = SeoAgentsConfig.from_dict(expand_env(self._raw))
            LOGGER.info(f"Configuration persisted to {self.path}")

    def update(self, patch: Mapping[str, Any]) -> None:
        """Deep-merge ``patch`` over the current raw config and persist."""
        self.save_raw(deep_merge(self.raw(), patch))
