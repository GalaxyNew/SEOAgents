"""Shared fixtures: isolated temp config + runtime in keyless mock mode."""
from __future__ import annotations

import textwrap

import pytest

from seoagents.agent.runtime import Runtime, reset_runtime
from seoagents.config import ConfigStore


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    config_path = tmp_path / "agents.yaml"
    # Paths are interpolated as POSIX: on Windows the backslashes in e.g. C:\Users\...
    # are invalid escape sequences inside a double-quoted YAML scalar.
    config_path.write_text(
        textwrap.dedent(
            f"""
            app: {{host: "127.0.0.1", port: 8765}}
            llm_providers:
              default_provider: anthropic
              anthropic: {{api_key: "", model: ""}}
            sites:
              site_url: "https://example.com"
              gsc_property: "sc-domain:example.com"
              brand_name: "Example"
              tracked_keywords: ["seo agent", "aeo monitoring"]
              content_pages:
                - url: "https://example.com/features"
                  anchor_candidates: ["seo agent", "features"]
                - url: "https://example.com/pricing"
                  anchor_candidates: ["pricing"]
            scoring: {{alpha: 0.4, beta: 0.2, gamma: 0.3, delta: 0.1, skill_compile_threshold: 150.0}}
            sandbox:
              allow_network_hosts: ["localhost", "127.0.0.1"]
              execution_timeout_seconds: 30
            scheduler: {{enabled: false}}
            storage:
              data_dir: "{(tmp_path / 'data').as_posix()}"
              skills_dir: "{(tmp_path / 'skills').as_posix()}"
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEOAGENTS_CONFIG", str(config_path))
    ConfigStore.reset_instance()
    reset_runtime()
    yield config_path
    ConfigStore.reset_instance()
    reset_runtime()


@pytest.fixture()
def runtime(temp_config) -> Runtime:
    return Runtime.from_config_store(ConfigStore.get_instance())
