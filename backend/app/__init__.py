"""Tick Stock Panel backend."""

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


# ── 企业代理 SSL 证书绕过 ──
# 华为代理(proxy.huawei.com:8080)用自签名证书拦截 HTTPS,导致 httpx 报
# CERTIFICATE_VERIFY_FAILED。TickFlow SDK 内部创建 httpx.Client/AsyncClient
# 但不暴露 verify 参数,需在 import 最早阶段 monkey-patch 强制 verify=False。
# 注意: httpx.get/post/stream 等便捷函数内部也创建 Client,必须无条件覆盖
# (setdefault 会被显式传 verify=True 的调用绕过)。
import httpx as _httpx

_orig_client_init = _httpx.Client.__init__
_orig_async_client_init = _httpx.AsyncClient.__init__

def _patched_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    return _orig_client_init(self, *args, **kwargs)

def _patched_async_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    return _orig_async_client_init(self, *args, **kwargs)

_httpx.Client.__init__ = _patched_client_init
_httpx.AsyncClient.__init__ = _patched_async_client_init