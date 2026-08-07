"""总控大屏模块历史存储。

逻辑运行按 (site_id, module_id, business_date) 幂等；每次实际执行追加 attempt，
不会覆盖旧的工作流/Hermes 证据。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from dojocore.quality import DataStatus
from seoagents.control_tower.models import MetricPoint, ModuleRun, utc_now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version       INTEGER PRIMARY KEY,
    applied_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS module_runs (
    module_run_id       TEXT PRIMARY KEY,
    site_id             TEXT NOT NULL,
    module_id           TEXT NOT NULL,
    business_date       TEXT NOT NULL,
    latest_attempt_no   INTEGER NOT NULL DEFAULT 0,
    latest_status       TEXT NOT NULL,
    latest_collected_at TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE(site_id, module_id, business_date)
);
CREATE INDEX IF NOT EXISTS idx_module_runs_latest
    ON module_runs(site_id, module_id, business_date DESC);

CREATE TABLE IF NOT EXISTS module_attempts (
    attempt_id           TEXT PRIMARY KEY,
    module_run_id        TEXT NOT NULL REFERENCES module_runs(module_run_id) ON DELETE CASCADE,
    attempt_no           INTEGER NOT NULL,
    data_status          TEXT NOT NULL CHECK(data_status IN ('REAL','DEGRADED','UNAVAILABLE','DISPUTED')),
    source               TEXT NOT NULL,
    data_window_json     TEXT NOT NULL,
    reason               TEXT,
    known_limitations_json TEXT NOT NULL,
    cross_validation     TEXT NOT NULL,
    single_source_risk   INTEGER NOT NULL CHECK(single_source_risk IN (0,1)),
    collected_at         TEXT NOT NULL,
    workflow_instance_id TEXT,
    timeline_node_id     TEXT,
    asset_id             TEXT,
    metrics_json         TEXT NOT NULL,
    dimensions_json      TEXT NOT NULL,
    findings_json        TEXT NOT NULL,
    schema_version       TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    UNIQUE(module_run_id, attempt_no)
);
CREATE INDEX IF NOT EXISTS idx_module_attempts_run
    ON module_attempts(module_run_id, attempt_no DESC);

CREATE TABLE IF NOT EXISTS metric_points (
    metric_point_id TEXT PRIMARY KEY,
    attempt_id      TEXT NOT NULL REFERENCES module_attempts(attempt_id) ON DELETE CASCADE,
    metric_key      TEXT NOT NULL,
    metric_label    TEXT NOT NULL,
    period_key      TEXT NOT NULL,
    window_start    TEXT NOT NULL,
    window_end      TEXT NOT NULL,
    value_num       REAL,
    value_text      TEXT,
    unit            TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    data_status     TEXT NOT NULL CHECK(data_status IN ('REAL','DEGRADED','UNAVAILABLE','DISPUTED'))
);
CREATE INDEX IF NOT EXISTS idx_metric_history
    ON metric_points(metric_key, period_key, window_end DESC);

CREATE TABLE IF NOT EXISTS module_findings (
    finding_id          TEXT PRIMARY KEY,
    attempt_id          TEXT NOT NULL REFERENCES module_attempts(attempt_id) ON DELETE CASCADE,
    finding_key         TEXT NOT NULL,
    severity            TEXT NOT NULL,
    title               TEXT NOT NULL,
    conclusion          TEXT NOT NULL,
    evidence_json       TEXT NOT NULL,
    recommendation      TEXT NOT NULL,
    expected_benefit    TEXT NOT NULL,
    verification_method TEXT NOT NULL,
    approval_required   INTEGER NOT NULL CHECK(approval_required IN (0,1))
);

CREATE TABLE IF NOT EXISTS inspection_runs (
    inspection_run_id TEXT PRIMARY KEY,
    site_id           TEXT NOT NULL,
    business_date     TEXT NOT NULL,
    data_status       TEXT NOT NULL CHECK(data_status IN ('REAL','DEGRADED','UNAVAILABLE','DISPUTED')),
    report_asset_id   TEXT,
    feishu_url        TEXT,
    payload_json      TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(site_id, business_date)
);

CREATE TABLE IF NOT EXISTS inspection_gates (
    inspection_run_id TEXT NOT NULL REFERENCES inspection_runs(inspection_run_id) ON DELETE CASCADE,
    module_run_id     TEXT NOT NULL REFERENCES module_runs(module_run_id),
    is_required       INTEGER NOT NULL CHECK(is_required IN (0,1)),
    PRIMARY KEY(inspection_run_id, module_run_id)
);
"""

