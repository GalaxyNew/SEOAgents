"""中央资产存储 —— S3 兼容对象存储客户端 (L4)。

接的是中科院 `s3.cstcloud.cn`。连通它踩了三个坑,都不在任何文档里,
全部写在这里,免得下次有人重新踩一遍:

1. **必须 Path-Style 寻址**。虚拟主机寻址(默认)会去连
   `https://<bucket>.s3.cstcloud.cn`,那个域名根本不存在。

2. **User-Agent 必须匹配控制台里给 AccessKey 绑定的「应用」**。
   网关按 UA 判断请求来自哪个客户端:UA 是 `rclone/*` 就放行,
   `aws-cli` / `boto3` 默认 UA 一律 **401 Unauthorized**。
   注意 401 不是标准 S3 错误码 —— 它由网关返回,请求压根没进鉴权逻辑,
   所以看起来像「密钥无效」,实际密钥完全正常。

3. **必须关掉 boto3 的分块校验和**。新版 botocore 默认给 PUT 加
   `aws-chunked` 传输编码与自动 checksum,该服务端不支持,
   回 `NotImplemented: aws-chunked request payloads are not implemented`。

另外实测到:``put_object`` 成功后立刻 ``list_objects_v2`` 可能返回 0 个 ——
**列表是最终一致的**。要确认某个对象写没写进去,用 ``head_object`` 而不是列表。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from dojocore.logging import LOGGER

# 绑定在 AccessKey 上的应用标识。改这个值之前先确认控制台里 key 绑的是什么,
# 两边不一致会直接 401。
_BOUND_CLIENT_UA = os.environ.get("S3_CLIENT_UA", "rclone/v1.65.2")


class ObjectStoreUnavailable(RuntimeError):
    """存储不可用。调用方必须如实上报,不得静默降级到本地磁盘。"""


@lru_cache(maxsize=1)
def get_client() -> Any:
    """复用同一个 client(内部有 HTTP 连接池,不该每次新建)。"""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # noqa: BLE001
        raise ObjectStoreUnavailable("boto3 未安装:pip install boto3") from exc

    endpoint = os.environ.get("S3_ENDPOINT", "").strip()
    ak = os.environ.get("S3_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("S3_SECRET_ACCESS_KEY", "").strip()
    missing = [n for n, v in
               (("S3_ENDPOINT", endpoint), ("S3_ACCESS_KEY_ID", ak),
                ("S3_SECRET_ACCESS_KEY", sk)) if not v]
    if missing:
        raise ObjectStoreUnavailable(f"缺少环境变量: {missing}")

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},      # 坑 1
            user_agent=_BOUND_CLIENT_UA,          # 坑 2
            request_checksum_calculation="when_required",   # 坑 3
            response_checksum_validation="when_required",
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _bucket() -> str:
    b = os.environ.get("S3_BUCKET", "").strip()
    if not b:
        raise ObjectStoreUnavailable("缺少环境变量 S3_BUCKET")
    return b


def put_bytes(key: str, data: bytes, *, content_type: str = "application/octet-stream") -> dict[str, Any]:
    """写入一个对象。失败抛异常 —— 资产写不进去是必须让人知道的事。"""
    s3 = get_client()
    s3.put_object(Bucket=_bucket(), Key=key, Body=data, ContentType=content_type)
    LOGGER.info(f"object_store: 已写入 {key} ({len(data)}B)")
    return {"key": key, "size": len(data), "content_type": content_type}


def put_json(key: str, obj: Any) -> dict[str, Any]:
    return put_bytes(
        key, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
        content_type="application/json",
    )


def get_bytes(key: str) -> bytes:
    return get_client().get_object(Bucket=_bucket(), Key=key)["Body"].read()


def get_json(key: str) -> Any:
    return json.loads(get_bytes(key).decode("utf-8"))


def exists(key: str) -> bool:
    """用 head 而不是 list —— 列表是最终一致的,刚写的对象可能列不出来。"""
    from botocore.exceptions import ClientError

    try:
        get_client().head_object(Bucket=_bucket(), Key=key)
        return True
    except ClientError:
        return False


def list_keys(prefix: str = "", limit: int = 1000) -> list[dict[str, Any]]:
    resp = get_client().list_objects_v2(Bucket=_bucket(), Prefix=prefix, MaxKeys=limit)
    return [
        {"key": o["Key"], "size": o["Size"], "modified": o["LastModified"].isoformat()}
        for o in resp.get("Contents", [])
    ]


def delete(key: str) -> None:
    get_client().delete_object(Bucket=_bucket(), Key=key)
    LOGGER.info(f"object_store: 已删除 {key}")


def health() -> dict[str, Any]:
    """连通性自检 —— 前端与 hm 用它判断资产中心是否可用。"""
    try:
        s3 = get_client()
        s3.list_objects_v2(Bucket=_bucket(), MaxKeys=1)
    except ObjectStoreUnavailable as exc:
        return {"ok": False, "reachable": False, "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reachable": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {
        "ok": True, "reachable": True,
        "endpoint": os.environ.get("S3_ENDPOINT"),
        "bucket": _bucket(),
        "client_ua": _BOUND_CLIENT_UA,
        "note": "列表最终一致;确认单个对象请用 head 而非 list",
    }


__all__ = [
    "ObjectStoreUnavailable", "delete", "exists", "get_bytes", "get_client",
    "get_json", "health", "list_keys", "put_bytes", "put_json",
]
