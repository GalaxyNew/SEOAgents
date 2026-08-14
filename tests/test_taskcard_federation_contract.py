"""G1-I2 federation contract for task cards.

The engine existed but the federation could not see it: healthz probed three
subsystems and not the ledger, and the control tower's grid counted only
cross-department requests. These tests pin the contract that fixes that, and
in particular the rule that an unreachable ledger must say so rather than
report zero — a zero renders as "nothing to do today" on twelve dashboards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import dojocore.taskcard as tcmod
from dojocore.taskcard.models import CardStatus
from dojocore.taskcard.service import TaskCardService
from dojocore.taskcard.store import TaskCardStore
from seoagents.dashboard.server import create_app


@pytest.fixture()
def cards(tmp_path, monkeypatch, runtime):
    """Bind the process-wide singleton to a throwaway ledger.

    ``runtime`` is required, not incidental: it is what calls
    ``set_config_provider``. Without it the collab service raises "尚未注册配置
    提供者", ``inbox/summary`` takes its early-exit branch, and the task card
    fields under test are never reached.
    """
    svc = TaskCardService(TaskCardStore(tmp_path, dept="seo"), dept="seo")
    monkeypatch.setattr(tcmod, "_service", svc)
    yield svc
    monkeypatch.setattr(tcmod, "_service", None)


@pytest.fixture()
def client(cards):
    return TestClient(create_app())


def _card(cards, title="联邦契约测试卡", **kw):
    kw.setdefault("goal", "验证联邦投影")
    kw.setdefault("acceptance", ["端点返回 REAL"])
    return cards.open_card(title=title, actor="hermes", **kw)


# ── 健康灯 ────────────────────────────────────────────────────────────────
class TestHealthz:
    def test_subsystems_now_report_taskcard(self, client, cards):
        subs = client.get("/api/v1/healthz").json()["subsystems"]
        assert "taskcard" in subs, "账本挂了健康灯还绿着,正是这条要修的"
        assert subs["taskcard"].startswith("ok")

    def test_probe_counts_active_cards(self, client, cards):
        card = _card(cards)
        cards.assign(card.card_id, "seo-tech", actor="hermes")
        assert client.get("/api/v1/healthz").json()["subsystems"]["taskcard"] == "ok:1"

    def test_broken_ledger_degrades_but_does_not_kill_the_light(
        self, client, cards, monkeypatch
    ):
        """账本不是联邦核心 —— 丢台账转黄,丢 collab 才转红。"""
        def boom():
            raise RuntimeError("账本不可达")

        monkeypatch.setattr(tcmod, "get_taskcards", boom)
        body = client.get("/api/v1/healthz").json()
        assert body["subsystems"]["taskcard"].startswith("degraded")
        assert body["light"] == "yellow"
        assert body["status"] == "ok"


# ── inbox 摘要 ────────────────────────────────────────────────────────────
class TestInboxSummary:
    def test_summary_carries_taskcard_counts(self, client, cards):
        body = client.get("/api/v1/inbox/summary").json()
        assert "taskcards" in body
        assert body["taskcards"]["data_status"] == "REAL"

    def test_counts_are_real(self, client, cards):
        a = _card(cards, "在办卡")
        cards.assign(a.card_id, "seo-tech", actor="hermes")
        cards.move(a.card_id, CardStatus.IN_PROGRESS, actor="seo-tech")
        b = _card(cards, "阻塞卡")
        cards.assign(b.card_id, "seo-tech", actor="hermes")
        cards.move(b.card_id, CardStatus.BLOCKED, actor="seo-tech")

        tc = client.get("/api/v1/inbox/summary").json()["taskcards"]
        assert tc["total"] == 2
        assert tc["active"] == 2
        assert tc["blocked"] == 1

    def test_audit_flags_are_surfaced(self, client, cards):
        _card(cards, "缺验收标准的卡", acceptance=[])
        assert client.get("/api/v1/inbox/summary").json()["taskcards"]["audit_flagged"] >= 1

    def test_unavailable_ledger_says_so_instead_of_reporting_zero(
        self, client, cards, monkeypatch
    ):
        """数据铁律:拿不到就标 UNAVAILABLE,补零会被读成「今天没活」。"""
        def boom():
            raise RuntimeError("磁盘只读")

        monkeypatch.setattr(tcmod, "get_taskcards", boom)
        tc = client.get("/api/v1/inbox/summary").json()["taskcards"]
        assert tc["data_status"] == "UNAVAILABLE"
        assert "磁盘只读" in tc["reason"]
        assert "total" not in tc, "标了 UNAVAILABLE 还给数字,等于没标"

    def test_taskcards_survive_a_broken_collab(self, client, cards, monkeypatch):
        """邻居坏了不该让自己也隐形。

        collab 抛异常时端点原本整体早退,任务卡数据明明健在也一起消失 ——
        「联邦看不见台账」换了个形式又出现一次。两个数据源必须各自降级。
        """
        card = _card(cards, "collab 挂了也要看得见")
        cards.assign(card.card_id, "seo-tech", actor="hermes")

        import dojocore.collab as collab_mod

        def boom():
            raise RuntimeError("collab 库损坏")

        monkeypatch.setattr(collab_mod, "get_collab_service", boom)
        body = client.get("/api/v1/inbox/summary").json()
        assert body["data_status"] == "UNAVAILABLE"      # collab 那半如实标注
        assert body["taskcards"]["data_status"] == "REAL"  # 台账这半照常给
        assert body["taskcards"]["active"] == 1

    def test_collab_counts_are_untouched(self, client, cards):
        """新增字段不得改动既有口径 —— 宫格曾出现过「停滞>在办」的自相矛盾。"""
        body = client.get("/api/v1/inbox/summary").json()
        for key in ("in_progress", "delivered_today", "stalled", "blocked", "inbox"):
            assert key in body


# ── 联邦投影 ──────────────────────────────────────────────────────────────
class TestFederationProjection:
    def test_returns_real_projection(self, client, cards):
        card = _card(cards)
        cards.assign(card.card_id, "seo-tech", actor="hermes")
        body = client.get("/api/v1/taskcards/federation").json()
        assert body["data_status"] == "REAL"
        assert body["count"] == 1
        assert body["cards"][0]["card_id"] == card.card_id

    def test_projection_omits_evidence_and_meta(self, client, cards):
        """12 节点 × 15 秒轮询,不能为了宫格一行标题把证据链全拉过来。"""
        card = _card(cards)
        cards.assign(card.card_id, "seo-tech", actor="hermes")
        cards.add_evidence(card.card_id, "seo-tech", "一条很长的证据" * 50)
        projected = client.get("/api/v1/taskcards/federation").json()["cards"][0]
        assert "evidence" not in projected
        assert "meta" not in projected
        assert "goal" not in projected

    def test_audit_state_is_a_boolean_not_a_list(self, client, cards):
        bad = _card(cards, "问题卡", acceptance=[])
        cards.assign(bad.card_id, "seo-tech", actor="hermes")  # DRAFT 不在 active 内
        projected = client.get("/api/v1/taskcards/federation").json()["cards"][0]
        assert projected["has_audit_flags"] is True

    def test_active_is_the_default_scope(self, client, cards):
        keep = _card(cards, "在办")
        cards.assign(keep.card_id, "seo-tech", actor="hermes")
        gone = _card(cards, "已取消")
        cards.move(gone.card_id, CardStatus.CANCELLED, actor="hermes")
        ids = {c["card_id"] for c in
               client.get("/api/v1/taskcards/federation").json()["cards"]}
        assert keep.card_id in ids and gone.card_id not in ids

    def test_all_scope_includes_terminal_cards(self, client, cards):
        gone = _card(cards, "已取消")
        cards.move(gone.card_id, CardStatus.CANCELLED, actor="hermes")
        ids = {c["card_id"] for c in
               client.get("/api/v1/taskcards/federation?status=all").json()["cards"]}
        assert gone.card_id in ids

    def test_limit_is_honoured(self, client, cards):
        for i in range(5):
            c = _card(cards, f"卡{i}")
            cards.assign(c.card_id, "seo-tech", actor="hermes")
        assert client.get("/api/v1/taskcards/federation?limit=2").json()["count"] == 2

    def test_unavailable_ledger_degrades_without_500(
        self, client, cards, monkeypatch
    ):
        def boom():
            raise RuntimeError("账本不可达")

        monkeypatch.setattr(tcmod, "get_taskcards", boom)
        r = client.get("/api/v1/taskcards/federation")
        assert r.status_code == 200
        assert r.json()["data_status"] == "UNAVAILABLE"
        assert r.json()["cards"] == []


# ── 路由顺序 ──────────────────────────────────────────────────────────────
class TestRoutePrecedence:
    def test_federation_path_is_not_eaten_by_the_card_id_wildcard(
        self, client, cards
    ):
        """/taskcards/federation 与 /taskcards/{card_id} 同形。

        federation_router 先于 taskcard_router 注册,所以静态路径先匹配。
        若顺序颠倒,这里会拿到 404「任务卡不存在: federation」。
        """
        body = client.get("/api/v1/taskcards/federation").json()
        assert "cards" in body and "card_id" not in body

    def test_real_card_id_still_resolves(self, client, cards):
        card = _card(cards)
        body = client.get(f"/api/v1/taskcards/{card.card_id}").json()
        assert body["card_id"] == card.card_id
        assert "evidence" in body  # 单卡详情仍返回全文
