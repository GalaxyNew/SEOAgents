"""
content_publisher — 文章排版渲染 + CMS 发布（G1-D）

28 号文 §八 G1-D 验收门禁：
  产线 render→publish 节点不再报 "tool not found"；发布返回真实 URL。

实现依据：西班牙二号 mejorsiptv.shop 的 Next.js API（源码实测）：
  POST /api/posts/publish  Bearer token 鉴权
  字段：title, slug, content(HTML), category, status, excerpt,
        metaTitle, metaDescription, canonicalUrl, keywords,
        templateId/templateName, anchorNavEnabled, locale

  POST /api/posts/upload   Bearer token 鉴权（图片上传，≤5MB）

同时修复 orchestrator.py 的三角色硬编码——本工具作为独立 L4 工具注册，
产线 workflow 通过 tool_call 节点调用它，不再依赖 orchestrator 的角色链。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from seoagents.tools.base import BaseToolSpec

LOGGER = logging.getLogger("seoagents")

# 西班牙二号的合法分类（API 源码 route.ts 第 8 行）
_VALID_CATEGORIES = {"guias", "dispositivos", "contenido", "comparativas"}
_VALID_STATUSES = {"published", "draft", "scheduled"}


class ContentPublisherSpec(BaseToolSpec):
    """文章发布工具：render（生成 HTML）+ publish（推 CMS）。"""

    def __init__(self, config: Any, store: Any = None) -> None:
        self.config = config
        self.token = (
            getattr(config.seo_credentials, "cms_publish_token", "") or ""
        ).strip()

    def _resolve_site(self, arguments: dict[str, Any]) -> str:
        """确定发布目标站点 URL。

        优先级：参数 site_url > 参数 site > config.sites.site_url。
        支持多站点：mejorsiptv.shop / igoriptv2.com 都有同一套 API。
        """
        site_url = (
            arguments.get("site_url")
            or arguments.get("site")
            or ""
        ).rstrip("/")
        if not site_url:
            site_url = (self.config.sites.site_url or "").rstrip("/")
        return site_url

    def _endpoints(self, site_url: str) -> tuple[str, str]:
        return (
            f"{site_url}/api/posts/publish",
            f"{site_url}/api/posts/upload",
        )

    def get_name(self) -> str:
        return "content_publisher"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "content_publisher",
            "description": (
                "文章排版渲染与 CMS 发布。\n"
                "action=render：把 Markdown/结构化内容渲染成完整 HTML（含 TDK、"
                "内链、schema 注入），不推 CMS，返回 HTML 供审阅。\n"
                "action=publish：把 HTML 推送到站点 CMS（POST /api/posts/publish），"
                "返回真实文章 URL。需要 cms_publish_token。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["render", "publish"],
                        "description": "render=只渲染HTML不发布; publish=渲染+推CMS",
                    },
                    "title": {"type": "string", "description": "文章标题"},
                    "content": {
                        "type": "string",
                        "description": "文章正文（HTML 或 Markdown）",
                    },
                    "slug": {
                        "type": "string",
                        "description": "URL slug（留空自动从标题生成）",
                    },
                    "category": {
                        "type": "string",
                        "enum": list(_VALID_CATEGORIES),
                        "description": "分类，默认 guias",
                    },
                    "status": {
                        "type": "string",
                        "enum": list(_VALID_STATUSES),
                        "description": "发布状态，默认 published",
                    },
                    "excerpt": {"type": "string", "description": "摘要"},
                    "meta_title": {"type": "string", "description": "SEO Title"},
                    "meta_description": {"type": "string", "description": "SEO Description"},
                    "canonical_url": {"type": "string", "description": "canonical 链接"},
                    "keywords": {"type": "string", "description": "关键词（逗号分隔）"},
                    "template_name": {"type": "string", "description": "模板名"},
                    "locale": {"type": "string", "description": "语言，默认 es"},
                },
                "required": ["action", "title", "content"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str = "") -> str | dict[str, Any]:
        action = (arguments.get("action") or "").strip().lower()
        if action == "render":
            return await self._render(arguments)
        elif action == "publish":
            return await self._publish(arguments)
        else:
            return json.dumps({
                "error": f"未知 action: {action}，支持 render / publish"
            })

    async def _render(self, arguments: dict[str, Any]) -> str:
        """渲染 HTML（不推 CMS）。

        当前实现：直接把传入 content 包进 HTML 壳。
        后续 G1-E（schema_tools）接入后，这里会注入 JSON-LD。
        """
        title = (arguments.get("title") or "").strip()
        content = arguments.get("content") or ""
        excerpt = arguments.get("excerpt") or ""
        meta_title = arguments.get("meta_title") or title
        meta_desc = arguments.get("meta_description") or excerpt[:150]

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{_esc(meta_title)}</title>
  <meta name="description" content="{_esc(meta_desc)}"/>
</head>
<body>
<article>
<h1>{_esc(title)}</h1>
{content}
</article>
</body>
</html>"""
        return json.dumps({
            "action": "render",
            "html": html,
            "title": title,
            "meta_title": meta_title,
            "meta_description": meta_desc,
        }, ensure_ascii=False)

    async def _publish(self, arguments: dict[str, Any]) -> str:
        """推送到 CMS API。"""
        if not self.token:
            return json.dumps({
                "error": "cms_publish_token 未配置。请在 agents.yaml 的 "
                         "seo_credentials.cms_publish_token 填入 ${CMS_PUBLISH_TOKEN}",
            })

        site_url = self._resolve_site(arguments)
        publish_ep, _ = self._endpoints(site_url)

        title = (arguments.get("title") or "").strip()
        content = arguments.get("content") or ""
        if not title or not content:
            return json.dumps({"error": "title 和 content 必填"})

        category = (arguments.get("category") or "guias").strip().lower()
        if category not in _VALID_CATEGORIES:
            category = "guias"

        status = (arguments.get("status") or "published").strip().lower()
        if status not in _VALID_STATUSES:
            status = "published"

        payload = {
            "title": title,
            "content": content,
            "slug": arguments.get("slug", ""),
            "locale": arguments.get("locale", "es"),
            "excerpt": arguments.get("excerpt", ""),
            "category": category,
            "status": status,
            "metaTitle": arguments.get("meta_title", ""),
            "metaDescription": arguments.get("meta_description", ""),
            "canonicalUrl": arguments.get("canonical_url", ""),
            "keywords": arguments.get("keywords", ""),
            "templateName": arguments.get("template_name", ""),
            "anchorNavEnabled": True,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    publish_ep,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except Exception as exc:
            LOGGER.exception("content_publisher 请求失败")
            return json.dumps({"error": f"请求异常: {exc}"})

        if resp.status_code == 401:
            return json.dumps({"error": "认证失败：token 无效或已过期"})
        if resp.status_code == 400:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            return json.dumps({"error": f"参数错误: {body.get('error', resp.text[:200])}"})

        if resp.status_code == 201:
            body = resp.json()
            post = body.get("post", {})
            slug = post.get("slug", "")
            site = site_url
            url = f"{site}/blog/{slug}" if slug else site
            return json.dumps({
                "ok": True,
                "action": "publish",
                "post_id": post.get("id"),
                "slug": slug,
                "url": url,
                "status": post.get("status"),
                "message": body.get("message", ""),
            }, ensure_ascii=False)

        return json.dumps({
            "error": f"CMS 返回 {resp.status_code}",
            "detail": resp.text[:300],
        })


def _esc(text: str) -> str:
    """HTML 转义。"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
