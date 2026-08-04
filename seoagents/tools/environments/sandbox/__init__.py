"""兼容层 —— 真身已迁至 ``dojocore.tools.environments.sandbox``(12 号文 §5)。

SEO 专属的 ``seo_audit_sandbox`` 留在本包内:它约束的是站点审计爬虫,
换个部门就不成立。
"""
from dojocore.tools.environments.sandbox import (  # noqa: F401
    SandboxPolicy,
    SandboxViolation,
)
