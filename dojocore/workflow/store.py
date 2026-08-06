"""Template and instance persistence.

Built-in templates ship with the package; user templates live in the data dir
so a department can add its own pipeline without touching code — which is the
point of composing from generic nodes rather than writing a script per process.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml

from dojocore.logging import LOGGER
from dojocore.workflow.instance import InstanceStatus, NodeState, WorkflowInstance, _now
from dojocore.workflow.template import TemplateError, WorkflowTemplate

__all__ = ["WorkflowConflict", "WorkflowStore"]


class WorkflowConflict(RuntimeError):
    """A stale whole-instance write or an already-held dispatch claim."""

# Templates ship with the *department*, not the framework — the framework has
# no opinion about what a pipeline should contain.
def _dept_template_dir() -> Path | None:
    try:
        from dojocore.department import active_department
        return active_department().template_dir
    except Exception:  # noqa: BLE001 - store must work without a department
        return None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wf_instances (
    instance_id      TEXT PRIMARY KEY,
    template_id      TEXT NOT NULL,
    template_version TEXT NOT NULL,
    dept             TEXT NOT NULL,
    status           TEXT NOT NULL,
    parent_task      TEXT,
    payload          TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wf_status ON wf_instances(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_wf_tpl    ON wf_instances(template_id, template_version);
"""


