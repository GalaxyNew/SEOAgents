"""LLM providers (L3): Anthropic Messages API, OpenAI-compatible, and Mock.

Provider selection (``build_provider``):
  * configured provider with a real api_key -> real HTTP provider
  * otherwise -> ``MockLLMProvider`` so the whole system runs keyless
    (the mock plays a deterministic SEO playbook that exercises real tools).
"""
from __future__ import annotations

import abc
import json
from typing import Any

import httpx

from dojocore.logging import LOGGER
from seoagents.agent.models import ChatMessage, LLMResult, ToolCall
from seoagents.config.models import LLMProvidersConfig

ANTHROPIC_DEFAULT_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class BaseLLMProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    async def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], *, system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResult: ...


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------
class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str = "") -> None:
        self.api_key = api_key
        self.model = model or "claude-sonnet-4-5"
        self.base_url = (base_url or ANTHROPIC_DEFAULT_URL).rstrip("/")

    async def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], *, system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": self._render_messages(messages),
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
                }
                for t in tools
            ]
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
            )
        if resp.status_code != 200:
            LOGGER.error(f"Anthropic API error {resp.status_code}: {resp.text[:300]}")
            return LLMResult(content=f"LLM provider error {resp.status_code}", stop_reason="error")

        data = resp.json()
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(name=block["name"], arguments=block.get("input", {}), id=block["id"])
                )
        usage = data.get("usage", {})
        return LLMResult(
            content="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=data.get("stop_reason", "end_turn"),
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )

    @staticmethod
    def _render_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        rendered: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for call in msg.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                    )
                rendered.append({"role": "assistant", "content": content})
            elif msg.role == "tool":
                rendered.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": res.call_id,
                                "content": res.as_text()[:30000],
                                "is_error": not res.ok,
                            }
                            for res in msg.tool_results
                        ],
                    }
                )
            elif msg.role in ("user", "assistant"):
                rendered.append({"role": msg.role, "content": msg.content})
        return rendered


# ---------------------------------------------------------------------------
# OpenAI-compatible (DeepSeek / GLM / local endpoints)
# ---------------------------------------------------------------------------
class OpenAICompatProvider(BaseLLMProvider):
    name = "openai_compat"

    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"
        self.base_url = base_url.rstrip("/")

    async def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], *, system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResult:
        oai_messages: list[dict[str, Any]] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                oai_messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or None,
                        "tool_calls": [
                            {
                                "id": c.id,
                                "type": "function",
                                "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                            }
                            for c in msg.tool_calls
                        ],
                    }
                )
            elif msg.role == "tool":
                for res in msg.tool_results:
                    oai_messages.append(
                        {"role": "tool", "tool_call_id": res.call_id, "content": res.as_text()[:30000]}
                    )
            else:
                oai_messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                    },
                }
                for t in tools
            ]
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        if resp.status_code != 200:
            LOGGER.error(f"OpenAI-compat API error {resp.status_code}: {resp.text[:300]}")
            return LLMResult(content=f"LLM provider error {resp.status_code}", stop_reason="error")
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {})
        tool_calls = [
            ToolCall(
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"].get("arguments") or "{}"),
                id=tc.get("id", ""),
            )
            for tc in message.get("tool_calls") or []
        ]
        return LLMResult(
            content=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason", "stop"),
            usage=data.get("usage", {}),
        )


