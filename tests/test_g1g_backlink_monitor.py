"""G1-G backlink_monitor — 外链采集工序。

多数用例是拒绝路径。一个会在拿不到数据时编个数字出来的采集器，比没有
采集器更危险：外链数补零会在趋势图上显示成"外链归零"，触发不存在的告警。
"""
from __future__ import annotations

import datetime as _dt
import json
from types import SimpleNamespace

import pytest

from seoagents.cron.seo_tasks import SEO_TASKS, _task_backlink_monitor
from seoagents.storage.snapshot_store import SnapshotStore


class _Resp:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text or json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class _Client:
    """替身 httpx.AsyncClient：余额走 get，采集走 post。"""

    def __init__(self, *, balance=50.0, summary=None, post_status=200,
                 balance_raises=False, post_raises=False):
        self._balance = balance
        self._summary = summary
        self._post_status = post_status
        self._balance_raises = balance_raises
        self._post_raises = post_raises

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, *a, **kw):
        if self._balance_raises:
            raise RuntimeError("余额端点不可达")
        return _Resp({"tasks": [{"result": [{"money": {"balance": self._balance}}]}]})

    async def post(self, *a, **kw):
        if self._post_raises:
            raise RuntimeError("采集端点不可达")
        if self._post_status != 200:
            return _Resp({}, status_code=self._post_status, text="upstream error")
        return _Resp(self._summary if self._summary is not None
                     else {"tasks": [{"result": [{}]}]})


@pytest.fixture()
def rt(tmp_path):
    store = SnapshotStore(str(tmp_path))
    return SimpleNamespace(
        config=SimpleNamespace(
            seo_credentials=SimpleNamespace(dataforseo_api_key="dGVzdDp0ZXN0"),
            storage=SimpleNamespace(data_dir=str(tmp_path)),
            data_dir=str(tmp_path),
            sites=SimpleNamespace(monitored_sites=[]),
        ),
        _store=store,
    )


def _patch_client(monkeypatch, client):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: client)


def _summary(**fields):
    return {"tasks": [{"result": [fields]}]}


SITE = "https://mejorsiptv.shop"


# ── 注册 ──────────────────────────────────────────────────────────────────
def test_task_is_registered_weekly():
    spec = SEO_TASKS.get("seo.backlink_monitor")
    assert spec is not None, "工序未注册"
    assert spec.cadence == "weekly", "外链是慢变量,日频刷新纯烧钱"
    assert spec.phase == "phase5"


# ── 花钱之前的拒绝 ────────────────────────────────────────────────────────
class TestRefusals:
    @pytest.mark.asyncio
    async def test_missing_credential_is_unavailable(self, rt):
        rt.config.seo_credentials.dataforseo_api_key = ""
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "凭证" in out["data"]["reason"]

    @pytest.mark.asyncio
    async def test_unexpanded_env_var_is_treated_as_missing(self, rt):
        rt.config.seo_credentials.dataforseo_api_key = "${DATAFORSEO_KEY}"
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"

    @pytest.mark.asyncio
    async def test_dry_run_is_the_default(self, rt):
        out = await _task_backlink_monitor(rt, SITE)
        assert out["data"]["dry_run"] is True
        assert out["data"]["estimated_cost_usd"] == 0.09

    @pytest.mark.asyncio
    async def test_dry_run_sends_nothing(self, rt, monkeypatch):
        sent = []

        class _Spy(_Client):
            async def post(self, *a, **kw):
                sent.append(a)
                return await super().post(*a, **kw)

        _patch_client(monkeypatch, _Spy(summary=_summary(backlinks=1)))
        await _task_backlink_monitor(rt, SITE)
        assert sent == [], "dry_run 竟然发出了请求 —— 那是真花钱"

    @pytest.mark.asyncio
    async def test_low_balance_refuses(self, rt, monkeypatch):
        _patch_client(monkeypatch, _Client(balance=1.0))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False, min_balance=5.0)
        assert out["data_status"] == "UNAVAILABLE"
        assert "余额" in out["data"]["reason"]

    @pytest.mark.asyncio
    async def test_balance_check_failure_refuses_conservatively(self, rt, monkeypatch):
        """余额查不到就不调 —— 未知消费比不采集更糟。"""
        _patch_client(monkeypatch, _Client(balance_raises=True))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "余额检查失败" in out["data"]["reason"]


