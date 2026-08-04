"""资产台账 (L4) —— 谁产出了什么、存在哪、能不能回滚。

对齐 `03-资产中心` 的数据契约,但用 SQLite 落地而不是 Postgres:
Asset Hub 独立服务没有部署,为一张表拉起一套 Postgres 不划算。契约本身
一条不打折 —— 尤其 **L3 门禁是数据库级 CHECK 约束**,不是应用层的 if。

这条特意做成硬约束,是因为经验库里有一条原案:
`failures/2026-07-21-终验擅自降低已声明资产类别门禁.md` ——
教训写进了经验库但没变成门禁,于是又发生了一次。写在应用层的检查,
下一个人加个 `skip_check=True` 就绕过去了;写在 CHECK 里绕不过。

本体不存这里,存中央存储(asset_hub)。台账只记「它在哪、怎么取、
出事了怎么回滚」。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import sqlite3
import threading
from typing import Any

from dojocore.logging import LOGGER

_DB_PATH = os.environ.get(
    "ASSET_REGISTRY_DB", "/data/seo-stack/seoagents-data/assets.db"
)
_lock = threading.Lock()

CLASSES = ("DOC", "CODE", "DATA", "MEDIA", "PROMPT", "AUTO", "INFRA", "MODEL", "BIZ")
LEVELS = ("L0", "L1", "L2", "L3")
STATUSES = ("DECLARED", "PENDING_CATALOG", "CATALOGED", "ACTIVE",
            "DEPRECATED", "ARCHIVED", "REVOKED")
SENSITIVITY = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET")
DATA_STATUS = ("REAL", "DEGRADED", "UNAVAILABLE", "MIXED", "DISPUTED")

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS assets (
    asset_id          TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    class             TEXT NOT NULL CHECK (class IN {CLASSES}),
    level             TEXT NOT NULL CHECK (level IN {LEVELS}),
    status            TEXT NOT NULL CHECK (status IN {STATUSES}),
    task_id           TEXT NOT NULL,
    project           TEXT,

    owner_department  TEXT NOT NULL,
    owner_agent       TEXT NOT NULL,
    owner_hm          TEXT,

    location_type     TEXT NOT NULL CHECK (location_type IN
                        ('local','s3','gdrive','git','feishu','url','server')),
    location          TEXT NOT NULL,
    storage_node      TEXT,
    version           TEXT NOT NULL,
    checksum          TEXT,
    size_bytes        INTEGER,
    content_type      TEXT,

    tags              TEXT NOT NULL DEFAULT '[]',
    summary           TEXT NOT NULL,
    usage             TEXT NOT NULL,
    sensitivity       TEXT NOT NULL CHECK (sensitivity IN {SENSITIVITY}),

    data_status       TEXT NOT NULL DEFAULT 'REAL' CHECK (data_status IN {DATA_STATUS}),
    data_window       TEXT,

    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    verified_at       TEXT,
    verified_by       TEXT,
    source_evidence   TEXT NOT NULL,

    backup_location   TEXT,
    rollback          TEXT,
    review_cycle      TEXT,
    supersedes        TEXT REFERENCES assets(asset_id),

    -- L3 门禁:数据库级,应用层绕不过
    CONSTRAINT l3_requires_backup CHECK (
        level <> 'L3' OR (
            backup_location IS NOT NULL AND TRIM(backup_location) <> ''
            AND rollback IS NOT NULL AND TRIM(rollback) <> ''
            AND review_cycle IS NOT NULL AND TRIM(review_cycle) <> ''
        )
    ),
    CONSTRAINT checksum_shape CHECK (
        checksum IS NULL OR checksum LIKE 'sha256:%'
    )
);

CREATE INDEX IF NOT EXISTS idx_assets_task  ON assets(task_id);
CREATE INDEX IF NOT EXISTS idx_assets_class ON assets(class, level, status);
CREATE INDEX IF NOT EXISTS idx_assets_owner ON assets(owner_hm, owner_department);

CREATE TABLE IF NOT EXISTS asset_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   TEXT NOT NULL,
    event      TEXT NOT NULL CHECK (event IN
                 ('created','uploaded','verified','status_changed',
                  'accessed','revoked','linked','restored')),
    actor      TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{{}}',
    at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_asset ON asset_events(asset_id, at DESC);

CREATE TABLE IF NOT EXISTS asset_lineage (
    parent_id  TEXT NOT NULL REFERENCES assets(asset_id),
    child_id   TEXT NOT NULL REFERENCES assets(asset_id),
    relation   TEXT NOT NULL CHECK (relation IN
                 ('derived_from','supersedes','references','generated_by')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id, relation)
);
"""


