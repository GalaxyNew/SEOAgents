"""DataForSEO LLM 可见度探针 (L4) —— AEO 的真实测量来源。

AEO 问的是「用户拿 AI 问这类问题时,答案里会不会出现我们」。这没法估算,
只能真的去问一遍。DataForSEO 的 ai_optimization 接口代跑 ChatGPT / Claude /
Perplexity / Gemini 并返回原文,我们在原文里找品牌词。

成本提醒:每个引擎每个 query 都是一次真实 LLM 调用。默认最多取前 3 个
query,四引擎合计 12 次;要改先想清楚这是按次计费的。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from dojocore.logging import LOGGER
from seoagents.tools.aeo_monitor import ProbeUnavailable

# engine_shares 里的键 → DataForSEO 的 llm_type
_ENGINE_TO_LLM: dict[str, str] = {
    "chatgpt": "chat_gpt",
    "claude": "claude",
    "perplexity": "perplexity",
    # Google AI Overview 没有独立接口;用 Gemini 作代理指标,证据里会标注清楚
    "google_aio": "gemini",
}

_PROXY_NOTE = {
    "google_aio": "以 Gemini 作为 Google AI Overview 的代理指标,二者并不等同",
}

MAX_QUERIES = 3


class DataForSeoLlmProbe:
    """一个引擎的可见度探针。"""

    def __init__(
        self,
        engine: str,
        api_key: str,
        base_url: str = "https://api.dataforseo.com",
        *,
        location_name: str = "",
        language_code: str = "",
        max_queries: int = MAX_QUERIES,
    ) -> None:
        if engine not in _ENGINE_TO_LLM:
            raise ValueError(f"不支持的引擎 '{engine}';可选 {sorted(_ENGINE_TO_LLM)}")
        self.engine = engine
        self.llm_type = _ENGINE_TO_LLM[engine]
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.location_name = location_name
        self.language_code = language_code
        self.max_queries = max(1, int(max_queries))
        self.model_version = ""  # 首次探测时确定

    # -- 模型选择 ---------------------------------------------------------
    async def _pick_model(self, client: httpx.AsyncClient) -> str:
        """挑一个支持联网的模型 —— AEO 问的是「现在」的答案,离线模型没意义。"""
        if self.model_version:
            return self.model_version
        url = f"{self.base}/v3/ai_optimization/{self.llm_type}/llm_responses/models"
        resp = await client.get(url, headers={"Authorization": f"Basic {self.api_key}"})
        data = resp.json()
        if int(data.get("status_code", 0)) != 20000:
            raise ProbeUnavailable(f"{self.engine}: 取模型列表失败 {data.get('status_message')}")
        tasks = data.get("tasks") or []
        models = (tasks[0].get("result") or []) if tasks else []
        web = [m for m in models if m.get("web_search_supported")]
        pool = web or models
        if not pool:
            raise ProbeUnavailable(f"{self.engine}: 没有可用模型")
        self.model_version = str(pool[0].get("model_name"))
        return self.model_version

    # -- 单次提问 ---------------------------------------------------------
    async def _ask(self, client: httpx.AsyncClient, model: str, prompt: str) -> str | None:
        url = f"{self.base}/v3/ai_optimization/{self.llm_type}/llm_responses/live"
        body = [{
            "user_prompt": prompt,
            "model_name": model,
            "web_search": True,
        }]
        if self.location_name:
            body[0]["location_name"] = self.location_name
        if self.language_code:
            body[0]["language_code"] = self.language_code
        try:
            resp = await client.post(
                url,
                headers={"Authorization": f"Basic {self.api_key}",
                         "Content-Type": "application/json"},
                json=body,
            )
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(f"{self.engine} 提问失败: {exc}")
            return None
        if int(data.get("status_code", 0)) != 20000:
            LOGGER.warning(f"{self.engine} 返回 {data.get('status_code')}: {data.get('status_message')}")
            return None
        tasks = data.get("tasks") or []
        if not tasks or int(tasks[0].get("status_code", 0)) != 20000:
            LOGGER.warning(f"{self.engine} task 异常: {tasks[0].get('status_message') if tasks else '空'}")
            return None
        results = tasks[0].get("result") or []
        if not results:
            return None
        chunks: list[str] = []
        for item in (results[0].get("items") or []):
            for sec in (item.get("sections") or []):
                t = sec.get("text")
                if t:
                    chunks.append(str(t))
            if item.get("text"):
                chunks.append(str(item["text"]))
        return "\n".join(chunks) if chunks else None

    # -- 对外接口 ---------------------------------------------------------
    async def measure(self, brand: str, queries: list[str]) -> dict[str, Any]:
        if not self.api_key:
            raise ProbeUnavailable(f"{self.engine}: 未配置 DataForSEO 凭证")
        # 关键:剔除本身就含品牌名的查询词。
        # 问「best IGOR IPTV」,AI 复述问题就会出现品牌名,提及率必然 100% ——
        # 那测的是自我复述,不是可见度。AEO 要问的是品类词:用户不知道你的时候,
        # AI 会不会主动提到你。
        needle_pre = re.sub(r"\s+", "", brand).lower()
        usable, self_ref = [], []
        for q in queries:
            if not q:
                continue
            if needle_pre and needle_pre in re.sub(r"\s+", "", q).lower():
                self_ref.append(q)
            else:
                usable.append(q)
        if not usable:
            raise ProbeUnavailable(
                f"{self.engine}: 全部查询词都含品牌名 {self_ref} —— "
                f"这样测出的提及率恒为 100%,是自我复述而非可见度。"
                f"请在 aeo.queries 里配置品类词(如「mejor iptv españa」)"
            )
        picked = usable[: self.max_queries]

        # 品牌匹配放宽到「去掉空格后包含」,避免 "Mejors IPTV" / "MejorsIPTV" 漏判
        needle = re.sub(r"\s+", "", brand).lower()
        hits = 0
        evidence: dict[str, Any] = {}

        async with httpx.AsyncClient(timeout=180.0) as client:
            model = await self._pick_model(client)
            answers = await asyncio.gather(
                *[self._ask(client, model, q) for q in picked], return_exceptions=True
            )

        measured = 0
        for q, ans in zip(picked, answers):
            if isinstance(ans, Exception) or ans is None:
                evidence[q] = {"measured": False, "reason": "本次未取得回答"}
                continue
            measured += 1
            flat = re.sub(r"\s+", "", ans).lower()
            mentioned = needle in flat
            hits += 1 if mentioned else 0
            evidence[q] = {
                "measured": True,
                "mentioned": mentioned,
                "excerpt": ans[:200],
            }

        if measured == 0:
            raise ProbeUnavailable(f"{self.engine}: {len(picked)} 个查询全部未取得回答")

        note = _PROXY_NOTE.get(self.engine)
        return {
            "mention_rate": hits / measured,
            "hits": hits,
            "total": measured,
            "evidence": {
                "model": self.model_version,
                "llm_type": self.llm_type,
                **({"excluded_self_referential": self_ref} if self_ref else {}),
                "location": self.location_name or "(未指定)",
                "queries": evidence,
                **({"proxy_note": note} if note else {}),
            },
        }


def build_probes(config: Any) -> dict[str, DataForSeoLlmProbe]:
    """按配置装出全部可用探针;没凭证就返回空字典,让 AEO 如实报 UNAVAILABLE。"""
    key = (getattr(config.seo_credentials, "dataforseo_api_key", "") or "").strip()
    if not key or key.startswith("${"):
        LOGGER.info("未配置 DataForSEO 凭证,AEO 探针不装配")
        return {}
    base = getattr(config.seo_credentials, "dataforseo_base_url", "https://api.dataforseo.com")
    loc = getattr(config.sites, "serp_location_name", "") or ""
    lang = getattr(config.sites, "serp_language_code", "") or ""
    probes: dict[str, DataForSeoLlmProbe] = {}
    for engine in config.aeo.engine_shares:
        if engine not in _ENGINE_TO_LLM:
            LOGGER.warning(f"AEO 引擎 '{engine}' 没有对应的 DataForSEO 通道,跳过")
            continue
        probes[engine] = DataForSeoLlmProbe(
            engine, key, base, location_name=loc, language_code=lang
        )
    LOGGER.info(f"AEO 探针已装配: {sorted(probes)}")
    return probes


__all__ = ["DataForSeoLlmProbe", "build_probes"]
