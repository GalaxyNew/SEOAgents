"""Agent 异步任务 API (L2) —— 长任务不能走同步 HTTP。

一次带工具调用的 agent 对话动辄两三分钟(爬站 + Lighthouse + 多轮推理),
而 Cloudflare 的源站超时是 100 秒:超时后返回的是一张 HTML 错误页,
前端 ``JSON.parse`` 直接抛 ``Unexpected token '<'``。用户看到的是
"网络请求异常",实际上后端跑得好好的。

这里把它拆成:提交立刻返回 job_id → 前端轮询进度 → 完成后取结果。
每个 HTTP 请求都在毫秒级,不触碰任何网关超时;副作用是前端能实时看到
agent 正在调哪个工具,比原来干等着强。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request

from dojocore.logging import LOGGER
from seoagents.agent.runtime import get_runtime
from seoagents.dashboard.schemas import AgentTaskRequest
from seoagents.multi_agent.orchestrator import AUDITOR, HM, LINKER, WRITER, hm_system_prompt

router = APIRouter(prefix="/api/agent", tags=["agent-jobs"])

_ROLE_MAP = {"auditor": AUDITOR, "writer": WRITER, "linker": LINKER, "hm": HM}

def _jobs_db_path() -> str:
    return os.environ.get(
        "SEOAGENTS_CONVERSATIONS_DB",
        "/data/seo-stack/seoagents-data/conversations.db",
    )


_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS copilot_runs (
    job_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL,
    task TEXT NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    hermes_session_id TEXT NOT NULL,
    hermes_run_id TEXT NOT NULL DEFAULT '',
    reasoning_baseline INTEGER NOT NULL DEFAULT 0,
    queued_count INTEGER NOT NULL DEFAULT 0,
    progress_json TEXT NOT NULL DEFAULT '[]',
    final_text TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    result_ok INTEGER,
    final_persisted INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_copilot_runs_active
ON copilot_runs(owner, conversation_id, status, created_at DESC);
"""