def record_event(asset_id: str, event: str, *, actor: str,
                 payload: dict[str, Any] | None = None) -> None:
    """写一条审计。

    **只增不改**,没有更新和删除接口 —— 能改的审计等于没有审计。

    写失败只告警不抛错:资产已经登记成功了,却因为审计写不进去而报错,
    会让人以为登记失败并重试一次,反而制造出两份资产。
    """
    try:
        with _lock, _conn() as c:
            c.execute(
                "INSERT INTO asset_events (asset_id,event,actor,payload,at)"
                " VALUES (?,?,?,?,?)",
                (asset_id, event, actor,
                 json.dumps(payload or {}, ensure_ascii=False), _now()),
            )
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning(f"审计写入失败(不影响业务): {asset_id} {event}: {exc}")


def events(asset_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
    """查审计。不给 asset_id 就是全量时间线。"""
    sql = "SELECT * FROM asset_events"
    args: list[Any] = []
    if asset_id:
        sql += " WHERE asset_id = ?"
        args.append(asset_id)
    sql += " ORDER BY at DESC, id DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, args)]  # noqa: S608 - 列名固定
    for r in rows:
        try:
            r["payload"] = json.loads(r.get("payload") or "{}")
        except json.JSONDecodeError:
            r["payload"] = {}
    return rows


class AssetError(RuntimeError):
    """登记失败。约束违例会被翻译成人话再抛出。"""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(_SCHEMA)
    return c


def _next_id(cls: str) -> str:
    day = _dt.datetime.now().strftime("%Y%m%d")
    pfx = f"AST-{cls}-{day}-"
    with _conn() as c:
        row = c.execute(
            "SELECT asset_id FROM assets WHERE asset_id LIKE ? ORDER BY asset_id DESC LIMIT 1",
            (pfx + "%",),
        ).fetchone()
    n = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{pfx}{n:04d}"


def register(
    *,
    name: str,
    cls: str,
    level: str,
    task_id: str,
    owner_department: str,
    owner_agent: str,
    location: str,
    location_type: str = "s3",
    storage_node: str = "",
    summary: str,
    usage: str,
    source_evidence: str,
    version: str = "1.0",
    project: str = "",
    owner_hm: str = "",
    sensitivity: str = "INTERNAL",
    data_status: str = "REAL",
    data_window: str = "",
    content: bytes | None = None,
    size_bytes: int | None = None,
    content_type: str = "",
    tags: list[str] | None = None,
    backup_location: str = "",
    rollback: str = "",
    review_cycle: str = "",
    status: str = "DECLARED",
    supersedes: str = "",
) -> dict[str, Any]:
    """登记一份资产。

    L3 缺 backup_location / rollback / review_cycle 任一项都会被数据库拒绝,
    这里把约束违例翻译成能照着改的提示。
    """
    if cls not in CLASSES:
        raise AssetError(f"class 必须是 {list(CLASSES)} 之一,收到 '{cls}'")
    if level not in LEVELS:
        raise AssetError(f"level 必须是 {list(LEVELS)} 之一,收到 '{level}'")

    # 提前给出人话提示,不必等数据库报 CHECK 违例
    if level == "L3":
        missing = [n for n, v in (("backup_location", backup_location),
                                  ("rollback", rollback),
                                  ("review_cycle", review_cycle)) if not str(v).strip()]
        if missing:
            raise AssetError(
                f"L3 核心生产资产必须填 {missing}。"
                f"这是数据库级约束,不能靠降级为 L2 绕过 —— "
                f"若它确实不是核心生产资产,请在声明时就写 L2,而不是终验时改。"
            )

    checksum = f"sha256:{hashlib.sha256(content).hexdigest()}" if content else None
    size = size_bytes if size_bytes is not None else (len(content) if content else None)
    aid = _next_id(cls)
    now = _now()

    row = {
        "asset_id": aid, "name": name, "class": cls, "level": level, "status": status,
        "task_id": task_id, "project": project,
        "owner_department": owner_department, "owner_agent": owner_agent,
        "owner_hm": owner_hm or owner_agent,
        "location_type": location_type, "location": location, "storage_node": storage_node,
        "version": version, "checksum": checksum, "size_bytes": size,
        "content_type": content_type,
        "tags": json.dumps(tags or [], ensure_ascii=False),
        "summary": summary, "usage": usage, "sensitivity": sensitivity,
        "data_status": data_status, "data_window": data_window,
        "created_at": now, "updated_at": now,
        "verified_at": None, "verified_by": None, "source_evidence": source_evidence,
        "backup_location": backup_location or None,
        "rollback": rollback or None,
        "review_cycle": review_cycle or None,
        "supersedes": supersedes or None,
    }
    cols = ",".join(row)
    ph = ",".join("?" * len(row))
    with _lock, _conn() as c:
        try:
            c.execute(f"INSERT INTO assets ({cols}) VALUES ({ph})", tuple(row.values()))  # noqa: S608
        except sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "l3_requires_backup" in msg:
                raise AssetError(
                    "L3 门禁拒绝:backup_location / rollback / review_cycle 必须齐全"
                ) from exc
            raise AssetError(f"登记被拒: {msg}") from exc
        if supersedes:
            c.execute(
                "INSERT OR IGNORE INTO asset_lineage VALUES (?,?,?,?)",
                (supersedes, aid, "supersedes", now),
            )
    record_event(aid, "created", actor=owner_agent, payload={
        "level": level, "class": cls, "location": location,
        "storage_node": storage_node, "task_id": task_id,
        "backup_location": backup_location or None,
    })
    LOGGER.info(f"资产已登记 {aid} [{level}] {name}")
    return {"ok": True, "asset_id": aid, "level": level, "location": location,
            "checksum": checksum}


def link(parent_id: str, child_id: str, relation: str = "derived_from") -> dict[str, Any]:
    """记血缘。REAL 资产不该派生自非 REAL 的父资产 —— 这里做检查并拒绝。"""
    with _lock, _conn() as c:
        p = c.execute("SELECT data_status, level FROM assets WHERE asset_id=?", (parent_id,)).fetchone()
        ch = c.execute("SELECT data_status FROM assets WHERE asset_id=?", (child_id,)).fetchone()
        if not p or not ch:
            raise AssetError(f"父或子资产不存在: {parent_id} / {child_id}")
        if ch["data_status"] == "REAL" and p["data_status"] != "REAL":
            raise AssetError(
                f"不能让 REAL 资产派生自 {p['data_status']} 的父资产 "
                f"({parent_id}) —— 那会把不可信数据洗成可信的"
            )
        c.execute("INSERT OR IGNORE INTO asset_lineage VALUES (?,?,?,?)",
                  (parent_id, child_id, relation, _now()))
    record_event(child_id, "linked", actor="system",
                 payload={"parent": parent_id, "relation": relation})
    return {"ok": True, "parent": parent_id, "child": child_id, "relation": relation}


def get(asset_id: str) -> dict[str, Any] | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["lineage"] = {
            "parents": [dict(x) for x in c.execute(
                "SELECT parent_id, relation FROM asset_lineage WHERE child_id=?", (asset_id,))],
            "children": [dict(x) for x in c.execute(
                "SELECT child_id, relation FROM asset_lineage WHERE parent_id=?", (asset_id,))],
        }
        return d


def listing(*, level: str = "", cls: str = "", status: str = "",
            department: str = "", limit: int = 100) -> list[dict[str, Any]]:
    where, args = [], []
    for col, val in (("level", level), ("class", cls),
                     ("status", status), ("owner_department", department)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    sql = "SELECT * FROM assets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        rows = [dict(r) for r in c.execute(sql, args)]  # noqa: S608 - 列名为白名单
    for d in rows:
        d["tags"] = json.loads(d.get("tags") or "[]")
    return rows


def verify(asset_id: str, *, verified_by: str) -> dict[str, Any]:
    """终验。刻意不提供「降级 level」的入口 —— 声明是 L3 就得按 L3 验。"""
    with _lock, _conn() as c:
        r = c.execute("SELECT level, backup_location, rollback, review_cycle FROM assets"
                      " WHERE asset_id=?", (asset_id,)).fetchone()
        if not r:
            raise AssetError(f"资产不存在: {asset_id}")
        if r["level"] == "L3":
            missing = [k for k in ("backup_location", "rollback", "review_cycle")
                       if not (r[k] or "").strip()]
            if missing:
                raise AssetError(f"L3 资产缺 {missing},不得通过终验")
        c.execute("UPDATE assets SET status='ACTIVE', verified_at=?, verified_by=?,"
                  " updated_at=? WHERE asset_id=?",
                  (_now(), verified_by, _now(), asset_id))
    record_event(asset_id, "verified", actor=verified_by,
                 payload={"from": "DECLARED", "to": "ACTIVE"})
    return {"ok": True, "asset_id": asset_id, "status": "ACTIVE", "verified_by": verified_by}


def stats() -> dict[str, Any]:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
        by_level = {r[0]: r[1] for r in c.execute(
            "SELECT level, COUNT(*) FROM assets GROUP BY level")}
        by_status = {r[0]: r[1] for r in c.execute(
            "SELECT status, COUNT(*) FROM assets GROUP BY status")}
        unverified_l3 = c.execute(
            "SELECT COUNT(*) FROM assets WHERE level='L3' AND verified_at IS NULL").fetchone()[0]
        lineage = c.execute("SELECT COUNT(*) FROM asset_lineage").fetchone()[0]
    return {"total": total, "by_level": by_level, "by_status": by_status,
            "unverified_l3": unverified_l3, "lineage_edges": lineage, "db": _DB_PATH}


__all__ = ["CLASSES", "LEVELS", "STATUSES", "AssetError", "events", "get",
           "link", "listing", "record_event", "register", "stats", "verify"]
