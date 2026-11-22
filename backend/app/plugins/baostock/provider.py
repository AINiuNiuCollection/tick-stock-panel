"""Baostock (证券宝) 内置数据源 provider。

方法签名对齐 custom.GenericHTTPProvider (service 分流点按这套签名调用),
注入 custom loader 注册表后, 各 service 无需改动即可路由到本 provider。

实现数据集:
  - daily       A 股日K (1990-12-19 起, 频率 d/w/m), adjustflag=2 前复权
  - minute      A 股分钟K (2015-01-01 起, 频率 5/15/30/60 分钟)
  - adj_factor  除权因子 (baostock query_adjust_factor 接口)

未声明 realtime / depth5 / financial → provider_has_dataset 为 False, 自动回退 tickflow。

单位与口径 (CONTRIBUTING §3.1, 不可凭字段名推断):
  - baostock 价格为元 (float), 直接透传
  - baostock volume 为股, 本项目日K/分钟契约均为手 → 统一 ÷100
  - baostock amount 单位元, 直接透传
  - 日K取前复权 (adjustflag=2), 与工程 enriched 前复权口径一致
  - 分钟 datetime 为北京墙钟 naive (baostock 已是北京时间)

网络特性:
  - baostock SDK 走 socket 协议 (baostock.com:10087), 非 HTTP
  - 企业 HTTP 代理通常不拦截 socket, 但需实测连通性
  - 免费无 token: bs.login() 即可, 返回 user_id
  - 串行查询: 同一进程同一 session, 查询完成后 bs.logout() 释放
"""
from __future__ import annotations

import logging
import os
import socket as _socket
import threading
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

# 只声明真实提供的数据集; 其余数据集 provider_has_dataset 返回 False → 回退 tickflow
_DATASETS = ("daily", "minute", "adj_factor")

# 工程中文频率 → baostock frequency 字符串
# baostock: d=日 w=周 m=月 5=5分钟 15=15分钟 30=30分钟 60=60分钟
_FREQ_MAP: dict[str, str] = {
    "日线": "d",
    "日": "d",
    "1d": "d",
    "周线": "w",
    "周": "w",
    "1w": "w",
    "月线": "m",
    "月": "m",
    "1M": "m",
    "5分钟": "5",
    "5m": "5",
    "1m": "5",  # 工程 1m 近似为 baostock 最小 5 分钟 (baostock 不支持 1 分钟历史)
    "15分钟": "15",
    "15m": "15",
    "30分钟": "30",
    "30m": "30",
    "60分钟": "60",
    "60m": "60",
    "1h": "60",
}

# 工程 symbol (600519.SH) → baostock code (sh.600519)
def _symbol_to_baostock_code(symbol: str) -> str | None:
    """工程 symbol 转 baostock code。

    工程格式: 600519.SH / 000001.SZ / 830799.BJ
    baostock 格式: sh.600519 / sz.000001 / bj.830799 (bj 暂不支持, 返回 None)
    """
    if not symbol or "." not in symbol:
        return None
    code, suffix = symbol.split(".", 1)
    suffix = suffix.upper()
    if suffix == "SH":
        return f"sh.{code}"
    if suffix == "SZ":
        return f"sz.{code}"
    # baostock 暂不支持北交所
    if suffix == "BJ":
        return None
    return None


def _baostock_code_to_symbol(bs_code: str) -> str:
    """baostock code → 工程 symbol。"""
    if "." not in bs_code:
        return bs_code
    code, suffix = bs_code.split(".", 1)
    return f"{code}.{suffix.upper()}"


def availability() -> tuple[bool, str]:
    """loader 启动自检: baostock 包可导入才注册为可切换数据源。不抛异常。"""
    try:
        import baostock  # noqa: F401
    except ImportError:
        return False, "baostock 未安装 (可在下方点击安装按钮自动 pip install)"
    return True, "ok"


