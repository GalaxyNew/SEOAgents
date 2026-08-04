#!/usr/bin/env python3
"""拆 config —— 12 号文 §5:「通用部分迁 dojocore,部门专属字段留部门」。

这一步和前面几个模块不同:config 不能整个搬。里面既有 SandboxConfig、
LLMProvidersConfig 这种任何部门都要的,也有 SitesConfig、SeoCredentialsConfig
这种只有 SEO 部门才有的。整个搬过去,SearchAgents 就得继承一堆 GSC 字段;
整个留下,框架又够不到沙箱策略。

拆法:按「换个部门还成不成立」判断。
  * 沙箱约束、LLM 提供方、MCP 服务器、协作端点、网关、调度器、存储目录
    —— 换成检索部照样需要 → 框架
  * GSC 凭证、站点清单、M_t 权重、AEO 引擎份额
    —— 只有 SEO 有 → 部门
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path("/data/seoagents")
SRC = ROOT / "seoagents" / "config" / "models.py"
DST_DIR = ROOT / "dojocore" / "config"

GENERIC = ["AppConfig", "LLMProviderConfig", "LLMProvidersConfig", "MCPServerConfig",
           "CollabConfig", "SandboxConfig", "GatewayConfig", "SchedulerConfig",
           "StorageConfig"]

text = SRC.read_text(encoding="utf-8")

# 头部:import 与私有工具函数,两边都要
head_end = text.index("@dataclass(frozen=True)")
header = text[:head_end]

# 按 @dataclass 边界切块
blocks: list[tuple[str, str]] = []
parts = re.split(r"(?=@dataclass\(frozen=True\)\nclass )", text[head_end:])
for part in parts:
    m = re.search(r"class (\w+)", part)
    if m:
        blocks.append((m.group(1), part))

generic_src = "".join(b for n, b in blocks if n in GENERIC)
dept_src = "".join(b for n, b in blocks if n not in GENERIC)

DST_DIR.mkdir(parents=True, exist_ok=True)
(DST_DIR / "__init__.py").write_text("", encoding="utf-8")

(DST_DIR / "models.py").write_text(
    '"""框架级配置模型 (L1) —— 部门无关的那部分。\n\n'
    "判据是「换个部门还成不成立」:沙箱约束、LLM 提供方、MCP 服务器、协作端点、\n"
    "网关、调度器、存储目录 —— 检索部照样需要,所以归框架。GSC 凭证、站点清单、\n"
    "M_t 权重那些只有 SEO 有的,留在 ``seoagents.config.models``。\n\n"
    "这么拆的实际后果:SearchAgents 只 import dojocore 就能拿到沙箱与 LLM 配置,\n"
    '不必把一堆 GSC 字段一起拖进来。\n"""\n'
    + header[header.index("from __future__"):]
    + generic_src,
    encoding="utf-8",
)

new_dept = (
    header
    + "# 框架级配置模型从 dojocore 取。它们不随部门变化 —— 换成检索部,\n"
    + "# 沙箱约束和 LLM 提供方的形状一模一样。\n"
    + "from dojocore.config.models import (  # noqa: F401\n"
    + "".join(f"    {n},\n" for n in GENERIC)
    + ")\n\n"
    + dept_src
)
SRC.write_text(new_dept, encoding="utf-8")

print(f"  ✓ 框架级 {len(GENERIC)} 个类 → dojocore/config/models.py")
print(f"  ✓ 部门专属 {len(blocks) - len(GENERIC)} 个类留在 seoagents/config/models.py")
print("    框架级:", ", ".join(GENERIC))
print("    部门级:", ", ".join(n for n, _ in blocks if n not in GENERIC))
