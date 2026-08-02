"""Google Drive 存储驱动 (L4)。

Drive 不是 S3 兼容,不能走 boto3。它有两个和对象存储根本不同的地方,
资产枢纽的接口要在这一层抹平:

1. **没有"路径"这个概念**。Drive 里只有文件和父文件夹,`a/b/c.json` 这种
   key 必须逐级建文件夹再挂上去。这里维护一个路径→文件夹 ID 的缓存,
   免得每次写入都重新遍历一遍目录树。
2. **同名文件可以共存**。S3 里 put 同一个 key 是覆盖,Drive 里会变成两个
   同名文件。所以写入前先按 (名字, 父目录) 查一次,有就 update 没有才 create ——
   否则跑几天就会有几十个同名快照,而且不知道哪个是最新的。

token 会自动续期并回写。存放位置刻意不在 `credentials/` 里 —— 那个目录是
只读挂载(静态凭证就该只读),而 token 每小时都要刷新回写。
"""
from __future__ import annotations

import io
import json
import os
import threading
from typing import Any

from dojocore.logging import LOGGER

_FOLDER_MIME = "application/vnd.google-apps.folder"
_lock = threading.Lock()
_folder_cache: dict[str, str] = {}
_service: Any = None


class GDriveError(RuntimeError):
    pass


def _token_path(node: dict[str, Any]) -> str:
    return node.get("token_path") or "/data/seo-stack/seoagents-data/google-drive-token.json"


def get_service(node: dict[str, Any]) -> Any:
    """拿一个可用的 Drive 客户端;token 过期会自动刷新并回写。"""
    global _service
    if _service is not None:
        return _service
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GDriveError("缺少 google-api-python-client / google-auth") from exc

    path = _token_path(node)
    if not os.path.exists(path):
        raise GDriveError(f"Drive token 不存在: {path}")
    try:
        creds = Credentials.from_authorized_user_file(path)
    except Exception as exc:  # noqa: BLE001
        raise GDriveError(f"Drive token 格式不可用: {exc}") from exc

    if not creds.valid:
        if not creds.refresh_token:
            raise GDriveError("Drive token 已过期且没有 refresh_token,需要重新授权")
        try:
            creds.refresh(Request())
        except Exception as exc:  # noqa: BLE001
            raise GDriveError(
                f"Drive token 刷新失败: {exc} —— "
                f"若 OAuth 应用仍处于「测试」状态,refresh_token 只有 7 天有效期,"
                f"需要把应用发布为「正式版」或重新授权"
            ) from exc
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        except OSError as exc:
            # 写不回去意味着下次重启还得再刷一次,不致命但要吵出来
            LOGGER.warning(f"Drive token 刷新成功但回写失败({exc}),下次启动需再刷一次")

    _service = build("drive", "v3", credentials=creds, cache_discovery=False)
    return _service


def _root_id(node: dict[str, Any]) -> str:
    return node.get("root_folder_id") or "root"


def _ensure_folder(svc: Any, name: str, parent: str) -> str:
    ck = f"{parent}/{name}"
    with _lock:
        if ck in _folder_cache:
            return _folder_cache[ck]
    q = (f"name = '{name}' and '{parent}' in parents and "
         f"mimeType = '{_FOLDER_MIME}' and trashed = false")
    res = svc.files().list(q=q, fields="files(id)", pageSize=1).execute()
    files = res.get("files") or []
    if files:
        fid = files[0]["id"]
    else:
        fid = svc.files().create(
            body={"name": name, "mimeType": _FOLDER_MIME, "parents": [parent]},
            fields="id",
        ).execute()["id"]
    with _lock:
        _folder_cache[ck] = fid
    return fid


def _resolve(svc: Any, node: dict[str, Any], key: str, *, create: bool) -> tuple[str, str]:
    """把 `a/b/c.json` 解析成 (父文件夹 ID, 文件名)。"""
    parts = [p for p in key.split("/") if p]
    if not parts:
        raise GDriveError("key 不能为空")
    name = parts[-1]
    parent = _root_id(node)
    for seg in parts[:-1]:
        if create:
            parent = _ensure_folder(svc, seg, parent)
        else:
            q = (f"name = '{seg}' and '{parent}' in parents and "
                 f"mimeType = '{_FOLDER_MIME}' and trashed = false")
            fs = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files") or []
            if not fs:
                raise GDriveError(f"路径不存在: {key}(卡在 '{seg}')")
            parent = fs[0]["id"]
    return parent, name