# ============================================================
# 企业代理支持: baostock SDK 走原生 socket, 不读 HTTP_PROXY/HTTPS_PROXY
# 企业网络常以 HTTP 代理 (如 proxyhk.huawei.com:8080) 出网, socket 直连被拦截。
# 解决: monkey-patch baostock.util.socketutil 的 connect 路径, 让 socket.connect
# 到代理后发 HTTP CONNECT 隧道请求, 透传到 baostock 服务器。
# 通过环境变量 BAOSTOCK_PROXY=host:port 启用, 不设置则保持原生直连。
# ============================================================
_PROXY_TUNNEL_INSTALLED = False


def _install_proxy_tunnel(proxy_host: str, proxy_port: int) -> None:
    """patch baostock socketutil, 让 connect 走 HTTP CONNECT 隧道。

    baostock SocketUtil.connect() 与 get_default_socket() 都调用
    socket.socket(AF_INET, SOCK_STREAM).connect((IP, PORT))。
    替换为: 先 connect 代理, 发 CONNECT 隧道请求, 200 后该 socket 即透传隧道。
    幂等: 多次调用只装一次。
    """
    global _PROXY_TUNNEL_INSTALLED
    if _PROXY_TUNNEL_INSTALLED:
        return
    try:
        import baostock.util.socketutil as sockutil
    except ImportError:
        return

    _orig_socket = sockutil.socket.socket

    class _TunnelSocket(_orig_socket):
        """connect 到 baostock 服务器时, 改走 HTTP CONNECT 代理隧道。"""

        def connect(self, address):
            host, port = address[0], address[1]
            # 仅对 baostock 服务器 (10030 端口) 走隧道; 其他 connect 保持原行为
            if port != 10030:
                return super().connect(address)
            try:
                super().connect((proxy_host, proxy_port))
                req = (
                    f"CONNECT {host}:{port} HTTP/1.1\r\n"
                    f"Host: {host}:{port}\r\n"
                    f"User-Agent: baostock-client\r\n\r\n"
                )
                self.sendall(req.encode("utf-8"))
                resp = b""
                while b"\r\n\r\n" not in resp and len(resp) < 4096:
                    chunk = self.recv(2048)
                    if not chunk:
                        break
                    resp += chunk
                if b" 200 " not in resp.split(b"\r\n", 1)[0]:
                    raise OSError(
                        f"proxy CONNECT failed: {resp[:200].decode('utf-8', errors='replace')}"
                    )
                return
            except OSError:
                # 隧道失败则回退原生直连 (避免彻底阻断)
                super().connect(address)

    sockutil.socket.socket = _TunnelSocket
    _PROXY_TUNNEL_INSTALLED = True
    logger.info("baostock proxy tunnel installed: %s:%d", proxy_host, proxy_port)


def _maybe_install_proxy_from_env() -> None:
    """从 BAOSTOCK_PROXY=host:port 读取并安装代理隧道。空值跳过。"""
    proxy = os.environ.get("BAOSTOCK_PROXY", "").strip()
    if not proxy:
        return
    if ":" not in proxy:
        logger.warning("BAOSTOCK_PROXY malformed (expect host:port): %s", proxy)
        return
    host, _, port_s = proxy.rpartition(":")
    try:
        port = int(port_s)
    except ValueError:
        logger.warning("BAOSTOCK_PROXY port not int: %s", proxy)
        return
    _install_proxy_tunnel(host, port)


class _BaostockConfig:
    """轻量 config shim, 让 custom loader 的 provider_has_dataset 能识别本 provider。

    对齐 tdx.TdxConfig 接口 (name/display_name/datasets/path/builtin)。
    """

    name = "baostock"
    display_name = "Baostock 证券宝"
    datasets = {"daily": {}, "minute": {}, "adj_factor": {}}
    path = None
    builtin = True