def _runs_conn():
    import sqlite3

    conn = sqlite3.connect(_jobs_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript(_RUNS_SCHEMA)
    cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(copilot_runs)")}
    if "queued_count" not in cols:
        conn.execute(
            "ALTER TABLE copilot_runs ADD COLUMN queued_count INTEGER NOT NULL DEFAULT 0"
        )
    return conn


def _save_job(job: dict[str, Any]) -> None:
    now = time.time()
    with _runs_conn() as conn:
        conn.execute(
            """INSERT INTO copilot_runs (
               job_id,conversation_id,owner,status,task,role,provider,model,
               reasoning_effort,hermes_session_id,hermes_run_id,reasoning_baseline,queued_count,
               progress_json,final_text,error,result_ok,final_persisted,
               created_at,started_at,finished_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
              status=excluded.status, task=excluded.task, role=excluded.role,
              provider=excluded.provider, model=excluded.model,
              reasoning_effort=excluded.reasoning_effort,
              hermes_session_id=excluded.hermes_session_id,
              hermes_run_id=excluded.hermes_run_id,
              reasoning_baseline=excluded.reasoning_baseline,
              queued_count=excluded.queued_count,
              progress_json=excluded.progress_json, final_text=excluded.final_text,
              error=excluded.error, result_ok=excluded.result_ok,
              final_persisted=excluded.final_persisted,
              started_at=excluded.started_at, finished_at=excluded.finished_at,
              updated_at=excluded.updated_at""",
            (
                job["job_id"], job.get("conversation_id") or "",
                job.get("owner") or "unknown", job.get("status") or "queued",
                job.get("task") or "", job.get("role") or "hm",
                job.get("provider") or "", job.get("model") or "",
                job.get("reasoning_effort") or "auto",
                job.get("hermes_session_id") or "",
                job.get("run_id") or "", int(job.get("reasoning_baseline") or 0),
                int(job.get("queued_count") or 0),
                json.dumps(job.get("progress") or [], ensure_ascii=False),
                job.get("final_text") or "", job.get("error") or "",
                None if job.get("ok") is None else int(bool(job.get("ok"))),
                int(bool(job.get("final_persisted"))),
                float(job.get("created_at") or now), job.get("started_at"),
                job.get("finished_at"), now,
            ),
        )


def _load_job(job_id: str) -> dict[str, Any] | None:
    with _runs_conn() as conn:
        row = conn.execute("SELECT * FROM copilot_runs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["progress"] = json.loads(d.pop("progress_json") or "[]")
    except json.JSONDecodeError:
        d["progress"] = []
    d["ok"] = None if d.pop("result_ok") is None else bool(row["result_ok"])
    d["final_persisted"] = bool(d.get("final_persisted"))
    d["run_id"] = d.pop("hermes_run_id") or ""
    return d


def _load_active_job(conversation_id: str, owner: str) -> dict[str, Any] | None:
    with _runs_conn() as conn:
        row = conn.execute(
            "SELECT job_id FROM copilot_runs WHERE conversation_id=? AND owner=?"
            " AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
            (conversation_id, owner),
        ).fetchone()
    return _load_job(str(row["job_id"])) if row else None


def _load_job_for_owner(job_id: str, owner: str) -> dict[str, Any] | None:
    """The browser must never learn another owner's job existence."""
    with _runs_conn() as conn:
        row = conn.execute(
            "SELECT job_id FROM copilot_runs WHERE job_id=? AND owner=?",
            (job_id, owner),
        ).fetchone()
    return _load_job(job_id) if row else None


def _project_orphaned_run(job: dict[str, Any]) -> dict[str, Any]:
    """Recover the final transcript after a dashboard restart.

    Hermes keeps processing the session-bound turn independently.  If this
    process lost its asyncio task, the assistant's final session message is the
    durable settlement signal.  Otherwise expose UNKNOWN rather than guessing
    or replaying a possibly side-effecting turn.
    """
    if job.get("status") not in {"queued", "running"}:
        return job
    session_id = str(job.get("hermes_session_id") or "")
    baseline = int(job.get("reasoning_baseline") or 0)
    if not session_id:
        return job
    try:
        payload = _hermes_json("GET", f"/api/sessions/{session_id}/messages")
    except Exception:
        return job
    final_candidates = []
    for message in payload.get("data") or []:
        message_id = _message_id_num(message.get("id"))
        content = str(message.get("content") or "").strip()
        if (
            message_id > baseline
            and message.get("role") == "assistant"
            and content
            and not message.get("tool_calls")
        ):
            final_candidates.append((message_id, content))
    if not final_candidates:
        # Session SSE is attached to the dashboard process.  After that process
        # restarts there is no safe way to resume a possibly side-effecting turn;
        # expose UNKNOWN instead of pretending it is still active or replaying it.
        job.update(
            status="unknown",
            error="Dashboard 进程已重启，原运行无法安全续接；未自动重放。",
            finished_at=time.time(),
        )
        _save_job(job)
        return job
    _, text = max(final_candidates, key=lambda x: x[0])
    job.update(
        status="done", ok=True, error="", final_text=text,
        finished_at=time.time(), turns=1,
    )
    actual_runtime: dict[str, Any] = {}
    try:
        session_payload = _hermes_json("GET", f"/api/sessions/{session_id}")
        session = session_payload.get("session") or {}
        actual_runtime = {
            "model": session.get("model") or job.get("model") or "",
            "provider": job.get("provider") or "",
            "route_source": "session_recovery",
        }
    except Exception:
        actual_runtime = {}
    if actual_runtime:
        job["effective_runtime"] = actual_runtime
        job["model"] = actual_runtime.get("model") or job.get("model")
    if not job.get("final_persisted") and job.get("conversation_id"):
        try:
            from seoagents.dashboard.routers.conversations import append_agent_message_once

            job["final_persisted"] = bool(append_agent_message_once(
                str(job["conversation_id"]),
                owner=str(job.get("owner") or "unknown"),
                text=text,
                turns=1,
                elapsed=float(job["finished_at"] - float(job.get("started_at") or job.get("created_at") or job["finished_at"])),
                trace=[],
                idempotency_key=f"job:{job['job_id']}:recovery",
            ))
        except Exception:
            job["final_persisted"] = False
    _save_job(job)
    return job


# Hot-process projection.  The durable copilot_runs ledger remains authoritative
# across dashboard restarts; live asyncio tasks are intentionally process-local.
_JOBS: dict[str, dict[str, Any]] = {}
_CONVERSATION_LOCKS: dict[str, asyncio.Lock] = {}
_JOB_TTL_SECONDS = 3600
_MAX_JOBS = 200


def _conversation_lock(conversation_id: str) -> asyncio.Lock:
    return _CONVERSATION_LOCKS.setdefault(conversation_id, asyncio.Lock())


def _sweep() -> None:
    """清掉过期任务,别让内存无限涨。"""
    now = time.time()
    stale = [k for k, v in _JOBS.items() if now - v.get("created_at", now) > _JOB_TTL_SECONDS]
    for k in stale:
        _JOBS.pop(k, None)
    if len(_JOBS) > _MAX_JOBS:
        for k in sorted(_JOBS, key=lambda x: _JOBS[x].get("created_at", 0))[: len(_JOBS) - _MAX_JOBS]:
            _JOBS.pop(k, None)
    try:
        with _runs_conn() as conn:
            conn.execute(
                "DELETE FROM copilot_runs WHERE status='done' AND updated_at < ?",
                (now - _JOB_TTL_SECONDS,),
            )
            # A process restart loses the local task object.  Never replay a
            # possibly side-effecting turn automatically; its Hermes session
            # transcript is reconciled lazily by _project_orphaned_run.
            conn.execute(
                "UPDATE copilot_runs SET status='unknown', updated_at=?"
                " WHERE status IN ('queued','running') AND updated_at < ?",
                (now, now - _JOB_TTL_SECONDS),
            )
    except Exception:
        LOGGER.warning("Copilot run ledger sweep failed")


_MAX_PROGRESS = 60          # 一条对话的步骤上限,防止极端情况撑爆内存
_MODEL_OPTIONS_TTL_SECONDS = 60
_MODEL_OPTIONS_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
_HERMES_STEER_CAPABILITY: dict[str, Any] = {"at": 0.0, "enabled": False}
_REASONING_EFFORTS = {"auto"}

# Session-health guardrails.  The provider-facing window is not always the
# value advertised by a community model catalog (the current custom endpoint
# has returned a hard overflow around 400K despite a larger catalog entry), so
# message count and accumulated input tokens are deliberately conservative.
_CONTEXT_PREFLIGHT_MESSAGES = 360
_CONTEXT_PREFLIGHT_INPUT_TOKENS = 250_000
_CONTEXT_HARD_MESSAGES = 480
_CONTEXT_HARD_INPUT_TOKENS = 350_000
_SSE_RECOVERY_GRACE_SECONDS = 12.0


def _attach_progress(rt: Any, job: dict[str, Any], session_id: str) -> None:
    """把 agent 的进度事件收进任务记录,供前端轮询。

    **按 session_id 过滤**:事件总线是全局的,多个任务并发时不过滤会把
    别人的步骤显示到你这条对话里 —— 那比没有进度更糟,因为看起来是真的。
    """
    def _push(kind: str, text: str) -> None:
        prog = job.setdefault("progress", [])
        if len(prog) < _MAX_PROGRESS:
            prog.append({"kind": kind, "text": text, "ts": time.time()})

    def on_turn(ev: Any) -> None:
        if ev.payload.get("session_id") != session_id:
            return
        _push("turn", f"第 {ev.payload.get('turn')} 轮")

    def on_thinking(ev: Any) -> None:
        if ev.payload.get("session_id") != session_id:
            return
        _push("thinking", str(ev.payload.get("text") or "")[:600])

    def on_tool_start(ev: Any) -> None:
        if ev.payload.get("session_id") != session_id:
            return
        _push("tool_start", "调用 " + "、".join(ev.payload.get("tools") or []))

    def on_tool(ev: Any) -> None:
        if ev.payload.get("session_id") != session_id:
            return
        ok = ev.payload.get("ok")
        ms = ev.payload.get("latency_ms")
        _push("tool", f"{ev.payload.get('tool')} {'成功' if ok else '失败'}"
                      f"{f' · {ms}ms' if ms is not None else ''}")

    bus = rt.event_bus
    bus.subscribe("agent.turn", on_turn)
    bus.subscribe("agent.thinking", on_thinking)
    bus.subscribe("agent.tool_start", on_tool_start)
    bus.subscribe("agent.tool", on_tool)


def _hermes_api_settings() -> tuple[str, str]:
    return (
        os.environ.get("HERMES_API_URL", "http://172.19.0.1:8642").rstrip("/"),
        os.environ.get("HERMES_API_KEY", "").strip(),
    )


def _hermes_headers() -> dict[str, str]:
    _, api_key = _hermes_api_settings()
    if not api_key:
        raise RuntimeError("HERMES_API_KEY 未配置，拒绝退回第二个独立大脑")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _redact_hermes_error(text: Any) -> str:
    """Keep bearer/API values out of the dashboard run ledger and user UI."""
    import re

    value = str(text or "")
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s'\"]+", r"\1[REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key[=:\s]+)[^\s,;'\"]+", r"\1[REDACTED]", value)
    return value[:1000]


def _hermes_json(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url, _ = _hermes_api_settings()
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base_url + path, data=raw, method=method, headers=_hermes_headers())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = _redact_hermes_error(exc.read().decode("utf-8", errors="replace"))
        raise RuntimeError(f"Hermes API HTTP {exc.code}: {detail[:300]}") from exc


def _hermes_supports_session_steer() -> bool:
    now = time.time()
    if now - float(_HERMES_STEER_CAPABILITY.get("at") or 0) < 60:
        return bool(_HERMES_STEER_CAPABILITY.get("enabled"))
    try:
        payload = _hermes_json("GET", "/v1/capabilities")
        enabled = bool((payload.get("features") or {}).get("session_steer"))
    except Exception:
        enabled = False
    _HERMES_STEER_CAPABILITY.update(at=now, enabled=enabled)
    return enabled


def _model_options(*, refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    cached = _MODEL_OPTIONS_CACHE.get("data")
    if (
        not refresh
        and cached is not None
        and now - float(_MODEL_OPTIONS_CACHE.get("at") or 0) < _MODEL_OPTIONS_TTL_SECONDS
    ):
        return cached
    raw = _hermes_json("GET", "/api/model/options" + ("?refresh=1" if refresh else ""))
    rows = []
    non_chat_markers = (
        "image", "audio", "realtime", "embedding", "rerank", "whisper", "tts",
    )
    for provider in raw.get("providers") or []:
        models = [
            str(m) for m in (provider.get("models") or [])
            if str(m).strip()
            and not any(marker in str(m).lower() for marker in non_chat_markers)
        ]
        if not provider.get("authenticated") or not models:
            continue
        capabilities = provider.get("capabilities") or {}
        rows.append({
            "slug": str(provider.get("slug") or ""),
            "label": str(provider.get("name") or provider.get("slug") or ""),
            "is_current": bool(provider.get("is_current")),
            "models": models,
            "capabilities": {
                m: {
                    "fast": bool((capabilities.get(m) or {}).get("fast")),
                    "reasoning": bool((capabilities.get(m) or {}).get("reasoning")),
                    "reasoning_efforts": [
                        str(x).strip().lower()
                        for x in ((capabilities.get(m) or {}).get("reasoning_efforts") or [])
                        if str(x).strip()
                    ],
                    "reasoning_source": str(
                        (capabilities.get(m) or {}).get("reasoning_source") or "unavailable"
                    ),
                }
                for m in models
            },
        })
    data = {
        "providers": rows,
        "current": {
            "provider": str(raw.get("provider") or ""),
            "model": str(raw.get("model") or ""),
        },
    }
    _MODEL_OPTIONS_CACHE.update(at=now, data=data)
    return data


def _validated_runtime(
    req: AgentTaskRequest, *, saved: dict[str, str] | None = None
) -> tuple[str, str, str]:
    catalog = _model_options()
    current = catalog.get("current") or {}
    saved = saved or {}
    provider = str(req.provider or saved.get("provider") or current.get("provider") or "").strip()
    model = str(req.model or saved.get("model") or current.get("model") or "").strip()
    effort = str(req.reasoning_effort or saved.get("reasoning_effort") or "auto").strip().lower()
    if not effort:
        effort = "auto"
    provider_row = next(
        (p for p in catalog.get("providers") or [] if p.get("slug") == provider),
        None,
    )
    if provider_row is None or model not in (provider_row.get("models") or []):
        raise RuntimeError(f"模型不在 Hermes 已认证目录中: {provider}/{model}")
    capability = (provider_row.get("capabilities") or {}).get(model) or {}
    allowed_efforts = [str(x) for x in (capability.get("reasoning_efforts") or [])]
    if effort != "auto" and effort not in allowed_efforts:
        source = str(capability.get("reasoning_source") or "unavailable")
        if not allowed_efforts:
            raise RuntimeError(
                f"{provider}/{model} 未从官方能力目录声明可选推理强度"
                f" (source={source})；请选择 auto"
            )
        raise RuntimeError(
            f"{provider}/{model} 不支持推理强度 {effort}；"
            f"官方可选: {', '.join(allowed_efforts)}"
        )
    return provider, model, effort


@router.get("/model-options")
async def model_options(refresh: bool = Query(False)) -> dict[str, Any]:
    """Proxy Hermes' authenticated picker inventory without exposing its bearer key."""
    try:
        return await asyncio.to_thread(_model_options, refresh=refresh)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _message_id_num(value: Any) -> int:
    """Hermes message IDs are commonly numeric but remain safe if that changes."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _reasoning_items(payload: dict[str, Any], *, after_id: int = 0) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    last_id = after_id
    for message in payload.get("data") or []:
        message_id = _message_id_num(message.get("id"))
        last_id = max(last_id, message_id)
        if message_id <= after_id or message.get("role") != "assistant":
            continue
        text = str(message.get("reasoning") or message.get("reasoning_content") or "").strip()
        if text:
            items.append({
                "id": message_id,
                "text": text,
                "finish_reason": message.get("finish_reason") or "",
            })
    return items[-30:], last_id


def _append_progress(job: dict[str, Any], kind: str, text: str) -> None:
    """Append one bounded, durable public progress item."""
    clean = str(text or "").strip()
    if not clean:
        return
    progress = job.setdefault("progress", [])
    progress.append({"kind": kind, "text": clean[:12000], "ts": time.time()})
    del progress[:-_MAX_PROGRESS]
    try:
        _save_job(job)
    except Exception:
        LOGGER.warning("Copilot progress ledger update failed for %s", job.get("job_id"))


def _session_snapshot(session_id: str) -> dict[str, Any]:
    """Read the client-safe Hermes session row used for context budgeting."""
    try:
        payload = _hermes_json("GET", f"/api/sessions/{session_id}")
    except Exception:
        return {}
    session = payload.get("session") or {}
    return dict(session) if isinstance(session, dict) else {}


def _assistant_after_baseline(
    session_id: str,
    baseline: int,
) -> tuple[str, dict[str, Any]]:
    """Recover a settled assistant result that the SSE transport missed."""
    payload = _hermes_json("GET", f"/api/sessions/{session_id}/messages")
    candidate: tuple[int, str] | None = None
    for message in payload.get("data") or []:
        message_id = _message_id_num(message.get("id"))
        content = str(message.get("content") or "").strip()
        if (
            message_id > baseline
            and message.get("role") == "assistant"
            and content
            and not message.get("tool_calls")
        ):
            candidate = max(candidate or (0, ""), (message_id, content), key=lambda x: x[0])
    return (candidate[1] if candidate else ""), payload


async def _recover_assistant_after_baseline(
    session_id: str,
    baseline: int,
    *,
    grace_seconds: float = _SSE_RECOVERY_GRACE_SECONDS,
) -> str:
    """Poll briefly because the session DB flush may lag the terminal SSE edge."""
    deadline = time.monotonic() + max(0.0, grace_seconds)
    while True:
        try:
            text, _ = await asyncio.to_thread(
                _assistant_after_baseline, session_id, baseline
            )
        except Exception:
            text = ""
        if text:
            return text
        if time.monotonic() >= deadline:
            return ""
        await asyncio.sleep(0.75)


def _context_budget_state(session: dict[str, Any]) -> tuple[str, str]:
    """Return (state, evidence) using only the real persisted session counters."""
    try:
        messages = int(session.get("message_count") or 0)
    except (TypeError, ValueError):
        messages = 0
    try:
        input_tokens = int(session.get("input_tokens") or 0)
    except (TypeError, ValueError):
        input_tokens = 0
    evidence = f"Hermes 会话 {messages} 条消息 · 累计输入 {input_tokens:,} tokens"
    if messages >= _CONTEXT_HARD_MESSAGES or input_tokens >= _CONTEXT_HARD_INPUT_TOKENS:
        return "hard", evidence
    if messages >= _CONTEXT_PREFLIGHT_MESSAGES or input_tokens >= _CONTEXT_PREFLIGHT_INPUT_TOKENS:
        return "preflight", evidence
    return "ok", evidence


@router.get("/sessions/{conversation_id}/reasoning")
async def session_reasoning(
    conversation_id: str,
    request: Request,
    after_id: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Return bounded, real reasoning summaries persisted by current Hermes."""
    from seoagents.dashboard.routers.conversations import conversation_owned

    owner = getattr(request.state, "user", None) or "unknown"
    if not await asyncio.to_thread(conversation_owned, conversation_id, owner=owner):
        raise HTTPException(status_code=404, detail="对话不存在")
    session_id = f"seoagents-{conversation_id.strip()[:128]}"
    try:
        payload = await asyncio.to_thread(
            _hermes_json, "GET", f"/api/sessions/{session_id}/messages"
        )
    except Exception as exc:
        # A new dashboard conversation has no Hermes row until its first turn.
        if "404" in str(exc) or "session_not_found" in str(exc):
            return {"session_id": session_id, "items": [], "last_id": after_id}
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    items, last_id = _reasoning_items(payload, after_id=after_id)
    return {"session_id": session_id, "items": items, "last_id": last_id}


async def _run_hermes_job(
    job: dict[str, Any], task: str, conversation_id: str | None,
    provider: str, model: str, reasoning_effort: str,
) -> None:
    """Run one durable, session-bound Hermes SSE turn.

    The dashboard job remains the browser-facing projection, while Hermes owns
    the actual session transcript and emits reasoning/tool lifecycle events.
    Disconnecting the browser therefore does not cancel the provider turn.
    """
    base_url, api_key = _hermes_api_settings()
    if not api_key:
        raise RuntimeError("HERMES_API_KEY 未配置，拒绝退回第二个独立大脑")
    cid = (conversation_id or job["job_id"]).strip()[:128]
    session_id = f"seoagents-{cid}"
    job["hermes_session_id"] = session_id
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-Hermes-Session-Id": session_id,
        "X-Hermes-Session-Key": "agent:main:seoagents:hm",
        "Accept": "text/event-stream",
    }

    # Session-chat-stream requires a pre-existing session.  Creating the same
    # deterministic ID is idempotent from the dashboard's perspective; a 409
    # means another request already created it and is safe to continue.
    try:
        await asyncio.to_thread(
            _hermes_json,
            "POST",
            "/api/sessions",
            {"id": session_id, "source": "seoagents", "model": model, "provider": provider},
        )
    except Exception as exc:
        if "409" not in str(exc) and "session_exists" not in str(exc):
            raise
    await asyncio.to_thread(
        _hermes_json,
        "POST",
        f"/api/sessions/{session_id}/model",
        {
            "provider": provider,
            "model": model,
            "require_model_lock": True,
            **(
                {
                    "model_options": {
                        "reasoning": {
                            "enabled": reasoning_effort != "none",
                            "effort": reasoning_effort,
                        },
                    }
                }
                if reasoning_effort != "auto"
                else {}
            ),
        },
    )

    session_before = await asyncio.to_thread(_session_snapshot, session_id)
    budget_state, budget_evidence = _context_budget_state(session_before)
    job["context_budget"] = {
        "state": budget_state,
        "message_count": int(session_before.get("message_count") or 0),
        "input_tokens": int(session_before.get("input_tokens") or 0),
    }
    if budget_state == "hard":
        _append_progress(
            job,
            "compacting",
            f"上下文已超过安全线，Hermes 将先压缩再继续 · {budget_evidence}",
        )
    elif budget_state == "preflight":
        _append_progress(
            job,
            "compacting",
            f"上下文接近安全线，已启用预压缩保护 · {budget_evidence}",
        )

    # Establish the per-turn cursor before the request starts.  Without this,
    # a refresh would replay reasoning from older turns as if it were current.
    try:
        previous = await asyncio.to_thread(
            _hermes_json, "GET", f"/api/sessions/{session_id}/messages"
        )
        ids = []
        for item in previous.get("data") or []:
            try:
                ids.append(int(item.get("id") or 0))
            except (TypeError, ValueError):
                pass
        job["reasoning_baseline"] = max(ids, default=0)
        await asyncio.to_thread(_save_job, job)
    except Exception:
        job["reasoning_baseline"] = 0
        await asyncio.to_thread(_save_job, job)

    payload: dict[str, Any] = {"message": task}
    if reasoning_effort != "auto":
        payload["model_options"] = {
            "reasoning": {
                "enabled": reasoning_effort != "none",
                "effort": reasoning_effort,
            },
            "reasoning_effort": reasoning_effort,
        }

    final_text = ""
    assistant_delta_text = ""
    effective_runtime: dict[str, Any] = {}
    stream_error = ""
    current_event = ""
    data_lines: list[str] = []

    def consume_event(event_name: str, raw_data: str) -> bool:
        nonlocal final_text, assistant_delta_text, effective_runtime, stream_error
        try:
            event = json.loads(raw_data)
        except json.JSONDecodeError:
            return False
        job["run_id"] = event.get("run_id") or job.get("run_id")
        if event_name == "run.started":
            try:
                _save_job(job)
            except Exception:
                LOGGER.warning("Copilot run ledger update failed for %s", job.get("job_id"))
            return False
        if event_name == "message.started":
            return False
        if event_name == "assistant.delta":
            delta = str(event.get("delta") or "")
            if delta:
                assistant_delta_text = (assistant_delta_text + delta)[-200000:]
                # Model prose is a public assistant draft, not hidden chain of
                # thought.  Expose it separately from tool/reasoning progress.
                progress = job.setdefault("progress", [])
                if progress and progress[-1].get("kind") == "assistant":
                    progress[-1]["text"] = assistant_delta_text
                    progress[-1]["ts"] = time.time()
                else:
                    progress.append({
                        "kind": "assistant",
                        "text": assistant_delta_text,
                        "ts": time.time(),
                    })
                del progress[:-_MAX_PROGRESS]
                try:
                    _save_job(job)
                except Exception:
                    LOGGER.warning("Copilot assistant delta ledger update failed for %s", job.get("job_id"))
            return False
        if event_name in {"tool.progress", "reasoning.available"}:
            text = str(event.get("delta") or event.get("text") or "")
            tool_name = event.get("tool_name") or "_thinking"
            if text.strip() and tool_name == "_status":
                status_kind = str(event.get("kind") or "status")
                _append_progress(
                    job,
                    "compacting" if status_kind in {"compacting", "compacted"} else "status",
                    text,
                )
                return False
            if text.strip() and tool_name in {"_thinking", "thinking", "reasoning"}:
                prog = job.setdefault("progress", [])
                if prog and prog[-1].get("kind") == "thinking":
                    prog[-1]["text"] = (str(prog[-1].get("text") or "") + text)[-12000:]
                    prog[-1]["ts"] = time.time()
                else:
                    prog.append({
                        "kind": "thinking",
                        "text": text[:12000],
                        "ts": time.time(),
                    })
                del prog[:-_MAX_PROGRESS]
                # Persist each reasoning event. Browser polling is still the
                # transport, but refresh/restart can now recover the same trail.
                try:
                    _save_job(job)
                except Exception:
                    LOGGER.warning("Copilot reasoning ledger update failed for %s", job.get("job_id"))
            return False
        if event_name in {"tool.started", "tool.completed", "tool.failed"}:
            kind = "tool_start" if event_name == "tool.started" else "tool"
            tool = event.get("tool") or event.get("tool_name") or "unknown"
            preview = str(event.get("preview") or "").strip()
            suffix = f" · {preview[:160]}" if preview else ""
            job.setdefault("progress", []).append({
                "kind": kind,
                "text": f"{tool} {event_name.split('.', 1)[1]}{suffix}",
                "ts": time.time(),
            })
            del job["progress"][:-_MAX_PROGRESS]
            try:
                _save_job(job)
            except Exception:
                LOGGER.warning("Copilot progress ledger update failed for %s", job.get("job_id"))
            return False
        if event_name == "assistant.completed":
            final_text = str(event.get("content") or "").strip()
            effective_runtime = event.get("runtime") or effective_runtime
            return False
        if event_name == "run.completed":
            final_text = (
                final_text
                or str(event.get("content") or "").strip()
                or assistant_delta_text.strip()
            )
            effective_runtime = event.get("runtime") or effective_runtime
            job["effective_runtime"] = effective_runtime
            return True
        if event_name == "error":
            stream_error = str(event.get("message") or "Hermes stream error")
            return True
        return event_name == "done"

    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/sessions/{session_id}/chat/stream",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = _redact_hermes_error((await resp.aread()).decode("utf-8", errors="replace"))
                    raise RuntimeError(f"Hermes session SSE HTTP {resp.status_code}: {body[:300]}")
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                    elif line == "" and data_lines:
                        should_stop = consume_event(current_event, "\n".join(data_lines))
                        current_event, data_lines = "", []
                        if should_stop:
                            break
    except Exception as exc:
        raise RuntimeError(_redact_hermes_error(exc)) from exc

    if not final_text:
        _append_progress(job, "status", "SSE 终态缺失，正在从 Hermes 会话记录回读结果…")
        final_text = await _recover_assistant_after_baseline(
            session_id,
            int(job.get("reasoning_baseline") or 0),
        )
        if final_text:
            _append_progress(job, "status", "已从 Hermes 持久会话恢复最终结果")
    if not final_text:
        detail = stream_error or "SSE 未给出终态，Hermes 会话回读也没有最终 assistant 消息"
        raise RuntimeError(detail)
    if final_text and not effective_runtime:
        # A recovered terminal message proves completion, but not provider
        # identity.  Keep the requested lock as accepted/DEGRADED evidence;
        # never invent an actual runtime from an absent terminal event.
        effective_runtime = {
            "provider": provider,
            "model": model,
            "route_source": "session_message_recovery",
            "model_lock": "accepted",
        }
        _append_progress(
            job,
            "status",
            "最终内容已恢复；运行时终态元数据缺失，按已接受的会话模型锁记录",
        )
    if (
        effective_runtime.get("provider") != provider
        or effective_runtime.get("model") != model
    ):
        raise RuntimeError(
            "Hermes confirmed model lock runtime mismatch: "
            f"requested={provider}/{model} actual="
            f"{effective_runtime.get('provider')}/{effective_runtime.get('model')}"
        )
    job.update(
        status="done",
        ok=True,
        error="",
        final_text=final_text,
        turns=1,
        trace=[],
        backend="hermes-session-sse",
        model=effective_runtime.get("model") or model,
        provider=effective_runtime.get("provider") or provider,
        reasoning_effort=reasoning_effort,
        effective_runtime=effective_runtime,
        finished_at=time.time(),
    )


async def _run_job(
    job_id: str, task: str, role_name: str, conversation_id: str | None = None,
    provider: str = "", model: str = "", reasoning_effort: str = "auto",
    owner: str = "unknown",
) -> None:
    job = _JOBS[job_id]
    job["status"] = "running"
    job["started_at"] = time.time()
    job["progress"] = [{
        "kind": "status",
        "text": f"已接入当前 Hermes · {provider}/{model} · {reasoning_effort}",
        "ts": time.time(),
    }]
    await asyncio.to_thread(_save_job, job)
    try:
        if role_name == "hm":
            from seoagents.dashboard.routers.conversations import (
                append_agent_message_once,
                claim_next_prompt,
                finish_prompt,
            )

            current_task = task
            current_provider = provider
            current_model = model
            current_effort = reasoning_effort
            current_prompt_id: str | None = None
            while True:
                job.update(
                    status="running",
                    task=current_task,
                    provider=current_provider,
                    model=current_model,
                    reasoning_effort=current_effort,
                    progress=[{
                        "kind": "status",
                        "text": f"已接入当前 Hermes · {current_provider}/{current_model} · {current_effort}",
                        "ts": time.time(),
                    }],
                    final_text="",
                    error="",
                    ok=None,
                    final_persisted=False,
                    finished_at=None,
                )
                await asyncio.to_thread(_save_job, job)
                turn_started_at = time.time()
                try:
                    await _run_hermes_job(
                        job, current_task, conversation_id,
                        current_provider, current_model, current_effort,
                    )
                    if conversation_id:
                        persisted = await asyncio.to_thread(
                            append_agent_message_once,
                            conversation_id,
                            owner=owner,
                            text=str(job.get("final_text") or "任务处理完毕。"),
                            turns=int(job.get("turns") or 1),
                            elapsed=float(job.get("finished_at", time.time()) - turn_started_at),
                            trace=list(job.get("trace") or []),
                            idempotency_key=f"job:{job_id}:{current_prompt_id or 'initial'}",
                        )
                        job["final_persisted"] = bool(persisted)
                    if current_prompt_id:
                        await asyncio.to_thread(finish_prompt, current_prompt_id, status="done")
                except Exception:
                    if current_prompt_id:
                        await asyncio.to_thread(finish_prompt, current_prompt_id, status="failed")
                    raise
                await asyncio.to_thread(_save_job, job)

                if not conversation_id:
                    job["status"] = "done"
                    await asyncio.to_thread(_save_job, job)
                    break
                # Queue submission and final settlement share this lock.  A
                # follow-up is therefore either claimed here, or its submitter
                # sees a terminal job and receives 409 — never silently stranded.
                async with _conversation_lock(conversation_id):
                    queued = await asyncio.to_thread(
                        claim_next_prompt, conversation_id, owner=owner
                    )
                    if not queued:
                        job["status"] = "done"
                        await asyncio.to_thread(_save_job, job)
                        break
                current_prompt_id = str(queued["id"])
                current_task = str(queued["text"])
                current_provider = str(queued["provider"])
                current_model = str(queued["model"])
                current_effort = str(queued["reasoning_effort"] or "auto")
                job["queued_count"] = max(0, int(job.get("queued_count") or 1) - 1)
            LOGGER.info(f"agent job {job_id} 完成: backend=hermes-session-sse ok=True")
            return

        rt = get_runtime()
        session_id = f"job_{job_id}"
        _attach_progress(rt, job, session_id)
        role = _ROLE_MAP.get(role_name)
        if role is HM:
            system = hm_system_prompt()
        elif role:
            system = role.system_prompt
        else:
            system = "role=default 你是 SEOAgents 的通用 SEO 智能体。"

        result = await rt.loop.run(
            task,
            system=system,
            allowed_tools=set(role.allowed_tools) if role and role.allowed_tools else None,
            session_id=session_id,
        )
        job.update(
            status="done",
            ok=result.ok,
            error=result.error,
            final_text=result.final_text,
            turns=result.turns,
            trace=result.trace_dicts(),
            finished_at=time.time(),
        )
        if conversation_id:
            from seoagents.dashboard.routers.conversations import append_agent_message_once

            persisted = await asyncio.to_thread(
                append_agent_message_once,
                conversation_id,
                owner=owner,
                text=str(result.final_text or "任务处理完毕。"),
                turns=int(result.turns or 1),
                elapsed=float(job.get("finished_at", time.time()) - job.get("started_at", time.time())),
                trace=list(job.get("trace") or []),
                idempotency_key=f"job:{job_id}:legacy",
            )
            job["final_persisted"] = bool(persisted)
        await asyncio.to_thread(_save_job, job)
        LOGGER.info(f"agent job {job_id} 完成: ok={result.ok} turns={result.turns}")
    except Exception as exc:  # noqa: BLE001 - 任务失败要如实记录,不能让轮询方永远等
        LOGGER.warning(f"agent job {job_id} 异常: {type(exc).__name__}: {_redact_hermes_error(exc)}")
        job.update(
            status="done",
            ok=False,
            error=f"{type(exc).__name__}: {_redact_hermes_error(exc)}",
            final_text="",
            turns=0,
            trace=[],
            finished_at=time.time(),
        )
        if conversation_id:
            from seoagents.dashboard.routers.conversations import append_agent_message_once

            persisted = await asyncio.to_thread(
                append_agent_message_once,
                conversation_id,
                owner=owner,
                text=f"⚠️ 执行失败: {job['error']}",
                turns=0,
                elapsed=float(job.get("finished_at", time.time()) - job.get("started_at", time.time())),
                trace=[],
                idempotency_key=f"job:{job_id}:error",
            )
            job["final_persisted"] = bool(persisted)
        await asyncio.to_thread(_save_job, job)


@router.post("/jobs", status_code=202)
async def submit_job(req: AgentTaskRequest, request: Request) -> dict[str, Any]:
    """Persist the user turn, bind runtime, then start a recoverable background job."""
    _sweep()
    owner = getattr(request.state, "user", None) or "unknown"
    if req.conversation_id:
        active = next((
            j for j in _JOBS.values()
            if j.get("conversation_id") == req.conversation_id
            and j.get("owner") == owner
            and j.get("status") in {"queued", "running"}
        ), None)
        if active:
            raise HTTPException(
                status_code=409,
                detail="该对话已有执行中任务；请使用追加指令",
            )
    saved_runtime: dict[str, str] | None = None
    if req.conversation_id:
        from seoagents.dashboard.routers.conversations import conversation_runtime

        saved_runtime = await asyncio.to_thread(
            conversation_runtime, req.conversation_id, owner=owner
        )
        if saved_runtime is None:
            raise HTTPException(status_code=404, detail="对话不存在")
    try:
        provider, model, reasoning_effort = await asyncio.to_thread(
            _validated_runtime, req, saved=saved_runtime
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if req.conversation_id:
        from seoagents.dashboard.routers.conversations import (
            append_user_message,
            queued_prompt_count,
            set_conversation_runtime,
        )

        accepted = await asyncio.to_thread(
            set_conversation_runtime,
            req.conversation_id,
            owner=owner,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        if not accepted:
            raise HTTPException(status_code=404, detail="对话不存在")
        await asyncio.to_thread(
            append_user_message, req.conversation_id, owner=owner, text=req.task
        )
    job_id = f"J-{uuid.uuid4().hex[:12]}"
    queued_count_value = 0
    if req.conversation_id:
        from seoagents.dashboard.routers.conversations import queued_prompt_count as _queued_count
        queued_count_value = await asyncio.to_thread(
            _queued_count, req.conversation_id, owner=owner
        )
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "task": req.task,
        "role": req.role,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "conversation_id": req.conversation_id or "",
        "hermes_session_id": f"seoagents-{req.conversation_id or job_id}",
        "owner": owner,
        "queued_count": queued_count_value,
        "created_at": time.time(),
    }
    await asyncio.to_thread(_save_job, _JOBS[job_id])
    asyncio.create_task(_run_job(
        job_id, req.task, req.role, req.conversation_id,
        provider, model, reasoning_effort, owner,
    ))
    return {
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "runtime": {
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
        },
    }


@router.post("/conversations/{conversation_id}/queue", status_code=202)
async def queue_conversation_prompt(
    conversation_id: str,
    req: AgentTaskRequest,
    request: Request,
) -> dict[str, Any]:
    """Append a durable FIFO follow-up while this conversation is running."""
    owner = getattr(request.state, "user", None) or "unknown"
    from seoagents.dashboard.routers.conversations import (
        conversation_runtime,
        enqueue_prompt,
        queued_prompt_count,
    )

    saved = await asyncio.to_thread(conversation_runtime, conversation_id, owner=owner)
    if saved is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    try:
        provider, model, effort = await asyncio.to_thread(
            _validated_runtime, req, saved=saved
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    async with _conversation_lock(conversation_id):
        active = next((
            j for j in _JOBS.values()
            if j.get("conversation_id") == conversation_id
            and j.get("owner") == owner
            and j.get("status") in {"queued", "running"}
        ), None)
        if not active:
            # The UI can race the exact settlement edge.  Persist the user
            # instruction first, then start a new turn in the same durable
            # conversation instead of rejecting it. This is NOT a replay of a
            # lost side-effecting run; it is a newly named user turn.
            followup = AgentTaskRequest(
                task=req.task,
                role="hm",
                conversation_id=conversation_id,
                provider=provider,
                model=model,
                reasoning_effort=effort,
            )
            return await submit_job(followup, request)
        prompt_id = await asyncio.to_thread(
            enqueue_prompt,
            conversation_id,
            owner=owner,
            text=req.task,
            provider=provider,
            model=model,
            reasoning_effort=effort,
        )
        count = await asyncio.to_thread(
            queued_prompt_count, conversation_id, owner=owner
        )
        active["queued_count"] = count
        await asyncio.to_thread(_save_job, active)
    return {
        "ok": True,
        "queued": True,
        "prompt_id": prompt_id,
        "job_id": active.get("job_id"),
        "queued_count": count,
        "runtime": {"provider": provider, "model": model, "reasoning_effort": effort},
    }


@router.post("/conversations/{conversation_id}/steer", status_code=202)
async def steer_conversation(
    conversation_id: str,
    req: AgentTaskRequest,
    request: Request,
) -> dict[str, Any]:
    """Inject a follow-up into the active Hermes turn after its next tool call."""
    owner = getattr(request.state, "user", None) or "unknown"
    from seoagents.dashboard.routers.conversations import (
        append_user_message,
        conversation_owned,
    )

    if not await asyncio.to_thread(conversation_owned, conversation_id, owner=owner):
        raise HTTPException(status_code=404, detail="对话不存在")
    active = next((
        j for j in _JOBS.values()
        if j.get("conversation_id") == conversation_id
        and j.get("owner") == owner
        and j.get("status") == "running"
    ), None)
    if not active:
        # A refresh/restart or an exact settlement race means there is no live
        # AIAgent object to steer. Preserve the instruction as a new explicit
        # turn in the same conversation rather than losing it.
        followup = AgentTaskRequest(
            task=req.task,
            role="hm",
            conversation_id=conversation_id,
            provider=req.provider,
            model=req.model,
            reasoning_effort=req.reasoning_effort,
        )
        started = await submit_job(followup, request)
        return {
            **started,
            "accepted": True,
            "mode": "new_turn",
            "notice": "当前轮已结束或不在本进程，指令已作为同会话新一轮启动",
        }
    if not await asyncio.to_thread(_hermes_supports_session_steer):
        raise HTTPException(status_code=503, detail="当前 Hermes 尚未启用会话 steer")
    session_id = str(active.get("hermes_session_id") or f"seoagents-{conversation_id}")
    try:
        result = await asyncio.to_thread(
            _hermes_json,
            "POST",
            f"/api/sessions/{session_id}/steer",
            {"message": req.task},
        )
    except Exception as exc:
        # Hermes may report session_not_running during the narrow window after
        # the dashboard still observed "running". Fall back to a durable FIFO
        # row; if the current loop has already settled, queue endpoint will
        # start a new turn immediately.
        if "session_not_running" in str(exc) or "No steerable run" in str(exc):
            return await queue_conversation_prompt(conversation_id, req, request)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Persist only after Hermes confirms acceptance; otherwise the transcript
    # must not claim an instruction reached the active model.
    await asyncio.to_thread(
        append_user_message, conversation_id, owner=owner, text=req.task
    )
    return {
        "ok": True,
        "accepted": bool(result.get("accepted")),
        "mode": "steer",
        "job_id": active.get("job_id"),
    }


@router.post("/jobs/{job_id}/checkpoint")
async def checkpoint_job(job_id: str, request: Request) -> dict[str, Any]:
    """Persist the live projection so a browser refresh can recover its trail."""
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或不在当前进程中")
    owner = getattr(request.state, "user", None) or "unknown"
    if job.get("owner") != owner:
        raise HTTPException(status_code=404, detail="任务不存在")
    await asyncio.to_thread(_save_job, job)
    return {"ok": True, "job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    """轮询任务状态。running 时也返回已经跑过的工具,前端好显示进度。"""
    owner = getattr(request.state, "user", None) or "unknown"
    live = _JOBS.get(job_id)
    if live is not None and live.get("owner") != owner:
        live = None
    job = live or await asyncio.to_thread(_load_job_for_owner, job_id, owner)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在或已过期")
    if live is None and job.get("status") in {"queued", "running"}:
        job = await asyncio.to_thread(_project_orphaned_run, job)
    elapsed = time.time() - job.get("started_at", job.get("created_at", time.time()))
    out = {
        "ok": True,
        "job_id": job_id,
        "status": job["status"],
        "elapsed_seconds": round(elapsed, 1),
        # 思考过程与工具调用,running 时也给 —— 这正是前端不用干等的原因
        "progress": job.get("progress") or [],
        "queued_count": int(job.get("queued_count") or 0),
        "reasoning_baseline": job.get("reasoning_baseline", 0),
        "runtime": {
            "provider": job.get("provider") or "",
            "model": job.get("model") or "",
            "reasoning_effort": job.get("reasoning_effort") or "",
        },
    }
    if job["status"] == "done":
        if job.get("ok"):
            out["runtime"]["provider"] = job.get("provider") or out["runtime"]["provider"]
            out["runtime"]["model"] = job.get("model") or out["runtime"]["model"]
        out.update(
            result_ok=job.get("ok"),
            error=job.get("error"),
            final_text=job.get("final_text"),
            turns=job.get("turns"),
            trace=job.get("trace") or [],
        )
    return out


@router.get("/conversations/{conversation_id}/active-job")
async def active_conversation_job(conversation_id: str, request: Request) -> dict[str, Any]:
    """Reconnect a reloaded browser to the still-running job for this conversation."""
    from seoagents.dashboard.routers.conversations import conversation_owned

    owner = getattr(request.state, "user", None) or "unknown"
    if not await asyncio.to_thread(conversation_owned, conversation_id, owner=owner):
        raise HTTPException(status_code=404, detail="对话不存在")
    jobs = [
        j for j in _JOBS.values()
        if j.get("conversation_id") == conversation_id
        and j.get("owner") == owner
        and j.get("status") in {"queued", "running"}
    ]
    job = max(jobs, key=lambda j: float(j.get("created_at") or 0)) if jobs else None
    if job is None:
        job = await asyncio.to_thread(_load_active_job, conversation_id, owner)
        if job:
            job = await asyncio.to_thread(_project_orphaned_run, job)
    if not job or job.get("status") in {"done", "unknown"}:
        return {"active": False, "status": job.get("status") if job else None, "error": job.get("error") if job else ""}
    return {
        "active": True,
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job.get("created_at"),
        "progress": job.get("progress") or [],
        "queued_count": int(job.get("queued_count") or 0),
        "reasoning_baseline": job.get("reasoning_baseline", 0),
        "runtime": {
            "provider": job.get("provider") or "",
            "model": job.get("model") or "",
            "reasoning_effort": job.get("reasoning_effort") or "auto",
        },
    }


__all__ = ["router"]
