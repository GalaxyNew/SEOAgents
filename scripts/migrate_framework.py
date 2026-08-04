#!/usr/bin/env python3
"""框架层搬运工具(12 号文 §5)。

把通用模块从 `seoagents` 迁进 `dojocore`,老路径留兼容层。

为什么留兼容层而不是一次性改完所有引用:这批文件有 60 多处被引用,
一次性改完再跑测试,红了根本分不清是哪一步搬错的。留 shim 就能一批一批
搬、一批一批验,任何一步红了都能立刻定位。等全部搬完、引用也都改到新路径
之后,再统一把 shim 删掉。

用法:
    python migrate.py <模块相对路径> [...]
例:
    python migrate.py agent/models.py tools/base.py
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path("/data/seoagents")
SRC_PKG = ROOT / "seoagents"
DST_PKG = ROOT / "dojocore"

# 已经搬到 dojocore 的模块 —— 搬运时顺手把 import 改到新路径
MOVED = [
    "agent.models", "agent.providers", "agent.loop",
    "tools.base", "tools.executor", "tools.environments.sandbox",
    "utils.event_bus", "skills.manager",
    "config.generic",
]


def rewrite_imports(text: str) -> str:
    for mod in MOVED:
        text = text.replace(f"from seoagents.{mod} import", f"from dojocore.{mod} import")
        text = text.replace(f"import seoagents.{mod}", f"import dojocore.{mod}")
    return text


def public_names(text: str) -> list[str]:
    """从 __all__ 或顶层定义里推出要 re-export 的名字。"""
    m = re.search(r"__all__\s*=\s*\[(.*?)\]", text, re.S)
    if m:
        return re.findall(r"[\"']([^\"']+)[\"']", m.group(1))
    names = re.findall(r"^(?:class|def|async def)\s+(\w+)", text, re.M)
    names += re.findall(r"^([A-Z][A-Z0-9_]*)\s*=", text, re.M)
    return [n for n in dict.fromkeys(names) if not n.startswith("_")]


def migrate(rel: str) -> None:
    src = SRC_PKG / rel
    dst = DST_PKG / rel
    if not src.is_file():
        sys.exit(f"✗ 源文件不存在: {src}")
    if dst.exists():
        print(f"  ⏭  已迁过,跳过 {rel}")
        return

    text = src.read_text(encoding="utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    for parent in dst.parents:
        if parent == DST_PKG:
            break
        init = parent / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")

    dst.write_text(rewrite_imports(text), encoding="utf-8")

    mod = rel[:-3].replace("/", ".")
    names = public_names(text)
    shim = (
        f'"""兼容层 —— 真身已迁至 ``dojocore.{mod}``(12 号文 §5 框架分层)。\n\n'
        f"这个文件只是转发。它存在是为了让搬运可以分批做:一次性改完 60 多处\n"
        f"引用再跑测试,红了分不清是哪一步搬错的。等引用都改到新路径之后,\n"
        f'这层会被删掉。\n"""\n'
        f"from dojocore.{mod} import *  # noqa: F401,F403\n"
        f"from dojocore.{mod} import (  # noqa: F401\n"
        + "".join(f"    {n},\n" for n in names)
        + ")\n"
    )
    src.write_text(shim, encoding="utf-8")
    print(f"  ✓ {rel}  →  dojocore/{rel}  (兼容层导出 {len(names)} 个名字)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for rel in sys.argv[1:]:
        migrate(rel)
