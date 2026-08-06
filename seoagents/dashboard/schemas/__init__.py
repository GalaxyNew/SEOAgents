"""Pydantic request/response models for dashboard APIs (L2)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AuditRunRequest(BaseModel):
    url: str | None = Field(default=None, description="审计起始 URL;缺省用配置站点")
    max_pages: int = Field(default=25, ge=1, le=100)


class AgentTaskRequest(BaseModel):
    task: str = Field(min_length=1, description="交给智能体回路的自然语言任务")
    role: str = Field(default="default", description="auditor | writer | linker | default")
    conversation_id: str | None = Field(
        default=None, max_length=128,
        description="前端会话 ID；用于绑定持久对话、运行状态和 Hermes transcript",
    )
    provider: str | None = Field(
        default=None, max_length=80,
        description="Hermes 已认证 provider；必须来自后端模型目录",
    )
    model: str | None = Field(
        default=None, max_length=200,
        description="会话模型；必须属于所选 provider 的后端模型目录",
    )
    reasoning_effort: str | None = Field(
        default=None, max_length=32,
        description="推理强度；必须来自所选 provider/model 的官方能力目录；auto 表示不覆盖模型默认值",
    )


class PipelineRequest(BaseModel):
    target_url: str | None = None


class SkillReplayRequest(BaseModel):
    skill_id: str


class MetricsSummary(BaseModel):
    site: str
    latest_m_t: float | None
    m_t_history: list[dict[str, Any]]
    serp_positions: list[dict[str, Any]]
    aeo_visibility: list[dict[str, Any]]
    v_t: float | None
    open_dead_links: int
    skills: list[dict[str, Any]]
    provider: str


class GenericResult(BaseModel):
    ok: bool = True
    data: Any = None
    error: str = ""
