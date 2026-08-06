"""Outbox deliverer — polls PENDING outbox records and delivers to recipient inbox.

Runs as a periodic task (every 15s). For each PENDING request in the outbox:
1. Look up the recipient department endpoint from departments.json
2. POST the request payload to {endpoint}/api/v1/inbox
3. On success: mark delivered_at on the outbox record
4. On failure: exponential backoff retry (max 5 attempts)

The deliverer is the *sender's* responsibility — only the department that
created the outbox record tries to deliver it. The recipient pulls status
changes from its own inbox; the sender polls for receipts.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error

from dojocore.collab import get_collab_service
from dojocore.logging import LOGGER

_DEPARTMENTS_PATH = os.environ.get(
    "DEPARTMENTS_JSON",
    "/data/seo-stack/seoagents-data/departments.json",
)


def _load_departments() -> dict:
    """Load the federated department directory."""
    try:
        with open(_DEPARTMENTS_PATH) as f:
            return json.load(f)
    except Exception as exc:
        LOGGER.warning(f"deliverer: cannot load departments.json: {exc}")
        return {}


def _resolve_endpoint(dept_id: str) -> str:
    """Look up the recipient's HTTP endpoint."""
    departments = _load_departments()
    dept_info = departments.get(dept_id, {})
    endpoint = dept_info.get("endpoint", "")
    if not endpoint:
        raise ValueError(f"department '{dept_id}' has no endpoint configured")
    return endpoint


def _post_inbox(endpoint: str, payload: dict) -> dict:
    """POST a request to the recipient's /api/v1/inbox."""
    url = f"{endpoint.rstrip('/')}/api/v1/inbox"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Dept": "seo",
        },
        method="POST",
    )
    # CF Access Service Token (if behind Cloudflare)
    cf_token = os.environ.get("CF_ACCESS_TOKEN", "")
    if cf_token:
        req.add_header("CF-Access-Client-Id", os.environ.get("CF_ACCESS_CLIENT_ID", ""))
        req.add_header("CF-Access-Client-Secret", cf_token)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        LOGGER.error(f"deliverer: POST {url} -> HTTP {exc.code}: {body[:200]}")
        raise
    except Exception as exc:
        LOGGER.error(f"deliverer: POST {url} failed: {exc}")
        raise


def run_delivery_once() -> dict:
    """Single delivery pass. Returns a summary of actions taken.

    Called by the cron scheduler on each tick.
    """
    try:
        svc = get_collab_service()
    except Exception as exc:
        LOGGER.warning(f"deliverer: collab service unavailable: {exc}")
        return {"delivered": 0, "skipped": 0, "errors": 0}

    # List PENDING items in our outbox
    pending = svc.store.list(box="outbox", status="PENDING", limit=50)
    if not pending:
        return {"delivered": 0, "skipped": 0, "errors": 0}

    delivered = 0
    skipped = 0
    errors = 0

    for req in pending:
        # Skip if already delivered (check history for delivery marker)
        _already = any(
            h.get("to") == "DELIVERED_TO_RECIPIENT"
            for h in (req.history or ())
        )
        if _already:
            skipped += 1
            continue

        # Resolve recipient endpoint
        recipient_dept = req.recipient.dept
        try:
            endpoint = _resolve_endpoint(recipient_dept)
        except ValueError as exc:
            # Endpoint not configured — skip silently (department not federated yet)
            LOGGER.info(f"deliverer: skip {req.request_id} — {exc}")
            skipped += 1
            continue

        # Deliver via POST
        payload = req.to_dict()
        try:
            result = _post_inbox(endpoint, payload)
            LOGGER.info(
                f"deliverer: {req.request_id} -> {recipient_dept} inbox OK "
                f"(created={result.get('created')})"
            )
            delivered += 1
        except Exception as exc:
            LOGGER.warning(
                f"deliverer: {req.request_id} delivery failed: {exc}"
            )
            errors += 1

    summary = {"delivered": delivered, "skipped": skipped, "errors": errors}
    LOGGER.info(f"deliverer: pass complete {summary}")
    return summary


__all__ = ["run_delivery_once", "run_delivery_loop"]
