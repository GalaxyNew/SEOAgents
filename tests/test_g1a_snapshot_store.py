"""G1-A 数据层验收测试 —— 真跑，不 mock。

对应 T20260812-02 三条门禁：
  1. 4 张表建成
  2. seo_daily_snapshot UNIQUE(date,site,task_name) 去重生效
  3. 读写层可 import 且可被工具层调用
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")

from seoagents.storage.snapshot_store import SnapshotStore, VALID_DATA_STATUS  # noqa: E402

FAILS: list[str] = []
PASSES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSES if cond else FAILS).append(f"{name} :: {detail}")
    print(f"{'✅' if cond else '❌'} {name}" + (f"  → {detail}" if detail else ""))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="g1a-test-")
    store = SnapshotStore(tmp)

    # ── 门禁 1：4 张表建成 ────────────────────────────────────────────
    tables = store.table_names()
    want = {"seo_daily_snapshot", "keyword_pool", "backlink_history", "cwv_history"}
    check("G1A-1 四张表建成", want.issubset(set(tables)), f"got={sorted(want & set(tables))}")

    # ── 门禁 2：UNIQUE 约束真的拦住重复 ──────────────────────────────
    raw = sqlite3.connect(store.db_path)
    raw.execute(
        "INSERT INTO seo_daily_snapshot(date,site,task_name,data_json)"
        " VALUES('2026-08-12','test','dup_test','{}')"
    )
    raw.commit()
    hit_unique = False
    try:
        raw.execute(
            "INSERT INTO seo_daily_snapshot(date,site,task_name,data_json)"
            " VALUES('2026-08-12','test','dup_test','{}')"
        )
        raw.commit()
    except sqlite3.IntegrityError as e:
        hit_unique = "UNIQUE" in str(e).upper()
        detail = str(e)
    else:
        detail = "第二条插入居然成功了 = 约束失效"
    raw.close()
    check("G1A-2 UNIQUE 去重约束生效", hit_unique, detail)

    # ── 门禁 3：读写层可用 ───────────────────────────────────────────
    site = "https://example.test"
    task = "seo.gsc_performance"

    check("G1A-3a 首跑 should_skip=False", store.should_skip(site=site, task_name=task) is False)

    w = store.write_snapshot(
        site=site, task_name=task,
        data={"clicks": 123, "impressions": 4567, "ctr": 0.027},
        data_status="REAL",
    )
    check("G1A-3b 写入成功", w["written"] is True, json.dumps(w, ensure_ascii=False))

    check("G1A-3c 写后 should_skip=True（省 API 配额）",
          store.should_skip(site=site, task_name=task) is True)

    r = store.read_snapshot(site=site, task_name=task)
    check("G1A-3d 读回且 JSON 已解析",
          r is not None and r["data"]["clicks"] == 123 and r["data_status"] == "REAL",
          f"data={r['data'] if r else None}")

    # UNAVAILABLE 不该堵住当天重试
    store.write_snapshot(site=site, task_name="seo.aeo_probe", data={}, data_status="UNAVAILABLE")
    check("G1A-3e UNAVAILABLE 不 skip（允许重试）",
          store.should_skip(site=site, task_name="seo.aeo_probe") is False)

    # 非法状态必须抛错
    try:
        store.write_snapshot(site=site, task_name="bad", data={}, data_status="PROBABLY_FINE")
        bad_ok = False
    except ValueError:
        bad_ok = True
    check("G1A-3f 非法 data_status 被拒", bad_ok, f"合法集={sorted(VALID_DATA_STATUS)}")

    # overwrite=False 幂等
    store.write_snapshot(site=site, task_name=task, data={"clicks": 999}, overwrite=False)
    r2 = store.read_snapshot(site=site, task_name=task)
    check("G1A-3g overwrite=False 保留首条", r2["data"]["clicks"] == 123, f"clicks={r2['data']['clicks']}")

    # overwrite=True 覆盖
    store.write_snapshot(site=site, task_name=task, data={"clicks": 999})
    r3 = store.read_snapshot(site=site, task_name=task)
    check("G1A-3h overwrite=True 覆盖", r3["data"]["clicks"] == 999, f"clicks={r3['data']['clicks']}")

    # keyword_pool：COALESCE 保护已有真实值
    store.upsert_keywords(
        [
            {"keyword": "iptv espana", "search_volume": 8100, "cpc": 0.42,
             "difficulty": 31.0, "intent": "commercial", "cluster": "iptv-es"},
            {"keyword": "mejor iptv", "search_volume": 2400, "intent": "commercial"},
        ],
        site=site, source="dataforseo",
    )
    kws = store.query_keywords(site=site)
    check("G1A-3i keyword_pool 写入", len(kws) == 2, f"rows={[k['keyword'] for k in kws]}")

    store.upsert_keywords([{"keyword": "iptv espana", "search_volume": None, "cluster": "iptv-es-v2"}], site=site)
    k1 = [k for k in store.query_keywords(site=site) if k["keyword"] == "iptv espana"][0]
    check("G1A-3j 空值不抹掉已有真实搜索量(COALESCE)",
          k1["search_volume"] == 8100 and k1["cluster"] == "iptv-es-v2",
          f"volume={k1['search_volume']} cluster={k1['cluster']}")

    # backlink / cwv
    store.write_backlinks(site=site, total_backlinks=1520, referring_domains=88,
                          domain_rating=21.4, new_links=12, lost_links=3)
    bl = store.backlink_history(site=site)
    check("G1A-3k backlink_history 写读", len(bl) == 1 and bl[0]["referring_domains"] == 88)

    store.write_cwv(url=site, lcp=2210.0, inp=180.0, cls=0.04, fcp=1400.0, ttfb=320.0, performance=87)
    cw = store.cwv_history(url=site)
    check("G1A-3l cwv_history 写读", len(cw) == 1 and cw[0]["performance"] == 87)

    # 同日重跑 skip 语义（B 阶段依赖）
    lst = store.list_snapshots(site=site)
    check("G1A-3m list_snapshots 汇总", len(lst) >= 2, f"tasks={[x['task_name'] for x in lst]}")

    print("\n" + "=" * 60)
    print(f"PASS={len(PASSES)}  FAIL={len(FAILS)}")
    print(f"counts={store.counts()}")
    print(f"db={store.db_path}")
    if FAILS:
        print("\n失败项：")
        for f in FAILS:
            print("  -", f)
        return 1
    print("G1A_ALL_GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
