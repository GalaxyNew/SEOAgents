"""登录与会话 (L2)。

这套后台此前对公网完全开放 —— 包括 ``/docs`` 那个能直接点按钮发 POST 的
交互页。任何人都能写存储、改配置、跑 LLM 任务(花的是本账号的钱)。
这个模块把门关上。

几个刻意的决定:

* **口令只存哈希**。PBKDF2-SHA256,10 万轮,每人独立盐。用户表被看到也
  拿不到明文口令。
* **会话密钥落盘**。每次重启换密钥会把所有人踢下线,看起来像"登录不上"。
  首次生成后写入 0600 文件复用。
* **默认口令必须改**。``admin/admin123`` 是给第一次进门用的,公网上的
  扫描器专门试这一类组合。带默认口令的账号会被标记 ``must_change``,
  登录后除了改口令什么都做不了。
* **只读放行清单尽量小**。健康检查和登录页必须匿名可达,其余一律要会话。
  静态资源放行 —— 拦它只会让登录页自己白屏。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from dojocore.logging import LOGGER

def _data_dir() -> Path:
    """每次都读环境变量,而不是在 import 时定死。

    模块级常量在 import 那一刻就把路径固定了,之后再改 SEOAGENTS_AUTH_DIR
    不会生效 —— 测试会因此写进生产用户表,而且排查起来毫无线索。
    """
    return Path(os.environ.get("SEOAGENTS_AUTH_DIR", "/data/seo-stack/seoagents-data"))


def _users_path() -> Path:
    return _data_dir() / "users.json"


def _secret_path() -> Path:
    return _data_dir() / "session_secret"

COOKIE = "seoagents_session"
SESSION_TTL = 7 * 24 * 3600  # 一周,够用又不至于长期有效的令牌到处躺着

# 匿名可达的前缀。登录页要能打开,静态资源要能加载,健康检查要能被探活 ——
# 除此之外不开口子。
_PUBLIC_PREFIXES = (
    "/api/auth/login", "/api/auth/session",
    "/static/", "/assets/", "/favicon", "/health",
)

# 机器对机器的入口。`/api/v1/*` 是别的部门实例调本部门用的 collab 协议:
# 对面是台服务器,拿不到浏览器 cookie,要它「登录」没有意义。这类请求走
# 服务令牌。令牌没配置时这些端点保持匿名可达 —— 直接锁死会让已经在跑的
# 跨部门协作在升级瞬间全断,而它们此前本来就是匿名的,不算新增暴露面。
_SERVICE_PREFIXES = ("/api/v1/",)


def _service_token() -> str:
    return os.environ.get("SEOAGENTS_SERVICE_TOKEN", "").strip()


def _service_authorized(request: Request) -> bool:
    want = _service_token()
    if not want:
        return True  # 未配置 = 维持既有行为,但会在启动时提醒
    got = (request.headers.get("x-service-token")
           or request.headers.get("authorization", "").removeprefix("Bearer ").strip())
    return bool(got) and hmac.compare_digest(got, want)


def _secret() -> bytes:
    if _secret_path().is_file():
        return _secret_path().read_bytes()
    _data_dir().mkdir(parents=True, exist_ok=True)
    s = secrets.token_bytes(32)
    _secret_path().write_bytes(s)
    os.chmod(_secret_path(), 0o600)
    LOGGER.info("已生成会话密钥")
    return s


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100_000).hex()


def _load_users() -> dict[str, Any]:
    if _users_path().is_file():
        try:
            return json.loads(_users_path().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.error(f"用户表损坏,拒绝以「无用户」状态启动: {exc}")
            raise
    # 首次启动:建默认管理员,并标记必须改口令
    salt = secrets.token_bytes(16).hex()
    users = {
        "admin": {
            "salt": salt,
            "hash": _hash("admin123", salt),
            "role": "admin",
            "must_change": True,
            "created_at": time.time(),
        }
    }
    _save_users(users)
    LOGGER.warning("已创建默认管理员 admin/admin123 —— 首次登录后必须修改口令")
    return users


def _save_users(users: dict[str, Any]) -> None:
    _data_dir().mkdir(parents=True, exist_ok=True)
    tmp = _users_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _users_path())
    os.chmod(_users_path(), 0o600)


def _sign(username: str, expires: int) -> str:
    payload = f"{username}:{expires}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def verify_token(token: str) -> str | None:
    """校验会话令牌,返回用户名;无效返回 None。"""
    try:
        username, exp_s, sig = token.rsplit(":", 2)
        expires = int(exp_s)
    except (ValueError, AttributeError):
        return None
    if expires < time.time():
        return None
    expected = hmac.new(_secret(), f"{username}:{expires}".encode(), hashlib.sha256).hexdigest()
    # 定长比较,避免按字节提前返回泄露信息
    if not hmac.compare_digest(sig, expected):
        return None
    return username if username in _load_users() else None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = _load_users().get(username)
    if not user:
        return None
    if not hmac.compare_digest(_hash(password, user["salt"]), user["hash"]):
        return None
    return user


class AuthMiddleware(BaseHTTPMiddleware):
    """没有有效会话就挡在门外。

    API 返回 401 让前端跳登录;页面请求返回登录页本身而不是 401 —— 直接
    甩一个 JSON 报错给浏览器,人只会看到一屏乱码。
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        if path == "/" or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)

        if any(path.startswith(p) for p in _SERVICE_PREFIXES):
            if _service_authorized(request):
                return await call_next(request)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "服务令牌无效", "code": "BAD_SERVICE_TOKEN"}, status_code=401)

        token = request.cookies.get(COOKIE, "")
        username = verify_token(token) if token else None
        if not username:
            # 也接受 Authorization: Bearer <token>,方便脚本与 agent 调用
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                username = verify_token(auth[7:])
        if not username:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "未登录"}, status_code=401)

        user = _load_users()[username]
        # 带默认口令的账号除了改口令什么都不许做 —— 公网上的扫描器
        # 专挑 admin/admin123 这类组合,不能让它停在"能登录就够了"。
        if user.get("must_change") and not path.startswith("/api/auth/"):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                {"detail": "首次登录必须修改口令", "code": "MUST_CHANGE_PASSWORD"},
                status_code=403,
            )
        request.state.user = username
        return await call_next(request)


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginIn, response: Response) -> dict[str, Any]:
    user = authenticate(body.username, body.password)
    if not user:
        # 不区分"用户不存在"与"口令错误" —— 区分了就等于送人一个用户名枚举器
        LOGGER.warning(f"登录失败: {body.username}")
        raise HTTPException(401, "用户名或口令不正确")
    expires = int(time.time()) + SESSION_TTL
    token = _sign(body.username, expires)
    response.set_cookie(
        COOKIE, token, max_age=SESSION_TTL, httponly=True, samesite="lax",
        secure=True, path="/",
    )
    LOGGER.info(f"登录成功: {body.username}")
    return {"ok": True, "username": body.username, "role": user.get("role", "user"),
            "must_change": bool(user.get("must_change")), "token": token}


