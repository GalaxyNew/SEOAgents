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
from pathlib import Path
from typing import Any

import yaml

from seoagents.logging import LOGGER
from seoagents.workflow.instance import WorkflowInstance
from seoagents.workflow.template import TemplateError, WorkflowTemplate

__all__ = ["WorkflowStore"]

_BUILTIN_DIR = Path(__file__).parent / "templates"

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

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- templates ---------------------------------------------------------
    def _template_files(self) -> list[Path]:
        return sorted(_BUILTIN_DIR.glob("*.yaml")) + sorted(self.user_templates.glob("*.yaml"))

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
        path.write_text(
            yaml.safe_dump(
                {
                    "id": tpl.id, "name": tpl.name, "version": tpl.version,
                    "dept": tpl.dept, "description": tpl.description,
                    "tags": list(tpl.tags),
                    "nodes": [
                        {k: v for k, v in n.to_dict().items()
                         if k not in ("type_label", "runs_externally")}
                        for n in tpl.nodes
                    ],
                },
                allow_unicode=True, sort_keys=False,
            ),
            encoding="utf-8",
        )
        LOGGER.info(f"workflow template saved: {tpl.id} v{tpl.version} → {path}")
        return path

    # -- instances ---------------------------------------------------------
    def save_instance(self, inst: WorkflowInstance) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO wf_instances (instance_id,template_id,template_version,dept,"
                "status,parent_task,payload,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(instance_id) DO UPDATE SET status=excluded.status,"
                " payload=excluded.payload, updated_at=excluded.updated_at",
                (inst.instance_id, inst.template_id, inst.template_version, inst.dept,
                 inst.status.value, inst.parent_task,
                 json.dumps(inst.to_dict(), ensure_ascii=False),
                 inst.created_at, inst.updated_at),
            )

    def instance(self, instance_id: str) -> WorkflowInstance | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload FROM wf_instances WHERE instance_id=?", (instance_id,)
            ).fetchone()
        return WorkflowInstance.from_dict(json.loads(row["payload"])) if row else None

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