# ── 目标域名解析 ──────────────────────────────────────────────────────────
class TestTargetParsing:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("given", [
        "https://mejorsiptv.shop",
        "http://mejorsiptv.shop/",
        "sc-domain:mejorsiptv.shop",
        "https://mejorsiptv.shop/blog/algo",
    ])
    async def test_strips_scheme_prefix_and_path(self, rt, given):
        out = await _task_backlink_monitor(rt, given)
        assert out["data"]["target"] == "mejorsiptv.shop"

    @pytest.mark.asyncio
    async def test_empty_target_is_refused(self, rt):
        out = await _task_backlink_monitor(rt, "", dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "目标域名" in out["data"]["reason"]


# ── 上游异常 ──────────────────────────────────────────────────────────────
class TestUpstreamFailures:
    @pytest.mark.asyncio
    async def test_non_200_is_unavailable(self, rt, monkeypatch):
        _patch_client(monkeypatch, _Client(post_status=502))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "502" in out["data"]["reason"]

    @pytest.mark.asyncio
    async def test_network_error_is_unavailable(self, rt, monkeypatch):
        _patch_client(monkeypatch, _Client(post_raises=True))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "请求异常" in out["data"]["reason"]

    @pytest.mark.asyncio
    async def test_malformed_response_is_unavailable(self, rt, monkeypatch):
        _patch_client(monkeypatch, _Client(summary={"tasks": []}))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert "响应结构异常" in out["data"]["reason"]

    @pytest.mark.asyncio
    async def test_empty_metrics_are_not_written(self, rt, monkeypatch):
        """核心指标全空 = 什么也没拿到,别把空壳写进历史表。"""
        _patch_client(monkeypatch, _Client(summary=_summary(rank=None)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "UNAVAILABLE"
        assert rt._store.backlink_history(site=SITE) == []


# ── 采集成功 ──────────────────────────────────────────────────────────────
class TestCollection:
    @pytest.mark.asyncio
    async def test_writes_real_metrics(self, rt, monkeypatch):
        _patch_client(monkeypatch, _Client(summary=_summary(
            backlinks=1523, referring_domains=87, rank=34.5,
            broken_backlinks=12, referring_main_domains=71,
        )))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data_status"] == "REAL"
        assert out["data"]["total_backlinks"] == 1523
        assert out["data"]["referring_domains"] == 87
        assert out["data"]["domain_rating"] == 34.5
        assert out["data"]["written"] is True

        rows = rt._store.backlink_history(site=SITE)
        assert len(rows) == 1
        assert rows[0]["total_backlinks"] == 1523
        assert rows[0]["data_status"] == "REAL"

    @pytest.mark.asyncio
    async def test_missing_field_stays_none_never_zero(self, rt, monkeypatch):
        """数据铁律:缺的字段保持 None。补零会把「没测到」说成「是零」。"""
        _patch_client(monkeypatch, _Client(summary=_summary(backlinks=100)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data"]["referring_domains"] is None
        assert out["data"]["domain_rating"] is None

    @pytest.mark.asyncio
    async def test_first_collection_leaves_delta_unknown(self, rt, monkeypatch):
        """首次采集没有比较基准 —— None 不是 0。报 0 会被读成「本周无变化」。"""
        _patch_client(monkeypatch, _Client(summary=_summary(
            backlinks=1000, referring_domains=50)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data"]["new_links"] is None
        assert out["data"]["lost_links"] is None
        assert out["data"]["compared_with"] is None


# ── 增减比对 ──────────────────────────────────────────────────────────────
class TestDelta:
    def _seed(self, rt, *, total, days_ago=7):
        day = (_dt.date.today() - _dt.timedelta(days=days_ago)).isoformat()
        rt._store.write_backlinks(site=SITE, total_backlinks=total,
                                  referring_domains=50, date=day)
        return day

    @pytest.mark.asyncio
    async def test_growth_becomes_new_links(self, rt, monkeypatch):
        day = self._seed(rt, total=1000)
        _patch_client(monkeypatch, _Client(summary=_summary(
            backlinks=1200, referring_domains=60)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data"]["new_links"] == 200
        assert out["data"]["lost_links"] == 0
        assert out["data"]["compared_with"] == day

    @pytest.mark.asyncio
    async def test_decline_becomes_lost_links(self, rt, monkeypatch):
        self._seed(rt, total=1000)
        _patch_client(monkeypatch, _Client(summary=_summary(
            backlinks=850, referring_domains=45)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data"]["lost_links"] == 150
        assert out["data"]["new_links"] == 0

    @pytest.mark.asyncio
    async def test_flat_week_reports_zero_not_none(self, rt, monkeypatch):
        """有基准且确实没变 —— 这时 0 才是真话。"""
        self._seed(rt, total=1000)
        _patch_client(monkeypatch, _Client(summary=_summary(
            backlinks=1000, referring_domains=50)))
        out = await _task_backlink_monitor(rt, SITE, dry_run=False)
        assert out["data"]["new_links"] == 0
        assert out["data"]["lost_links"] == 0