_SCHEMA_LOCK = threading.Lock()


class ControlTowerStore:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.dir.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / "control_tower.db"
        self._lock = threading.Lock()
        # journal_mode and CREATE TABLE both acquire database-wide locks. A
        # Timeline pulse and an API request can construct stores at the same
        # instant, so initialise the schema behind a process-wide lock. Normal
        # reads/writes still rely on SQLite's cross-process locking.
        with _SCHEMA_LOCK, self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)",
                (1, utc_now()),
            )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def record_attempt(
        self,
        run: ModuleRun,
        *,
        metric_points: tuple[MetricPoint, ...] | list[MetricPoint] = (),
    ) -> dict[str, Any]:
        run.validate()
        points = tuple(metric_points)
        for point in points:
            point.validate()
            if point.data_status is DataStatus.UNAVAILABLE:
                raise ValueError("UNAVAILABLE 不应写成指标点；保持缺失即可")

        now = utc_now()
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT module_run_id,latest_attempt_no FROM module_runs "
                "WHERE site_id=? AND module_id=? AND business_date=?",
                (run.site_id, run.module_id, run.business_date),
            ).fetchone()
            if row is None:
                module_run_id = "MR-" + uuid.uuid4().hex[:16]
                attempt_no = 1
                conn.execute(
                    "INSERT INTO module_runs(module_run_id,site_id,module_id,business_date,"
                    "latest_attempt_no,latest_status,latest_collected_at,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        module_run_id, run.site_id, run.module_id, run.business_date,
                        attempt_no, run.data_status.value, run.collected_at, now, now,
                    ),
                )
            else:
                module_run_id = str(row["module_run_id"])
                attempt_no = int(row["latest_attempt_no"]) + 1
                conn.execute(
                    "UPDATE module_runs SET latest_attempt_no=?,latest_status=?,"
                    "latest_collected_at=?,updated_at=? WHERE module_run_id=?",
                    (attempt_no, run.data_status.value, run.collected_at, now, module_run_id),
                )

            attempt_id = "MA-" + uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO module_attempts(attempt_id,module_run_id,attempt_no,data_status,"
                "source,data_window_json,reason,known_limitations_json,cross_validation,"
                "single_source_risk,collected_at,workflow_instance_id,timeline_node_id,asset_id,"
                "metrics_json,dimensions_json,findings_json,schema_version,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attempt_id, module_run_id, attempt_no, run.data_status.value, run.source,
                    _json(run.data_window), run.reason, _json(run.known_limitations),
                    run.cross_validation, int(run.single_source_risk), run.collected_at,
                    run.workflow_instance_id, run.timeline_node_id, run.asset_id,
                    _json(run.metrics), _json(run.dimensions),
                    _json([f.to_dict() for f in run.findings]), run.schema_version, now,
                ),
            )
            for point in points:
                conn.execute(
                    "INSERT INTO metric_points(metric_point_id,attempt_id,metric_key,metric_label,"
                    "period_key,window_start,window_end,value_num,value_text,unit,dimensions_json,"
                    "data_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "MP-" + uuid.uuid4().hex[:16], attempt_id, point.metric_key,
                        point.metric_label, point.period_key, point.window_start, point.window_end,
                        point.value_num, point.value_text, point.unit, _json(point.dimensions),
                        point.data_status.value,
                    ),
                )
            for finding in run.findings:
                conn.execute(
                    "INSERT INTO module_findings(finding_id,attempt_id,finding_key,severity,title,"
                    "conclusion,evidence_json,recommendation,expected_benefit,verification_method,"
                    "approval_required) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "MF-" + uuid.uuid4().hex[:16], attempt_id, finding.finding_key,
                        finding.severity, finding.title, finding.conclusion, _json(finding.evidence),
                        finding.recommendation, finding.expected_benefit,
                        finding.verification_method, int(finding.approval_required),
                    ),
                )
        return {
            "module_run_id": module_run_id,
            "attempt_id": attempt_id,
            "attempt_no": attempt_no,
        }

    def latest(self, site_id: str, module_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT r.module_run_id,r.site_id,r.module_id,r.business_date,r.latest_attempt_no,"
                "a.* FROM module_runs r JOIN module_attempts a ON a.module_run_id=r.module_run_id "
                "AND a.attempt_no=r.latest_attempt_no WHERE r.site_id=? AND r.module_id=? "
                "ORDER BY r.business_date DESC,r.updated_at DESC LIMIT 1",
                (site_id, module_id),
            ).fetchone()
            return self._project_attempt(conn, row) if row else None

    def by_business_date(
        self, site_id: str, module_id: str, business_date: str
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT r.module_run_id,r.site_id,r.module_id,r.business_date,r.latest_attempt_no,"
                "a.* FROM module_runs r JOIN module_attempts a ON a.module_run_id=r.module_run_id "
                "AND a.attempt_no=r.latest_attempt_no WHERE r.site_id=? AND r.module_id=? "
                "AND r.business_date=?",
                (site_id, module_id, business_date),
            ).fetchone()
            return self._project_attempt(conn, row) if row else None

    def history(
        self, site_id: str, module_id: str, *, start: str | None = None,
        end: str | None = None, limit: int = 90,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 366))
        sql = (
            "SELECT r.module_run_id,r.site_id,r.module_id,r.business_date,r.latest_attempt_no,"
            "a.* FROM module_runs r JOIN module_attempts a ON a.module_run_id=r.module_run_id "
            "AND a.attempt_no=r.latest_attempt_no WHERE r.site_id=? AND r.module_id=?"
        )
        args: list[Any] = [site_id, module_id]
        if start:
            sql += " AND r.business_date>=?"; args.append(start)
        if end:
            sql += " AND r.business_date<=?"; args.append(end)
        sql += " ORDER BY r.business_date DESC LIMIT ?"; args.append(limit)
        with self._conn() as conn:
            return [self._project_attempt(conn, row) for row in conn.execute(sql, args).fetchall()]

    def attempts(self, module_run_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT r.module_run_id,r.site_id,r.module_id,r.business_date,r.latest_attempt_no,"
                "a.* FROM module_runs r JOIN module_attempts a ON a.module_run_id=r.module_run_id "
                "WHERE r.module_run_id=? ORDER BY a.attempt_no DESC",
                (module_run_id,),
            ).fetchall()
            return [self._project_attempt(conn, row) for row in rows]

    def _project_attempt(self, conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
        attempt_id = str(row["attempt_id"])
        points = [
            {
                "metric_key": p["metric_key"], "metric_label": p["metric_label"],
                "period_key": p["period_key"], "window_start": p["window_start"],
                "window_end": p["window_end"], "value_num": p["value_num"],
                "value_text": p["value_text"], "unit": p["unit"],
                "dimensions": json.loads(p["dimensions_json"]),
                "data_status": p["data_status"],
            }
            for p in conn.execute(
                "SELECT * FROM metric_points WHERE attempt_id=? ORDER BY metric_key,period_key",
                (attempt_id,),
            ).fetchall()
        ]
        return {
            "schema_version": row["schema_version"],
            "module_run_id": row["module_run_id"],
            "attempt_id": attempt_id,
            "attempt_no": row["attempt_no"],
            "latest_attempt_no": row["latest_attempt_no"],
            "site_id": row["site_id"],
            "module_id": row["module_id"],
            "business_date": row["business_date"],
            "data_status": row["data_status"],
            "source": row["source"],
            "data_window": json.loads(row["data_window_json"]),
            "reason": row["reason"],
            "known_limitations": json.loads(row["known_limitations_json"]),
            "cross_validation": row["cross_validation"],
            "single_source_risk": bool(row["single_source_risk"]),
            "collected_at": row["collected_at"],
            "workflow_instance_id": row["workflow_instance_id"] or "",
            "timeline_node_id": row["timeline_node_id"] or "",
            "asset_id": row["asset_id"] or "",
            "metrics": json.loads(row["metrics_json"]),
            "dimensions": json.loads(row["dimensions_json"]),
            "findings": json.loads(row["findings_json"]),
            "metric_points": points,
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


__all__ = ["ControlTowerStore"]