# ===== 引用计数会话管理 =====
# baostock SDK 的连接是进程级全局单连接 (login 写入模块全局)。
# 之前每次查询前 login、查询后 logout, 批量扫描时每只股票一对
# login/logout (stdout 刷屏 "login success!/logout success!")。
# 改为引用计数: 第一个查询触发 login, 并发查询共享会话, 全部完成后
# (引用归零) 才 logout。单次批量扫描全程只产生一对登录/登出日志。
_bs_session_lock = threading.Lock()
_bs_session_refs = 0


def _session_acquire() -> tuple[bool, str]:
    """进入一段 baostock 查询区, 返回 (是否成功, 错误)。

    引用从 0→1 时真正 login; 已有会话则直接复用 (不重复 login)。
    login 失败时不计数, 后续调用会重试。
    """
    global _bs_session_refs
    with _bs_session_lock:
        if _bs_session_refs == 0:
            ok, msg = _do_login()
            if not ok:
                return False, msg
        _bs_session_refs += 1
    return True, ""


def _session_release() -> None:
    """退出一段 baostock 查询区。引用归零时 logout (业务全部完成)。"""
    global _bs_session_refs
    with _bs_session_lock:
        if _bs_session_refs > 0:
            _bs_session_refs -= 1
        if _bs_session_refs == 0:
            try:
                import baostock as bs
                bs.logout()
            except Exception:  # noqa: BLE001
                pass


def _do_login() -> tuple[bool, str]:
    """真正登录 baostock, 返回 (是否成功, user_id 或错误)。"""
    try:
        import baostock as bs
    except ImportError:
        return False, "baostock not installed"

    # baostock SDK 走原生 socket, 不读 HTTP_PROXY/HTTPS_PROXY。
    # 企业网络需经 HTTP 代理出网时, 设置环境变量 BAOSTOCK_PROXY=host:port
    # 触发 monkey-patch, 让 socket.connect 到 baostock:10030 时改走
    # HTTP CONNECT 隧道。未设置则保持原生直连。
    _maybe_install_proxy_from_env()

    lg = bs.login()
    if getattr(lg, "error_code", "0") != "0":
        return False, f"login failed: {getattr(lg, 'error_msg', 'unknown')}"
    return True, getattr(lg, "user_id", "")


