"""L7 ConfigStore — env expansion, deep merge, redaction, persistence."""
from __future__ import annotations

from seoagents.config import ConfigStore, deep_merge, expand_env


def test_env_expansion(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "s3cret")
    assert expand_env({"key": "${MY_SECRET}"}) == {"key": "s3cret"}
    assert expand_env("${UNDEFINED_VAR_XYZ}") == "${UNDEFINED_VAR_XYZ}"


def test_deep_merge_nested():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    patch = {"a": {"c": 20}, "e": 4}
    merged = deep_merge(base, patch)
    assert merged == {"a": {"b": 1, "c": 20}, "d": 3, "e": 4}
    assert base["a"]["c"] == 2  # original untouched


def test_snapshot_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SEOAGENTS_CONFIG", str(tmp_path / "missing.yaml"))
    ConfigStore.reset_instance()
    store = ConfigStore.get_instance()
    snap = store.snapshot()
    assert snap.app.port == 8765
    assert snap.scoring.alpha == 0.4
    assert not snap.llm_providers.anthropic.has_key
    ConfigStore.reset_instance()


def test_save_and_reload_roundtrip(temp_config):
    store = ConfigStore.get_instance()
    store.update({"app": {"port": 9999}, "gateway": {"feishu_webhook_url": "https://hook/xyz"}})
    assert store.snapshot().app.port == 9999

    fresh = ConfigStore(temp_config)
    assert fresh.snapshot().app.port == 9999
    assert fresh.snapshot().gateway.feishu_webhook_url == "https://hook/xyz"


def test_redaction_masks_secrets(temp_config):
    store = ConfigStore.get_instance()
    store.update(
        {"llm_providers": {"anthropic": {"api_key": "sk-ant-realkey123456"}},
         "gateway": {"feishu_webhook_url": "https://open.feishu.cn/hook/abc"}}
    )
    red = store.redacted()
    assert red["llm_providers"]["anthropic"]["api_key"] == "sk-a***"
    assert red["gateway"]["feishu_webhook_url"].endswith("***")
    # non-secret values untouched
    assert red["app"]["host"] == "127.0.0.1"
