"""兼容层 —— 真身已迁至 ``dojocore.tools.executor``(12 号文 §5 框架分层)。

这个文件只是转发。它存在是为了让搬运可以分批做:一次性改完 60 多处
引用再跑测试,红了分不清是哪一步搬错的。等引用都改到新路径之后,
这层会被删掉。
"""
from dojocore.tools.executor import *
from dojocore.tools.executor import (  # noqa: F401
    ToolExecutor,
    active_runtime_metadata,
    active_session_id,
)
