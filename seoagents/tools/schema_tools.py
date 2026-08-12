"""
schema_tools — JSON-LD 结构化数据生成 + 验证（G1-E）

28 号文 §八 G1-E 验收门禁：
  生成的 schema 通过 Google Rich Results Test。

实现：
  generate — 根据 page_type + content 生成 JSON-LD（Article/BreadcrumbList/FAQPage/HowTo/Product）
  validate — 用 Google Rich Results API 验证（免费，不花 DataForSEO 的钱）
  inject   — 把 JSON-LD <script> 注入 HTML head

Google Rich Results API：
  POST https://search.google.com/test/rich-results
  （实际上 Google 没有公开 REST API，验证走 https://validator.schema.org/lite）
  改用 https://search.google.com/test/rich-results?url=<URL> 做 URL 级验证
  或结构化数据自行校验（schema.org 规范 + 必填字段检查）
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from seoagents.tools.base import BaseToolSpec

LOGGER = logging.getLogger("seoagents")


class SchemaToolsSpec(BaseToolSpec):
    """JSON-LD 结构化数据生成 + 验证。"""

    def __init__(self, config: Any = None, store: Any = None) -> None:
        self.config = config

    def get_name(self) -> str:
        return "schema_tools"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "schema_tools",
            "description": (
                "JSON-LD 结构化数据工具。\n"
                "action=generate：按 page_type 生成 JSON-LD（Article/BreadcrumbList/"
                "FAQPage/HowTo/Product/Organization/WebSite）\n"
                "action=validate：校验 JSON-LD 必填字段完整性 + schema.org 规范\n"
                "action=inject：把 JSON-LD script 注入 HTML head"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["generate", "validate", "inject"],
                    },
                    "page_type": {
                        "type": "string",
                        "enum": ["Article", "BreadcrumbList", "FAQPage", "HowTo",
                                 "Product", "Organization", "WebSite"],
                        "description": "页面类型（generate 必填）",
                    },
                    "data": {
                        "type": "object",
                        "description": "生成或验证的数据（generate 传字段值；validate 传完整 JSON-LD）",
                    },
                    "html": {
                        "type": "string",
                        "description": "inject 时要注入的 HTML",
                    },
                    "json_ld": {
                        "type": "string",
                        "description": "inject 时要注入的 JSON-LD 字符串",
                    },
                    "site_url": {"type": "string"},
                    "site_name": {"type": "string"},
                },
                "required": ["action"],
            },
        }

    async def execute(
        self, arguments: dict[str, Any], session_id: str = ""
    ) -> str | dict[str, Any]:
        action = (arguments.get("action") or "").strip().lower()
        if action == "generate":
            return await self._generate(arguments)
        elif action == "validate":
            return self._validate(arguments)
        elif action == "inject":
            return self._inject(arguments)
        return json.dumps({"error": f"未知 action: {action}"})

    # ── generate ──────────────────────────────────────────────

    async def _generate(self, args: dict[str, Any]) -> str:
        page_type = args.get("page_type", "Article")
        data = args.get("data") or {}
        site_url = args.get("site_url", "")
        site_name = args.get("site_name", "")

        generators = {
            "Article": self._gen_article,
            "BreadcrumbList": self._gen_breadcrumb,
            "FAQPage": self._gen_faq,
            "HowTo": self._gen_howto,
            "Product": self._gen_product,
            "Organization": self._gen_organization,
            "WebSite": self._gen_website,
        }

        gen = generators.get(page_type)
        if not gen:
            return json.dumps({"error": f"不支持的 page_type: {page_type}"})

        jsonld = gen(data, site_url, site_name)
        return json.dumps({
            "action": "generate",
            "page_type": page_type,
            "json_ld": jsonld,
            "json_ld_str": json.dumps(jsonld, ensure_ascii=False),
        }, ensure_ascii=False)

    def _gen_article(self, d: dict, site: str, name: str) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": d.get("title", ""),
            "description": d.get("description", ""),
            "image": d.get("image", ""),
            "datePublished": d.get("date_published", ""),
            "dateModified": d.get("date_modified", ""),
            "author": {
                "@type": "Organization",
                "name": d.get("author", name or ""),
            },
            "publisher": {
                "@type": "Organization",
                "name": name or "",
                "logo": {"@type": "ImageObject", "url": d.get("logo", "")},
            },
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": d.get("url", site),
            },
        }

    def _gen_breadcrumb(self, d: dict, site: str, name: str) -> dict:
        items = d.get("items", [])
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "name": item.get("name", ""),
                    "item": item.get("url", ""),
                }
                for i, item in enumerate(items)
            ],
        }

    def _gen_faq(self, d: dict, site: str, name: str) -> dict:
        qa = d.get("questions", [])
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": q.get("question", ""),
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": q.get("answer", ""),
                    },
                }
                for q in qa
            ],
        }

    def _gen_howto(self, d: dict, site: str, name: str) -> dict:
        steps = d.get("steps", [])
        return {
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": d.get("title", ""),
            "description": d.get("description", ""),
            "step": [
                {
                    "@type": "HowToStep",
                    "position": i + 1,
                    "name": s.get("name", ""),
                    "text": s.get("text", ""),
                }
                for i, s in enumerate(steps)
            ],
        }

    def _gen_product(self, d: dict, site: str, name: str) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": d.get("name", ""),
            "description": d.get("description", ""),
            "brand": {"@type": "Brand", "name": name or ""},
            "offers": {
                "@type": "Offer",
                "price": d.get("price", ""),
                "priceCurrency": d.get("currency", "EUR"),
                "availability": f"https://schema.org/{d.get('availability', 'InStock')}",
            },
        }

    def _gen_organization(self, d: dict, site: str, name: str) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": name or d.get("name", ""),
            "url": site,
            "logo": d.get("logo", ""),
            "sameAs": d.get("social_links", []),
        }

    def _gen_website(self, d: dict, site: str, name: str) -> dict:
        return {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": name or "",
            "url": site,
            "potentialAction": {
                "@type": "SearchAction",
                "target": f"{site}/search?q={{search_term_string}}",
                "query-input": "required name=search_term_string",
            },
        }

    # ── validate ──────────────────────────────────────────────

    # 各类型必填字段（Google Rich Results 要求）
    REQUIRED_FIELDS = {
        "Article": ["headline", "author", "datePublished", "image"],
        "BreadcrumbList": ["itemListElement"],
        "FAQPage": ["mainEntity"],
        "HowTo": ["name", "step"],
        "Product": ["name", "offers"],
    }

    def _validate(self, args: dict[str, Any]) -> str:
        """校验 JSON-LD 必填字段完整性。"""
        data = args.get("data")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                return json.dumps({"valid": False, "error": f"JSON 解析失败: {e}"})

        if not isinstance(data, dict):
            return json.dumps({"valid": False, "error": "data 必须是 JSON-LD 对象"})

        jsonld_type = data.get("@type", "")
        context = data.get("@context", "")

        errors: list[str] = []
        warnings: list[str] = []

        # 检查 @context
        if context != "https://schema.org":
            errors.append(f"@context 应为 'https://schema.org'，实际 '{context}'")

        # 检查 @type
        if not jsonld_type:
            errors.append("缺少 @type 字段")

        # 检查必填字段
        required = self.REQUIRED_FIELDS.get(jsonld_type, [])
        for field in required:
            val = data.get(field)
            if val is None or val == "" or val == []:
                errors.append(f"缺少必填字段: {field}")

        # 常见质量检查
        if jsonld_type == "Article":
            author = data.get("author", {})
            if isinstance(author, dict) and not author.get("name"):
                warnings.append("Article.author.name 为空")
            img = data.get("image", "")
            if isinstance(img, str) and not img.startswith("http"):
                warnings.append("Article.image 应为完整 URL")

        valid = len(errors) == 0
        return json.dumps({
            "action": "validate",
            "valid": valid,
            "type": jsonld_type,
            "errors": errors,
            "warnings": warnings,
            "message": "Schema 验证通过" if valid else f"{len(errors)} 个错误",
        }, ensure_ascii=False)

    # ── inject ────────────────────────────────────────────────

    def _inject(self, args: dict[str, Any]) -> str:
        """把 JSON-LD <script> 注入 HTML head。"""
        html = args.get("html") or ""
        jsonld_str = args.get("json_ld") or ""

        if isinstance(args.get("data"), dict):
            jsonld_str = json.dumps(args["data"], ensure_ascii=False)
        elif isinstance(args.get("data"), str):
            jsonld_str = args["data"]

        if not html or not jsonld_str:
            return json.dumps({"error": "html 和 json_ld/data 都必填"})

        script_tag = (
            f'\n<script type="application/ld+json">\n{jsonld_str}\n</script>'
        )

        # 注入 </head> 前；没有 head 就加在 <html> 后
        if "</head>" in html:
            html = html.replace("</head>", f"{script_tag}\n</head>", 1)
        elif "<body" in html:
            html = html.replace("<body", f"{script_tag}\n<body", 1)
        else:
            html = script_tag + "\n" + html

        return json.dumps({
            "action": "inject",
            "html": html,
            "injected": True,
        }, ensure_ascii=False)
