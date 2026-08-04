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


@pytest.fixture(autouse=True)
def _authenticated_session(tmp_path, monkeypatch):
    """让测试里的 HTTP 请求带上有效会话。

    刻意不关掉鉴权中间件:关掉就变成在测「没有门的那个版本」,而线上是有门的。
    这里签一个真令牌注入 cookie,请求照样走完整的中间件。

    httpx 与 starlette 两种客户端都要打:测试里两种都有,只打一种会剩下
    一半用例莫名其妙地 401。
    """
    import time as _time

    import httpx as _httpx

    monkeypatch.setenv("SEOAGENTS_AUTH_DIR", str(tmp_path / "auth"))
    from seoagents.dashboard import auth as _auth

    users = _auth._load_users()
    users["admin"]["must_change"] = False   # 测试不走「首次必须改口令」流程
    _auth._save_users(users)
    cookie = f"{_auth.COOKIE}={_auth._sign('admin', int(_time.time()) + 3600)}"

    # collab 协议(/api/v1/*)走服务令牌而不是浏览器会话。给测试设一个固定值并
    # 随请求带上 —— 这样测的仍是「真的要令牌」的那条路径,而不是把闸门关掉。
    svc = "test-service-token"
    monkeypatch.setenv("SEOAGENTS_SERVICE_TOKEN", svc)

    def _patch(cls):
        orig = cls.request

        def wrapper(self, method, url, **kw):
            headers = dict(kw.pop("headers", None) or {})
            headers.setdefault("Cookie", cookie)
            headers.setdefault("X-Service-Token", svc)
            return orig(self, method, url, headers=headers, **kw)

        monkeypatch.setattr(cls, "request", wrapper)

    _patch(_httpx.AsyncClient)
    _patch(_httpx.Client)