class BaostockProvider:
    """Baostock (证券宝) 数据 provider。

    纯 SDK 调用, 无 API Key。免费登录 bs.login()。
    会话采用模块级引用计数 (_session_acquire/_session_release):
    首个查询触发 login, 并发/连续查询共享同一会话, 引用归零才 logout。
    一次批量扫描全程只产生一对 login/logout。
    """

    name = "baostock"
    builtin = True

    def __init__(self):
        self.config = _BaostockConfig()

    def close(self) -> None:
        """无持久资源需清理 (会话由模块级引用计数管理)。"""
        pass

    # ============================================================
    # daily 数据集
    # ============================================================

    def get_daily(
        self,
        symbols: list[str],
        start_time: date | str | None = None,
        end_time: date | str | None = None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[pl.DataFrame], None] | None = None,
    ) -> pl.DataFrame:
        """查询 baostock 日 K (前复权 adjustflag=2)。

        返回 canonical schema: [symbol, asset_type, source, date, open, high, low, close,
        volume, amount, pre_close, change_pct]
        """
        if not symbols:
            return pl.DataFrame()

        start_d = _to_date(start_time)
        end_d = _to_date(end_time)
        start_str = start_d.strftime("%Y-%m-%d") if start_d else "1990-12-19"
        end_str = end_d.strftime("%Y-%m-%d") if end_d else datetime.now().strftime("%Y-%m-%d")

        ok, _ = _session_acquire()
        if not ok:
            logger.warning("baostock login failed, skip daily fetch")
            return pl.DataFrame()

        try:
            frames = []
            for symbol in symbols:
                bs_code = _symbol_to_baostock_code(symbol)
                if bs_code is None:
                    logger.warning("baostock: unsupported symbol %s (BJ or invalid)", symbol)
                    continue
                df = self._query_kline(
                    bs_code=bs_code,
                    start_date=start_str,
                    end_date=end_str,
                    frequency="d",
                    adjustflag="2",
                )
                if df is None or df.is_empty():
                    continue
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                frames.append(df)

            if not frames:
                return pl.DataFrame()

            combined = pl.concat(frames)
            # 调 normalizer 补 pre_close / change_pct / asset_type / source
            from app.data_providers.normalizer import normalize_daily
            result = normalize_daily(combined, source="baostock")
            if asset_type and "asset_type" not in result.columns:
                result = result.with_columns(pl.lit(asset_type).alias("asset_type"))
            if on_chunk_done:
                on_chunk_done(result)
            return result
        finally:
            _session_release()

    def iter_daily(
        self,
        symbols: list[str],
        start_time: date | str | None = None,
        end_time: date | str | None = None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[pl.DataFrame], None] | None = None,
    ) -> Iterator[pl.DataFrame]:
        """有界分批迭代日K, 每个 symbol 一批。"""
        if not symbols:
            return

        start_d = _to_date(start_time)
        end_d = _to_date(end_time)
        start_str = start_d.strftime("%Y-%m-%d") if start_d else "1990-12-19"
        end_str = end_d.strftime("%Y-%m-%d") if end_d else datetime.now().strftime("%Y-%m-%d")

        ok, _ = _session_acquire()
        if not ok:
            return

        try:
            from app.data_providers.normalizer import normalize_daily
            for symbol in symbols:
                bs_code = _symbol_to_baostock_code(symbol)
                if bs_code is None:
                    continue
                df = self._query_kline(
                    bs_code=bs_code,
                    start_date=start_str,
                    end_date=end_str,
                    frequency="d",
                    adjustflag="2",
                )
                if df is None or df.is_empty():
                    continue
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                result = normalize_daily(df, source="baostock")
                if asset_type and "asset_type" not in result.columns:
                    result = result.with_columns(pl.lit(asset_type).alias("asset_type"))
                if on_chunk_done:
                    on_chunk_done(result)
                yield result
        finally:
            _session_release()

    # ============================================================
    # minute 数据集
    # ============================================================

    def get_minute(
        self,
        symbols: list[str],
        start_time: datetime | str | None = None,
        end_time: datetime | str | None = None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[pl.DataFrame], None] | None = None,
        freq: str = "1m",
    ) -> pl.DataFrame:
        """查询 baostock 分钟 K (前复权 adjustflag=2)。

        freq 工程值 (1m/5m/15m/30m/60m) → baostock frequency (5/15/30/60)。
        baostock 不支持 1 分钟历史, 1m 自动降级为 5 分钟。

        返回 canonical schema: [symbol, asset_type, source, datetime, open, high, low, close,
        volume, amount, freq]
        """
        if not symbols:
            return pl.DataFrame()

        bs_freq = _FREQ_MAP.get(freq, "5")
        if bs_freq not in ("5", "15", "30", "60"):
            logger.warning("baostock: unsupported minute freq %s, fallback to 5", freq)
            bs_freq = "5"

        start_dt = _to_datetime(start_time)
        end_dt = _to_datetime(end_time)
        # baostock 分钟数据从 2015-01-01 起
        start_str = start_dt.strftime("%Y-%m-%d") if start_dt else "2015-01-01"
        end_str = end_dt.strftime("%Y-%m-%d") if end_dt else datetime.now().strftime("%Y-%m-%d")

        ok, _ = _session_acquire()
        if not ok:
            logger.warning("baostock login failed, skip minute fetch")
            return pl.DataFrame()

        try:
            frames = []
            for symbol in symbols:
                bs_code = _symbol_to_baostock_code(symbol)
                if bs_code is None:
                    continue
                df = self._query_kline(
                    bs_code=bs_code,
                    start_date=start_str,
                    end_date=end_str,
                    frequency=bs_freq,
                    adjustflag="2",
                )
                if df is None or df.is_empty():
                    continue
                df = df.with_columns([
                    pl.lit(symbol).alias("symbol"),
                    pl.lit(freq).alias("freq"),
                ])
                frames.append(df)

            if not frames:
                return pl.DataFrame()

            combined = pl.concat(frames)
            combined = combined.with_columns([
                pl.lit(asset_type).alias("asset_type"),
                pl.lit("baostock").alias("source"),
            ])
            if on_chunk_done:
                on_chunk_done(combined)
            return combined
        finally:
            _session_release()

    # ============================================================
    # adj_factor 数据集
    # ============================================================

    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: date | str | None = None,
        end_time: date | str | None = None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[pl.DataFrame], None] | None = None,
    ) -> pl.DataFrame:
        """查询 baostock 除权因子。

        返回 canonical schema: [symbol, asset_type, source, trade_date, ex_factor]
        """
        if not symbols:
            return pl.DataFrame()

        start_d = _to_date(start_time)
        end_d = _to_date(end_time)
        start_str = start_d.strftime("%Y-%m-%d") if start_d else "1990-12-19"
        end_str = end_d.strftime("%Y-%m-%d") if end_d else datetime.now().strftime("%Y-%m-%d")

        ok, _ = _session_acquire()
        if not ok:
            logger.warning("baostock login failed, skip adj_factor fetch")
            return pl.DataFrame()

        try:
            import baostock as bs
            frames = []
            for symbol in symbols:
                bs_code = _symbol_to_baostock_code(symbol)
                if bs_code is None:
                    continue
                try:
                    rs = bs.query_adjust_factor(
                        code=bs_code,
                        start_date=start_str,
                        end_date=end_str,
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("baostock query_adjust_factor failed for %s: %s", symbol, e)
                    continue

                rows = []
                while rs.next():
                    row = rs.get_row_data()
                    if not row:
                        continue
                    fmap = {name: idx for idx, name in enumerate(rs.fields)}
                    rows.append({
                        "symbol": symbol,
                        "trade_date": _parse_date_str(row[fmap["date"]]),
                        "ex_factor": _safe_float(row[fmap["foreAdjustFactor"]]),
                    })
                if rows:
                    frames.append(pl.DataFrame(rows))

            if not frames:
                return pl.DataFrame()

            combined = pl.concat(frames)
            combined = combined.with_columns([
                pl.lit(asset_type).alias("asset_type"),
                pl.lit("baostock").alias("source"),
            ])
            if on_chunk_done:
                on_chunk_done(combined)
            return combined
        finally:
            _session_release()

    # ============================================================
    # 内部: K 线查询 + 字段映射
    # ============================================================

    def _query_kline(
        self,
        bs_code: str,
        start_date: str,
        end_date: str,
        frequency: str,
        adjustflag: str,
    ) -> pl.DataFrame | None:
        """调用 baostock query_history_k_data_plus, 返回 polars DataFrame。

        日K返回: date, open, high, low, close, volume(股), amount(元), pre_close
        (baostock 源字段名为 preclose, 归一化为工程契约的 pre_close)
        分钟K返回: date, time, open, high, low, close, volume(股), amount(元)
                   time 格式 HHMMSS (如 93000 = 09:30:00), 需组合 date+time 为 datetime
        """
        try:
            import baostock as bs
        except ImportError:
            return None

        # 日K带 preclose 字段(baostock 官方字段名无下划线); 分钟K不带但带 time 字段。
        # 旧写法传 "pre_close" → baostock [10004012] 日线指标参数传入错误。
        is_daily = frequency in ("d", "w", "m")
        if is_daily:
            fields = "date,open,high,low,close,volume,amount,preclose"
        else:
            fields = "date,time,open,high,low,close,volume,amount"

        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjustflag,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("baostock query_history_k_data_plus failed for %s: %s", bs_code, e)
            return None

        if getattr(rs, "error_code", "0") != "0":
            logger.warning(
                "baostock query error for %s: [%s] %s",
                bs_code, getattr(rs, "error_code", "?"), getattr(rs, "error_msg", "?"),
            )
            return None

        # baostock ResultData API: rs.next() 推进游标, rs.get_row_data() 返回
        # 与 rs.fields 对齐的 list[str]。无 get_field_string 方法。
        rows = []
        while rs.next():
            row = rs.get_row_data()
            if not row:
                continue
            # 字段索引映射 (按 fields 字符串顺序)
            fmap = {name: idx for idx, name in enumerate(rs.fields)}
            if is_daily:
                rows.append({
                    "date": _parse_date_str(row[fmap["date"]]),
                    "open": _safe_float(row[fmap["open"]]),
                    "high": _safe_float(row[fmap["high"]]),
                    "low": _safe_float(row[fmap["low"]]),
                    "close": _safe_float(row[fmap["close"]]),
                    # baostock volume 单位股, 工程契约手 → ÷100
                    "volume": _safe_float(row[fmap["volume"]]) / 100.0,
                    "amount": _safe_float(row[fmap["amount"]]),
                    "pre_close": _safe_float(row[fmap["preclose"]]),
                })
            else:
                date_str = row[fmap["date"]]
                time_str = row[fmap["time"]]
                dt = _combine_date_time(date_str, time_str)
                if dt is None:
                    continue
                rows.append({
                    "datetime": dt,
                    "open": _safe_float(row[fmap["open"]]),
                    "high": _safe_float(row[fmap["high"]]),
                    "low": _safe_float(row[fmap["low"]]),
                    "close": _safe_float(row[fmap["close"]]),
                    "volume": _safe_float(row[fmap["volume"]]) / 100.0,
                    "amount": _safe_float(row[fmap["amount"]]),
                })

        if not rows:
            return None

        if is_daily:
            return pl.DataFrame(rows, schema={
                "date": pl.Date,
                "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                "close": pl.Float64, "volume": pl.Float64, "amount": pl.Float64,
                "pre_close": pl.Float64,
            })
        else:
            return pl.DataFrame(rows, schema={
                "datetime": pl.Datetime,
                "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                "close": pl.Float64, "volume": pl.Float64, "amount": pl.Float64,
            })


# ============================================================
# 工具函数
# ============================================================

def _to_date(val: date | str | datetime | None) -> date | None:
    """归一化为 date。"""
    if val is None:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return datetime.strptime(val[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _to_datetime(val: datetime | str | date | None) -> datetime | None:
    """归一化为 datetime。"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, str):
        try:
            return datetime.strptime(val[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                return datetime.strptime(val[:10], "%Y-%m-%d")
            except ValueError:
                return None
    return None


def _parse_date_str(s: str) -> date | None:
    """baostock date 字符串 'YYYY-MM-DD' → date。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _safe_float(s: str) -> float:
    """baostock 字段字符串 → float, 空值返回 0.0。"""
    if not s or s == "":
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _combine_date_time(date_str: str, time_str: str) -> datetime | None:
    """baostock 分钟数据 date + time 组合为 datetime (北京墙钟 naive)。

    date: 'YYYY-MM-DD'
    time: 'YYYYMMDDHHMMSSmmm' 17 位字符串 (如 '20241101100000000' = 2024-11-01 10:00:00.000)
          含日期+时间+毫秒, 时间部分取 HHMMSS。
    """
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    # baostock 分钟 time 字段为 17 位 YYYYMMDDHHMMSSmmm
    t = time_str or ""
    if len(t) >= 14:
        # 取 HHMMSS 部分 (位置 8-14)
        try:
            hh = int(t[8:10])
            mm = int(t[10:12])
            ss = int(t[12:14])
            return d.replace(hour=hh, minute=mm, second=ss)
        except (ValueError, IndexError):
            return d
    # 兼容旧格式 HHMMSS (6 位)
    t6 = t.zfill(6)
    if len(t6) == 6:
        try:
            hh = int(t6[:2])
            mm = int(t6[2:4])
            ss = int(t6[4:6])
            return d.replace(hour=hh, minute=mm, second=ss)
        except (ValueError, IndexError):
            return d
    return d
