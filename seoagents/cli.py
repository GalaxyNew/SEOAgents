"""``seoagents`` console entry point (L2/CLI)."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from seoagents import __version__
from seoagents.logging import LOGGER

_EXAMPLE_CONFIG = Path(__file__).parent.parent / "config" / "agents.example.yaml"


def _cmd_dashboard(args: argparse.Namespace) -> int:
    import uvicorn

    from seoagents.dashboard.server import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_evolve(_: argparse.Namespace) -> int:
    from seoagents.agent.runtime import get_runtime
    from seoagents.cron.seo_evo_jobs import run_seo_self_evolution_pipeline

    summary = asyncio.run(run_seo_self_evolution_pipeline(get_runtime()))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_audit(args: argparse.Namespace) -> int:
    from seoagents.agent.models import ToolCall
    from seoagents.agent.runtime import get_runtime

    rt = get_runtime()
    call_args = {"max_pages": args.max_pages}
    if args.url:
        call_args["start_url"] = args.url
    res = asyncio.run(
        rt.executor.execute_one(
            ToolCall(name="site_technical_auditor", arguments=call_args), session_id="cli:audit"
        )
    )
    print(res.as_text())
    return 0 if res.ok else 1


def _cmd_agent(args: argparse.Namespace) -> int:
    from seoagents.agent.runtime import get_runtime
    from seoagents.multi_agent.orchestrator import AUDITOR, LINKER, WRITER

    roles = {"auditor": AUDITOR, "writer": WRITER, "linker": LINKER}
    role = roles.get(args.role)
    rt = get_runtime()
    result = asyncio.run(
        rt.loop.run(
            args.task,
            system=role.system_prompt if role else "role=default 你是 SEOAgents 的通用 SEO 智能体。",
            allowed_tools=set(role.allowed_tools) if role and role.allowed_tools else None,
        )
    )
    print(result.final_text)
    if args.trace:
        print("\n--- trace ---")
        print(json.dumps(result.trace_dicts(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _cmd_pipeline(args: argparse.Namespace) -> int:
    from seoagents.agent.runtime import get_runtime

    rt = get_runtime()
    result = asyncio.run(rt.orchestrator.run_content_pipeline(args.url))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_skills(args: argparse.Namespace) -> int:
    from seoagents.agent.runtime import get_runtime

    rt = get_runtime()
    if args.skills_cmd == "list":
        print(json.dumps(rt.skill_manager.list_skills(), ensure_ascii=False, indent=2))
        return 0
    if args.skills_cmd == "replay":
        results = asyncio.run(rt.skill_compiler.execute_skill(args.skill_id, rt.executor))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    return 1


def _cmd_config_init(args: argparse.Namespace) -> int:
    from seoagents.config.loader import DEFAULT_CONFIG_PATH

    target = Path(args.path or DEFAULT_CONFIG_PATH).expanduser()
    if target.exists() and not args.force:
        LOGGER.error(f"{target} already exists (use --force to overwrite)")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if _EXAMPLE_CONFIG.exists():
        target.write_text(_EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    else:  # installed as a wheel without the example file
        target.write_text("app:\n  host: 127.0.0.1\n  port: 8765\n", encoding="utf-8")
    print(f"Config template written to {target} — 填入密钥后即可切换真实 API 模式。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seoagents",
        description="SEOAgents — 自进化 SEO/AEO 智能体集群 (DojoAgents 七层架构)",
    )
    parser.add_argument("--version", action="version", version=f"seoagents {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("dashboard", help="启动 L1/L2 看板与 API 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=_cmd_dashboard)

    p = sub.add_parser("evolve", help="立即执行一轮自进化闭环流水线")
    p.set_defaults(func=_cmd_evolve)

    p = sub.add_parser("audit", help="对站点执行技术审计")
    p.add_argument("url", nargs="?", default=None)
    p.add_argument("--max-pages", type=int, default=25)
    p.set_defaults(func=_cmd_audit)

    p = sub.add_parser("agent", help="运行一次智能体回路任务")
    p.add_argument("task")
    p.add_argument("--role", default="default", choices=["default", "auditor", "writer", "linker"])
    p.add_argument("--trace", action="store_true")
    p.set_defaults(func=_cmd_agent)

    p = sub.add_parser("pipeline", help="运行 Auditor->Writer->Linker 内容整改流水线")
    p.add_argument("url", nargs="?", default=None)
    p.set_defaults(func=_cmd_pipeline)

    p = sub.add_parser("skills", help="技能管理")
    skills_sub = p.add_subparsers(dest="skills_cmd", required=True)
    skills_sub.add_parser("list", help="列出全部技能").set_defaults(func=_cmd_skills)
    replay = skills_sub.add_parser("replay", help="免 LLM 重放已固化技能")
    replay.add_argument("skill_id")
    replay.set_defaults(func=_cmd_skills)

    p = sub.add_parser("config", help="配置管理")
    config_sub = p.add_subparsers(dest="config_cmd", required=True)
    init = config_sub.add_parser("init", help="生成 agents.yaml 配置模版")
    init.add_argument("--path", default=None)
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=_cmd_config_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