class WorkflowStore:
    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.dir = Path(os.path.expanduser(str(data_dir)))
        self.user_templates = self.dir / "workflows"
        self.user_templates.mkdir(parents=True, exist_ok=True)
        self.db = self.dir / "workflows.db"
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)
            columns = {str(r["name"]) for r in conn.execute("PRAGMA table_info(wf_instances)")}
            if "revision" not in columns:
                conn.execute("ALTER TABLE wf_instances ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- templates ---------------------------------------------------------
    def _template_files(self) -> list[Path]:
        dept_dir = _dept_template_dir()
        shipped = sorted(dept_dir.glob("*.yaml")) if dept_dir and dept_dir.exists() else []
        return shipped + sorted(self.user_templates.glob("*.yaml"))

    def templates(self) -> list[WorkflowTemplate]:
        """User templates override built-ins with the same id."""
        found: dict[str, WorkflowTemplate] = {}
        for path in self._template_files():
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                tpl = WorkflowTemplate.from_dict(raw)
            except (yaml.YAMLError, TemplateError, KeyError) as exc:
                # A broken template must be visible, not silently skipped.
                LOGGER.error(f"工作流模板加载失败,已跳过: {path.name} — {exc}")
                continue
            found[tpl.id] = tpl
        return sorted(found.values(), key=lambda t: t.id)

    def template(self, template_id: str) -> WorkflowTemplate | None:
        return next((t for t in self.templates() if t.id == template_id), None)

    def save_template(self, tpl: WorkflowTemplate) -> Path:
        tpl.validate()
        path = self.user_templates / f"{tpl.id}.yaml"
        content = yaml.safe_dump(
            {
                    "id": tpl.id, "name": tpl.name, "version": tpl.version,
                    "dept": tpl.dept, "description": tpl.description,
                    "tags": list(tpl.tags),
                    "metadata": dict(tpl.metadata),
                    "nodes": [
                        {k: v for k, v in n.to_dict().items()
                         if k not in ("type_label", "runs_externally")}
                        for n in tpl.nodes
                    ],
            },
            allow_unicode=True, sort_keys=False,
        )
        # Atomic replace: a crash or full disk never leaves a half-written YAML.
        fd, tmp_name = tempfile.mkstemp(prefix=f".{tpl.id}.", suffix=".tmp", dir=self.user_templates)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        LOGGER.info(f"workflow template saved: {tpl.id} v{tpl.version} → {path}")
        return path

    def delete_template(self, template_id: str) -> bool:
        """Delete a user override; shipped templates remain immutable on disk.

        A built-in template may be edited by saving an override with the same
        id.  Deleting that override exposes the shipped version again.
        """
        path = self.user_templates / f"{template_id}.yaml"
        if not path.exists():
            return False
        path.unlink()
        LOGGER.info(f"workflow user template deleted: {template_id}")
        return True

    # -- instances ---------------------------------------------------------
    def save_instance(self, inst: WorkflowInstance) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision FROM wf_instances WHERE instance_id=?", (inst.instance_id,)
            ).fetchone()
            if row is None:
                if inst.revision != 0:
                    raise WorkflowConflict(
                        f"实例 {inst.instance_id} 不存在但 revision={inst.revision}"
                    )
                inst.revision = 1
                conn.execute(
                    "INSERT INTO wf_instances (instance_id,template_id,template_version,dept,"
                    "status,parent_task,payload,created_at,updated_at,revision) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (inst.instance_id, inst.template_id, inst.template_version, inst.dept,
                     inst.status.value, inst.parent_task,
                     json.dumps(inst.to_dict(), ensure_ascii=False),
                     inst.created_at, inst.updated_at, inst.revision),
                )
                return
            current = int(row["revision"])
            if current != inst.revision:
                raise WorkflowConflict(
                    f"实例 {inst.instance_id} 已由其他进程更新: expected revision "
                    f"{inst.revision}, current {current}"
                )
            inst.revision = current + 1
            conn.execute(
                "UPDATE wf_instances SET status=?,parent_task=?,payload=?,updated_at=?,revision=?"
                " WHERE instance_id=? AND revision=?",
                (inst.status.value, inst.parent_task,
                 json.dumps(inst.to_dict(), ensure_ascii=False), inst.updated_at,
                 inst.revision, inst.instance_id, current),
            )

    @staticmethod
    def _write_locked(conn: sqlite3.Connection, inst: WorkflowInstance, current: int) -> None:
        """Write an instance while the caller holds BEGIN IMMEDIATE."""
        inst.revision = current + 1
        inst.updated_at = _now()
        cur = conn.execute(
            "UPDATE wf_instances SET status=?,parent_task=?,payload=?,updated_at=?,revision=?"
            " WHERE instance_id=? AND revision=?",
            (inst.status.value, inst.parent_task,
             json.dumps(inst.to_dict(), ensure_ascii=False), inst.updated_at,
             inst.revision, inst.instance_id, current),
        )
        if cur.rowcount != 1:
            raise WorkflowConflict(f"实例 {inst.instance_id} CAS 更新失败")

    def authorize_start(self, instance_id: str) -> WorkflowInstance:
        """Persist the only authorization that permits Pulse/runtime dispatch."""
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload,revision FROM wf_instances WHERE instance_id=?", (instance_id,)
            ).fetchone()
            if row is None:
                raise KeyError(instance_id)
            inst = WorkflowInstance.from_dict(json.loads(row["payload"]))
            if inst.status in {InstanceStatus.CANCELLED, InstanceStatus.DONE, InstanceStatus.FAILED}:
                raise WorkflowConflict(f"实例已处于 {inst.status.value}")
            if not inst.context.get("start_authorized") or inst.status in {
                InstanceStatus.PENDING, InstanceStatus.PAUSED,
            }:
                inst.context["start_authorized"] = True
                inst.context.setdefault("start_authorized_at", _now())
                inst.status = InstanceStatus.RUNNING
                self._write_locked(conn, inst, int(row["revision"]))
            return inst

    def claim_ready_node(self, instance_id: str, node_id: str) -> WorkflowInstance | None:
        """CAS-claim one dependency-ready node before any external submit.

        This is the concurrency boundary shared by direct start, auto-start and
        Pulse.  The claim is persisted before POST /v1/runs, so only its holder
        may bind the returned run id.  A submit with an uncertain outcome remains
        claimed/UNKNOWN and is never silently re-armed.
        """
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload,revision FROM wf_instances WHERE instance_id=?", (instance_id,)
            ).fetchone()
            if row is None:
                return None
            inst = WorkflowInstance.from_dict(json.loads(row["payload"]))
            if not inst.context.get("start_authorized") or inst.status not in {
                InstanceStatus.RUNNING, InstanceStatus.BLOCKED,
            }:
                return None
            run = inst.runs.get(node_id)
            if run is None or run.state not in {NodeState.PENDING, NodeState.READY}:
                return None
            tpl = self.template_for_instance(inst)
            if tpl is None:
                return None
            node = tpl.node(node_id)
            if any(inst.runs[d].state not in {NodeState.DONE, NodeState.SKIPPED}
                   for d in node.depends_on):
                return None
            run.state = NodeState.DISPATCHING
            run.runtime_status = "DISPATCHING"
            run.dispatch_token = uuid.uuid4().hex
            run.started_at = run.started_at or _now()
            run.attempts += 1
            inst.status = InstanceStatus.RUNNING
            self._write_locked(conn, inst, int(row["revision"]))
            return inst

    def bind_dispatch(
        self, instance_id: str, node_id: str, token: str, *, run_id: str = "",
        error: str = "",
    ) -> WorkflowInstance:
        """Bind a Hermes acknowledgement, or preserve an uncertain submit."""
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload,revision FROM wf_instances WHERE instance_id=?", (instance_id,)
            ).fetchone()
            if row is None:
                raise KeyError(instance_id)
            inst = WorkflowInstance.from_dict(json.loads(row["payload"]))
            run = inst.runs[node_id]
            if run.dispatch_token != token or run.state is not NodeState.DISPATCHING:
                raise WorkflowConflict(f"节点 {node_id} dispatch claim 已失效")
            if run_id:
                run.runtime_run_id = run_id
                run.runtime_status = "RUNNING"
                run.state = NodeState.RUNNING
            else:
                run.runtime_status = "UNKNOWN"
                run.error = error or "Hermes submit outcome unacknowledged"
                # Keep DISPATCHING: UNKNOWN may already have caused a side effect,
                # therefore neither Pulse nor a direct start may retry it.
                inst.status = InstanceStatus.BLOCKED
            self._write_locked(conn, inst, int(row["revision"]))
            return inst

    def instance(self, instance_id: str) -> WorkflowInstance | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM wf_instances WHERE instance_id=?", (instance_id,)
            ).fetchone()
        return WorkflowInstance.from_dict(json.loads(row["payload"])) if row else None

    def template_for_instance(self, inst: WorkflowInstance) -> WorkflowTemplate | None:
        """Return the immutable DAG snapshot pinned when the instance started."""
        if inst.template_snapshot:
            try:
                return WorkflowTemplate.from_dict(inst.template_snapshot)
            except TemplateError as exc:
                LOGGER.error(f"实例 {inst.instance_id} 的模板快照损坏: {exc}")
                return None
        # Backward compatibility: use current template once; API callers persist
        # it into template_snapshot immediately before any further transition.
        return self.template(inst.template_id)

    def instances(
        self, *, status: str | None = None, template_id: str | None = None, limit: int = 100
    ) -> list[WorkflowInstance]:
        sql = "SELECT payload FROM wf_instances WHERE 1=1"
        args: list[Any] = []
        if status:
            sql += " AND status=?"; args.append(status)
        if template_id:
            sql += " AND template_id=?"; args.append(template_id)
        sql += " ORDER BY updated_at DESC LIMIT ?"; args.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [WorkflowInstance.from_dict(json.loads(r["payload"])) for r in rows]

    def delete_instance(self, instance_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM wf_instances WHERE instance_id=?", (instance_id,))
            return bool(cur.rowcount)
