"""InternalLinkerSpec (L4) — TF-IDF internal-link recommendation & injection.

Fixed rewrite of manual §4.2:
  * ``json`` imported (missing in the manual)
  * the TF-IDF matrix is actually *used*: target pages are ranked by cosine
    similarity against the source document, so the most relevant pages get
    linked first when anchor mentions overlap
  * regex injection is HTML-aware: skips text already inside <a> tags and
    never injects inside tag attributes
  * one link per target page (over-optimization guard, per the manual)
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from dojocore.logging import LOGGER
from dojocore.quality import real, unavailable
from seoagents.tools.base import BaseToolSpec


class InternalLinkerSpec(BaseToolSpec):
    """自动化 NLP 内链推荐与 HTML 锚文本植入."""

    def get_name(self) -> str:
        return "nlp_internal_linker"

    def get_schema(self) -> dict[str, Any]:
        return {
            "name": "nlp_internal_linker",
            "description": (
                "基于 TF-IDF 语义矩阵匹配,自动比对目标整站现有文章库,"
                "输出最相关的锚文本推荐并在 HTML 中安全植入内链 (每个落地页至多一条)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_html": {
                        "type": "string",
                        "description": "待植入内链的 HTML 富文本源码",
                    },
                    "target_pages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "拟导向的落地页 URL"},
                                "anchor_candidates": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "该落地页可匹配的锚文本关键词列表",
                                },
                            },
                            "required": ["url", "anchor_candidates"],
                        },
                        "description": "整站现有核心页面及对应关键词映射列表",
                    },
                    "max_links": {
                        "type": "integer",
                        "default": 5,
                        "description": "本篇文档允许注入的内链总数上限",
                    },
                },
                "required": ["source_html", "target_pages"],
            },
        }

    async def execute(self, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
        source_html: str = arguments["source_html"]
        target_pages: list[dict[str, Any]] = list(arguments["target_pages"])
        max_links = int(arguments.get("max_links", 5))
        LOGGER.info(
            f"InternalLinker processing {len(target_pages)} target pages session={session_id}"
        )

        soup = BeautifulSoup(source_html, "html.parser")
        text_content = soup.get_text(" ", strip=True)
        if not text_content or not target_pages:
            return unavailable(
                source="nlp_internal_linker",
                reason="source_html 无正文文本,或 target_pages 为空",
            )

        ranked = self._rank_pages_by_similarity(text_content, target_pages)

        linked_count = 0
        injections: list[dict[str, Any]] = []
        modified_html = source_html
        already_linked_urls = {a.get("href") for a in soup.find_all("a")}

        for score, page in ranked:
            if linked_count >= max_links:
                break
            url = page["url"]
            if url in already_linked_urls:
                continue
            anchors = sorted(page.get("anchor_candidates", []), key=len, reverse=True)
            for anchor in anchors:
                new_html, injected = self._inject_anchor(modified_html, anchor, url)
                if injected:
                    modified_html = new_html
                    linked_count += 1
                    injections.append(
                        {"url": url, "anchor": anchor, "similarity": round(float(score), 4)}
                    )
                    break  # 每个目标落地页只建立一条最优锚文本,规避过度链接惩罚

        # Pure local computation over caller-supplied input: always REAL,
        # there is no external source that could degrade.
        return real(
            {
                "linked_links_injected": linked_count,
                "injections": injections,
                "optimized_html": modified_html,
            },
            source="nlp_internal_linker",
        )

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _rank_pages_by_similarity(
        text_content: str, target_pages: list[dict[str, Any]]
    ) -> list[tuple[float, dict[str, Any]]]:
        corpus = [text_content]
        for page in target_pages:
            corpus.append(" ".join(page.get("anchor_candidates", [])) or page.get("url", ""))
        try:
            vectorizer = TfidfVectorizer(stop_words="english")
            tfidf_matrix = vectorizer.fit_transform(corpus)
            sims = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
        except ValueError:  # e.g. corpus of pure stop words
            sims = [0.0] * len(target_pages)
        ranked = sorted(zip(sims, target_pages), key=lambda pair: pair[0], reverse=True)
        return [(float(s), p) for s, p in ranked]

    @staticmethod
    def _inject_anchor(html: str, anchor: str, url: str) -> tuple[str, bool]:
        """Replace the first safe occurrence of ``anchor`` with a link.

        Safety rules: case-insensitive whole-word match; skip matches inside
        existing <a>...</a> ranges; skip matches inside tag markup.
        """
        if not anchor.strip():
            return html, False
        pattern = re.compile(rf"\b({re.escape(anchor)})\b", re.IGNORECASE)

        # Pre-compute spans to skip: existing anchor elements + raw tags.
        skip_spans: list[tuple[int, int]] = [
            m.span() for m in re.finditer(r"<a\b.*?</a>", html, re.IGNORECASE | re.DOTALL)
        ]
        skip_spans += [m.span() for m in re.finditer(r"<[^>]*>", html)]

        def in_skip(start: int, end: int) -> bool:
            return any(s <= start < e or s < end <= e for s, e in skip_spans)

        for match in pattern.finditer(html):
            if in_skip(*match.span()):
                continue
            replacement = f'<a href="{url}" title="{anchor} relative link">{match.group(1)}</a>'
            return html[: match.start()] + replacement + html[match.end():], True
        return html, False


__all__ = ["InternalLinkerSpec"]