@router.get("/session")
def session(request: Request) -> dict[str, Any]:
    """当前会话状态。前端据此决定显示登录页还是主界面。"""
    token = request.cookies.get(COOKIE, "")
    username = verify_token(token) if token else None
    if not username:
        return {"authenticated": False}
    user = _load_users()[username]
    return {"authenticated": True, "username": username,
            "role": user.get("role", "user"), "must_change": bool(user.get("must_change"))}


@router.post("/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


class ChangeIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/password")
def change_password(body: ChangeIn, request: Request, response: Response) -> dict[str, Any]:
    token = request.cookies.get(COOKIE, "")
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(401, "未登录")
    if not authenticate(username, body.old_password):
        raise HTTPException(401, "原口令不正确")
    if len(body.new_password) < 8:
        raise HTTPException(422, "新口令至少 8 位")
    if body.new_password in {"admin123", "password", "12345678", username}:
        raise HTTPException(422, "这个口令在字典里,换一个")

    users = _load_users()
    salt = secrets.token_bytes(16).hex()
    users[username].update({
        "salt": salt, "hash": _hash(body.new_password, salt),
        "must_change": False, "password_changed_at": time.time(),
    })
    _save_users(users)
    # 改完口令换发令牌:旧令牌基于旧状态签发,继续用会让"改口令"失去意义
    expires = int(time.time()) + SESSION_TTL
    response.set_cookie(COOKIE, _sign(username, expires), max_age=SESSION_TTL,
                        httponly=True, samesite="lax", secure=True, path="/")
    LOGGER.info(f"口令已修改: {username}")
    return {"ok": True}


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "user"


@router.get("/users")
def list_users(request: Request) -> dict[str, Any]:
    _require_admin(request)
    return {"users": [
        {"username": u, "role": d.get("role", "user"),
         "must_change": bool(d.get("must_change")),
         "created_at": d.get("created_at")}
        for u, d in _load_users().items()
    ]}


@router.post("/users")
def create_user(body: UserIn, request: Request) -> dict[str, Any]:
    _require_admin(request)
    users = _load_users()
    if body.username in users:
        raise HTTPException(409, f"用户已存在: {body.username}")
    if len(body.password) < 8:
        raise HTTPException(422, "口令至少 8 位")
    salt = secrets.token_bytes(16).hex()
    users[body.username] = {
        "salt": salt, "hash": _hash(body.password, salt),
        "role": body.role, "must_change": True, "created_at": time.time(),
    }
    _save_users(users)
    return {"ok": True, "username": body.username}


@router.delete("/users/{username}")
def delete_user(username: str, request: Request) -> dict[str, Any]:
    me = _require_admin(request)
    if username == me:
        raise HTTPException(422, "不能删除自己 —— 否则可能把最后一个管理员删掉,谁也进不来")
    users = _load_users()
    if username not in users:
        raise HTTPException(404, f"用户不存在: {username}")
    admins = [u for u, d in users.items() if d.get("role") == "admin" and u != username]
    if not admins:
        raise HTTPException(422, "这是最后一个管理员,删掉就没人能管理系统了")
    users.pop(username)
    _save_users(users)
    return {"ok": True}


def _require_admin(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    username = verify_token(token) if token else None
    if not username:
        raise HTTPException(401, "未登录")
    if _load_users()[username].get("role") != "admin":
        raise HTTPException(403, "需要管理员权限")
    return username


__all__ = ["AuthMiddleware", "COOKIE", "router", "verify_token"]