def _find(svc: Any, parent: str, name: str) -> str | None:
    q = f"name = '{name}' and '{parent}' in parents and trashed = false"
    fs = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files") or []
    return fs[0]["id"] if fs else None


# ── 对外接口:与 S3 驱动保持同样的语义 ──────────────────────────────
def put(node: dict[str, Any], key: str, data: bytes, content_type: str) -> dict[str, Any]:
    from googleapiclient.http import MediaIoBaseUpload

    svc = get_service(node)
    parent, name = _resolve(svc, node, key, create=True)
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type, resumable=False)
    existing = _find(svc, parent, name)
    if existing:
        # 同名即覆盖 —— 对齐 S3 的 put 语义,否则会堆出一串同名文件
        svc.files().update(fileId=existing, media_body=media).execute()
        fid = existing
    else:
        fid = svc.files().create(
            body={"name": name, "parents": [parent]}, media_body=media, fields="id",
        ).execute()["id"]
    return {"file_id": fid, "key": key, "size": len(data)}


def get(node: dict[str, Any], key: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload

    svc = get_service(node)
    parent, name = _resolve(svc, node, key, create=False)
    fid = _find(svc, parent, name)
    if not fid:
        raise GDriveError(f"对象不存在: {key}")
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=fid))
    done = False
    while not done:
        _, done = dl.next_chunk()
    return buf.getvalue()


def exists(node: dict[str, Any], key: str) -> bool:
    try:
        svc = get_service(node)
        parent, name = _resolve(svc, node, key, create=False)
        return _find(svc, parent, name) is not None
    except GDriveError:
        return False


def listing(node: dict[str, Any], prefix: str = "", limit: int = 200) -> list[dict[str, Any]]:
    svc = get_service(node)
    parent = _root_id(node)
    segs = [p for p in prefix.split("/") if p]
    try:
        for seg in segs:
            q = (f"name = '{seg}' and '{parent}' in parents and "
                 f"mimeType = '{_FOLDER_MIME}' and trashed = false")
            fs = svc.files().list(q=q, fields="files(id)", pageSize=1).execute().get("files") or []
            if not fs:
                return []
            parent = fs[0]["id"]
    except Exception:  # noqa: BLE001
        return []
    res = svc.files().list(
        q=f"'{parent}' in parents and trashed = false",
        fields="files(id,name,size,modifiedTime,mimeType)", pageSize=min(limit, 1000),
    ).execute()
    out = []
    for f in res.get("files", []):
        out.append({
            "key": f"{prefix.rstrip('/')}/{f['name']}" if prefix else f["name"],
            "size": int(f.get("size", 0) or 0),
            "modified": f.get("modifiedTime", ""),
            "is_folder": f.get("mimeType") == _FOLDER_MIME,
        })
    return out


def delete(node: dict[str, Any], key: str) -> None:
    svc = get_service(node)
    parent, name = _resolve(svc, node, key, create=False)
    fid = _find(svc, parent, name)
    if fid:
        svc.files().delete(fileId=fid).execute()


def head_size(node: dict[str, Any], key: str) -> int:
    try:
        svc = get_service(node)
        parent, name = _resolve(svc, node, key, create=False)
        fid = _find(svc, parent, name)
        if not fid:
            return 0
        return int(svc.files().get(fileId=fid, fields="size").execute().get("size", 0) or 0)
    except Exception:  # noqa: BLE001
        return 0


def quota_info(node: dict[str, Any]) -> dict[str, Any]:
    """Drive 自己就报真实用量 —— 比我们本地记账准,优先用它。"""
    svc = get_service(node)
    a = svc.about().get(fields="user,storageQuota").execute()
    q = a.get("storageQuota", {})
    used = int(q.get("usage", 0) or 0)
    limit = int(q.get("limit", 0) or 0)
    return {
        "account": a.get("user", {}).get("emailAddress"),
        "used_bytes": used,
        "limit_bytes": limit,
        "used_gb": round(used / 1024 ** 3, 3),
        "limit_gb": round(limit / 1024 ** 3, 1) if limit else None,
        "used_ratio": round(used / limit, 4) if limit else None,
    }


__all__ = ["GDriveError", "delete", "exists", "get", "get_service", "head_size",
           "listing", "put", "quota_info"]
