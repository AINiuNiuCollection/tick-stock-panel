"""分析层异常与 HTTP 状态映射。

独立成模块, 让 domain / application / api 都能引用而不依赖 analyzer 编排。
"""
from __future__ import annotations


class AnalyzerError(Exception):
    """分析层异常。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def error_status(code: str) -> int:
    """业务错误默认 503 (可重试), 仅未预期内部错误用 500。"""
    return 500 if code == "INTERNAL_ERROR" else 503
