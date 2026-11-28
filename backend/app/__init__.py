"""Tick Stock Panel backend."""

import os
import sys

__version__ = "0.2.4"

# Windows 默认 stdout/stderr 编码为 GBK(cp936),TickFlow SDK 内部输出含 emoji 的
# 指数/标的名称(如 \U0001f193)时会抛 UnicodeEncodeError,导致请求失败。
# 进程加载最早阶段强制 UTF-8,根治此类编码崩溃。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


# 企业代理 TLS 拦截环境 opt-in: 代理对 HTTPS 做自签名证书拦截, 默认证书链校验
# 会报 UnknownIssuer。设 TSP_HTTPX_INSECURE=1 时, 对【未显式指定 verify】的
# httpx 客户端放宽证书校验; 调用方显式传入的 verify (如 CZSC_SERVE_VERIFY_SSL
# 控制的东财兜底) 不被覆盖。不设置该变量则零副作用, 保持默认严格校验 —
# 无代理环境/其他用户/CI 不受任何影响。
if os.environ.get("TSP_HTTPX_INSECURE", "").strip().lower() in ("1", "true", "yes", "on"):
    import httpx as _httpx

    _orig_client_init = _httpx.Client.__init__
    _orig_async_client_init = _httpx.AsyncClient.__init__

    def _patched_client_init(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        return _orig_client_init(self, *args, **kwargs)

    def _patched_async_client_init(self, *args, **kwargs):
        kwargs.setdefault("verify", False)
        return _orig_async_client_init(self, *args, **kwargs)

    _httpx.Client.__init__ = _patched_client_init
    _httpx.AsyncClient.__init__ = _patched_async_client_init