# ---------------------------------------------------------------------------
# Mock provider — deterministic SEO playbooks for keyless operation
# ---------------------------------------------------------------------------
class MockLLMProvider(BaseLLMProvider):
    """Plays a fixed tool-call playbook based on the agent role marker.

    The playbook exercises the *real* L4 tools, so keyless runs still produce
    genuine audits, SERP snapshots and interlink injections — only the LLM
    reasoning is scripted.
    """

    name = "mock"

    PLAYBOOKS: dict[str, list[str]] = {
        "auditor": ["site_technical_auditor", "lighthouse_audit"],
        "writer": [],
        "linker": ["nlp_internal_linker"],
        "evolution": [
            "google_seo_monitor",
            "serp_rank_tracker",
            "google_seo_monitor:trends",
            "aeo_visibility_monitor",
        ],
        "default": ["site_technical_auditor"],
    }

    def __init__(self) -> None:
        LOGGER.warning(
            "No LLM api_key configured — using MockLLMProvider (deterministic playbooks). "
            "Set llm_providers.<provider>.api_key in ~/.dojo/agents.yaml for real reasoning."
        )

    async def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]], *, system: str = "",
        max_tokens: int = 2048,
    ) -> LLMResult:
        role = self._detect_role(system)
        playbook = self.PLAYBOOKS.get(role, self.PLAYBOOKS["default"])
        available = {t["name"] for t in tools}
        done = [c.name for m in messages for c in m.tool_calls]
        trends_done = any(
            c.name == "google_seo_monitor" and c.arguments.get("action") == "query_rising_keywords"
            for m in messages
            for c in m.tool_calls
        )

        for step in playbook:
            tool_name, _, variant = step.partition(":")
            if tool_name not in available:
                continue
            if variant == "trends":
                if trends_done:
                    continue
                return LLMResult(
                    tool_calls=[ToolCall(
                        name="google_seo_monitor",
                        arguments={"action": "query_rising_keywords"},
                    )],
                    stop_reason="tool_use",
                )
            if tool_name in done:
                continue
            args = self._default_args(tool_name, messages)
            return LLMResult(
                tool_calls=[ToolCall(name=tool_name, arguments=args)], stop_reason="tool_use"
            )
        return LLMResult(content=self._final_summary(role, messages), stop_reason="end_turn")

    @staticmethod
    def _detect_role(system: str) -> str:
        lowered = system.lower()
        for marker in ("auditor", "writer", "linker", "evolution"):
            if f"role={marker}" in lowered:
                return marker
        return "default"

    @staticmethod
    def _default_args(tool_name: str, messages: list[ChatMessage]) -> dict[str, Any]:
        if tool_name == "google_seo_monitor":
            return {"action": "query_gsc_performance"}
        if tool_name == "nlp_internal_linker":
            # Writer output (or task payload) is expected in the last user message as JSON.
            for msg in reversed(messages):
                if msg.role == "user":
                    try:
                        payload = json.loads(msg.content)
                        if isinstance(payload, dict) and "source_html" in payload:
                            return {
                                "source_html": payload["source_html"],
                                "target_pages": payload.get("target_pages", []),
                            }
                    except (json.JSONDecodeError, TypeError):
                        continue
            return {"source_html": "<p>placeholder</p>", "target_pages": []}
        return {}

    @staticmethod
    def _final_summary(role: str, messages: list[ChatMessage]) -> str:
        tool_stats: list[str] = []
        for msg in messages:
            for res in msg.tool_results:
                status = "ok" if res.ok else "error"
                tool_stats.append(f"{res.name}={status}")
        joined = ", ".join(tool_stats) or "no tools executed"
        if role == "writer":
            return json.dumps(
                {
                    "summary": "内容整改建议(mock): 补全缺失的 meta description 与 H1;"
                    "为核心页补充 FAQ Schema;压缩超长标题至 60 字符内。",
                    "source_html": (
                        "<article><h1>SEO 整改建议</h1><p>本文覆盖 seo agent 与 aeo monitoring "
                        "的最佳实践,并给出结构化数据示例。</p></article>"
                    ),
                },
                ensure_ascii=False,
            )
        return f"[mock:{role}] 任务完成。已执行工具: {joined}。"


def build_provider(config: LLMProvidersConfig) -> BaseLLMProvider:
    active = config.active()
    if active.has_key:
        if config.default_provider == "openai_compat":
            if not active.base_url:
                LOGGER.warning("openai_compat.base_url missing — falling back to mock provider")
                return MockLLMProvider()
            return OpenAICompatProvider(active.api_key, active.model, active.base_url)
        return AnthropicProvider(active.api_key, active.model, active.base_url)
    return MockLLMProvider()


__all__ = [
    "AnthropicProvider",
    "BaseLLMProvider",
    "MockLLMProvider",
    "OpenAICompatProvider",
    "build_provider",
]
