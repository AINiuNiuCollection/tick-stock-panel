"""TdxProvider 契约与二进制解析测试。

不依赖真实通达信安装: 构造临时 .day/.lc1/.lc5/gbbq 二进制文件, 验证:
  - 字段映射 (symbol 从文件名推导, date/datetime 编码)
  - 单位口径 (CONTRIBUTING §3.1: 价格 ×100→元, volume 股→手)
  - datetime 编码自动检测 (方案 A mootdx vs 方案 B)
  - gbbq 记录长度自动检测 (32 vs 24 字节)
  - ex_factor 单事件比值计算
  - 能力声明 (未声明数据集回退 tickflow)
  - availability / probe_config
"""
from __future__ import annotations

import struct
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest

# Mock tickflow SDK to avoid ModuleNotFoundError during import chain
# (data_providers/__init__ → registry → tickflow_provider → tickflow.client → tickflow)
for _mod in ("tickflow", "tickflow.client"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from app.plugins.tdx import reader
from app.plugins.tdx.provider import TdxProvider, availability, probe_config


# ============================================================
# 辅助: 构造二进制文件
# ============================================================

def _make_day_record(date_int: int, o: int, h: int, l: int, c: int, amount: float, vol: int) -> bytes:
    """构造一条 .day 记录 (32 字节)。价格单位为分(×100), volume 单位为股。"""
    return struct.pack("<iiiiifii", date_int, o, h, l, c, amount, vol, 0)


def _make_lc_record(date_uint16: int, time_uint16: int, o: float, h: float, l: float, c: float, amount: float, vol: int) -> bytes:
    """构造一条 .lc1/.lc5 记录 (32 字节)。

    date_uint16: 方案 A 编码 (year-2004)×2048 + month×100 + day
    time_uint16: HHMM 编码 (如 931 = 09:31)
    价格为 float32 元, volume 单位为股。
    """
    return struct.pack("<HHfffffii", date_uint16, time_uint16, o, h, l, c, amount, vol, 0)


def _make_gbbq_record_32(market: int, code: str, date_int: int, sz: float, fh: float, pg: float, pgj: float) -> bytes:
    """构造一条 gbbq 记录 (32 字节版)。"""
    return struct.pack("<H6sIfffff", market, code.encode("ascii"), date_int, sz, fh, pg, pgj, 0.0)


def _make_gbbq_record_28(market: int, code: str, date_int: int, sz: float, fh: float, pg: float, pgj: float) -> bytes:
    """构造一条 gbbq 记录 (28 字节版, 无 reserved)。"""
    return struct.pack("<H6sIffff", market, code.encode("ascii"), date_int, sz, fh, pg, pgj)


def _encode_lc_date_a(year: int, month: int, day: int) -> int:
    """方案 A 编码: (year - 2004) × 2048 + month × 100 + day。"""
    return (year - 2004) * 2048 + month * 100 + day


# ============================================================
# .day 文件解析测试
# ============================================================

class TestReadDayFile:
    def test_basic_parsing(self, tmp_path):
        """验证 .day 文件基本解析: 价格 ÷100, volume ÷100 股→手。"""
        day_file = tmp_path / "sh600519.day"
        day_file.write_bytes(
            _make_day_record(20260101, 168500, 170000, 167000, 169500, 1.2e9, 500000)
            + _make_day_record(20260102, 169500, 171000, 169000, 170500, 1.5e9, 600000)
        )
        df = reader.read_day_file(day_file, "600519.SH")
        assert len(df) == 2
        assert df["symbol"].to_list() == ["600519.SH", "600519.SH"]
        assert df["date"].to_list() == [date(2026, 1, 1), date(2026, 1, 2)]
        # 价格 ÷100: 168500 → 1685.00
        assert df["open"].to_list()[0] == 1685.0
        assert df["close"].to_list()[0] == 1695.0
        # volume ÷100: 500000 股 → 5000 手
        assert df["volume"].to_list()[0] == 5000.0

    def test_empty_file(self, tmp_path):
        """空文件返回空 DataFrame。"""
        day_file = tmp_path / "sh600519.day"
        day_file.write_bytes(b"")
        df = reader.read_day_file(day_file, "600519.SH")
        assert df.is_empty()

    def test_zero_padding_skipped(self, tmp_path):
        """全零记录(文件尾部 padding)被跳过。"""
        day_file = tmp_path / "sh600519.day"
        day_file.write_bytes(
            _make_day_record(20260101, 168500, 170000, 167000, 169500, 1.2e9, 500000)
            + b"\x00" * 32  # 全零 padding
        )
        df = reader.read_day_file(day_file, "600519.SH")
        assert len(df) == 1


# ============================================================
# .lc1/.lc5 文件解析测试
# ============================================================

class TestReadLcFile:
    def test_datetime_encoding_a(self, tmp_path):
        """方案 A (mootdx) date 编码 + HHMM time 编码。"""
        lc_file = tmp_path / "sh600519.lc1"
        dt_a = _encode_lc_date_a(2026, 1, 5)  # 2026-01-05
        lc_file.write_bytes(
            _make_lc_record(dt_a, 931, 1685.0, 1688.0, 1684.0, 1687.0, 5e7, 10000)
            + _make_lc_record(dt_a, 932, 1687.0, 1690.0, 1686.0, 1689.0, 6e7, 11000)
        )
        df = reader.read_lc_file(lc_file, "600519.SH", "1m")
        assert len(df) == 2
        # 第一条为 09:31
        assert df["datetime"].to_list()[0] == datetime(2026, 1, 5, 9, 31)
        # 第二条为 09:32
        assert df["datetime"].to_list()[1] == datetime(2026, 1, 5, 9, 32)
        # volume ÷100: 10000 股 → 100 手
        assert df["volume"].to_list()[0] == 100.0
        assert df["freq"].to_list()[0] == "1m"

    def test_afternoon_session(self, tmp_path):
        """下午时段时间解码: 13:01。"""
        lc_file = tmp_path / "sh600519.lc1"
        dt_a = _encode_lc_date_a(2026, 1, 5)
        lc_file.write_bytes(
            _make_lc_record(dt_a, 1301, 1685.0, 1688.0, 1684.0, 1687.0, 5e7, 10000)
        )
        df = reader.read_lc_file(lc_file, "600519.SH", "1m")
        assert len(df) == 1
        assert df["datetime"].to_list()[0] == datetime(2026, 1, 5, 13, 1)

    def test_lc5_freq(self, tmp_path):
        """5 分钟线 freq 标记正确。"""
        lc_file = tmp_path / "sh600519.lc5"
        dt_a = _encode_lc_date_a(2026, 1, 5)
        lc_file.write_bytes(
            _make_lc_record(dt_a, 935, 1685.0, 1688.0, 1684.0, 1687.0, 5e7, 10000)
        )
        df = reader.read_lc_file(lc_file, "600519.SH", "5m")
        assert df["freq"].to_list()[0] == "5m"
        # 5分钟线第一条为 09:35
        assert df["datetime"].to_list()[0] == datetime(2026, 1, 5, 9, 35)


# ============================================================
# gbbq 文件解析测试
# ============================================================

class TestReadGbbqFile:
    def test_32_byte_records(self, tmp_path):
        """32 字节版 gbbq 解析: symbol 从 market+code 推导。"""
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(
            _make_gbbq_record_32(1, "600519", 20260615, 0.0, 25.91, 0.0, 0.0)  # 茅台分红
            + _make_gbbq_record_32(0, "000001", 20260620, 0.1, 0.0, 0.0, 0.0)  # 平安送股
        )
        df = reader.read_gbbq_file(gbbq)
        assert len(df) == 2
        assert df["symbol"].to_list() == ["600519.SH", "000001.SZ"]
        assert df["trade_date"].to_list() == [date(2026, 6, 15), date(2026, 6, 20)]
        assert abs(df["fenhong"].to_list()[0] - 25.91) < 0.001
        assert abs(df["songzhuang"].to_list()[1] - 0.1) < 0.001

    def test_28_byte_records(self, tmp_path):
        """28 字节版 gbbq 自动检测 (无 reserved 字段)。"""
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(
            _make_gbbq_record_28(1, "600519", 20260615, 0.0, 25.91, 0.0, 0.0)
        )
        df = reader.read_gbbq_file(gbbq)
        assert len(df) == 1
        assert df["symbol"].to_list()[0] == "600519.SH"

    def test_bj_market(self, tmp_path):
        """北交所 market=2 → .BJ 后缀。"""
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(
            _make_gbbq_record_32(2, "830799", 20260615, 0.0, 0.5, 0.0, 0.0)
        )
        df = reader.read_gbbq_file(gbbq)
        assert df["symbol"].to_list()[0] == "830799.BJ"

    def test_empty_file(self, tmp_path):
        """空文件返回空 DataFrame。"""
        gbbq = tmp_path / "gbbq"
        gbbq.write_bytes(b"")
        df = reader.read_gbbq_file(gbbq)
        assert df.is_empty()


# ============================================================
# ex_factor 计算测试
# ============================================================

class TestComputeExFactor:
    def test_pure_dividend(self):
        """纯分红: ratio = (C - D) / C。"""
        events = pl.DataFrame({
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 6, 16)],  # 除权日
            "songzhuang": [0.0],
            "fenhong": [25.91],
            "peigu": [0.0],
            "peigujia": [0.0],
        })
        daily_close = pl.DataFrame({
            "symbol": ["600519.SH", "600519.SH"],
            "date": [date(2026, 6, 15), date(2026, 6, 16)],
            "close": [1700.0, 1674.09],
        })
        result = reader.compute_ex_factor(events, daily_close)
        assert len(result) == 1
        # ratio = (1700 - 25.91) / (1700 × 1) = 1674.09 / 1700 ≈ 0.98476
        ex = result["ex_factor"].to_list()[0]
        assert abs(ex - (1700 - 25.91) / 1700) < 1e-6

    def test_pure_bonus_shares(self):
        """纯送股: ratio = C / (C × (1 + S)) = 1 / (1 + S)。"""
        events = pl.DataFrame({
            "symbol": ["000001.SZ"],
            "trade_date": [date(2026, 6, 20)],
            "songzhuang": [0.1],
            "fenhong": [0.0],
            "peigu": [0.0],
            "peigujia": [0.0],
        })
        daily_close = pl.DataFrame({
            "symbol": ["000001.SZ"],
            "date": [date(2026, 6, 19)],
            "close": [10.0],
        })
        result = reader.compute_ex_factor(events, daily_close)
        assert len(result) == 1
        # ratio = 10 / (10 × 1.1) = 1/1.1 ≈ 0.90909
        ex = result["ex_factor"].to_list()[0]
        assert abs(ex - 1.0 / 1.1) < 1e-6

    def test_no_prev_close_skipped(self):
        """无前收盘的事件被跳过。"""
        events = pl.DataFrame({
            "symbol": ["600519.SH"],
            "trade_date": [date(2026, 6, 16)],
            "songzhuang": [0.0],
            "fenhong": [25.91],
            "peigu": [0.0],
            "peigujia": [0.0],
        })
        daily_close = pl.DataFrame({
            "symbol": ["600519.SH"],
            "date": [date(2026, 6, 17)],  # 只有除权日之后的数据
            "close": [1674.09],
        })
        result = reader.compute_ex_factor(events, daily_close)
        assert result.is_empty()


# ============================================================
# symbol ↔ 文件路径转换测试
# ============================================================

class TestSymbolFilePath:
    def test_symbol_to_day_path(self, tmp_path):
        """symbol → .day 文件路径。"""
        p = reader.symbol_to_file_path(tmp_path, "600519.SH", ".day")
        assert p == tmp_path / "sh" / "lday" / "sh600519.day"

    def test_symbol_to_lc1_path(self, tmp_path):
        """symbol → .lc1 文件路径。"""
        p = reader.symbol_to_file_path(tmp_path, "000001.SZ", ".lc1")
        assert p == tmp_path / "sz" / "minline" / "sz000001.lc1"

    def test_symbol_to_lc5_path(self, tmp_path):
        """symbol → .lc5 文件路径。"""
        p = reader.symbol_to_file_path(tmp_path, "830799.BJ", ".lc5")
        assert p == tmp_path / "bj" / "fzline" / "bj830799.lc5"

    def test_file_path_to_symbol(self):
        """文件路径 → symbol。"""
        p = Path("/some/vipdoc/sh/lday/sh600519.day")
        assert reader.file_path_to_symbol(p) == "600519.SH"

    def test_file_path_to_symbol_sz(self):
        p = Path("/some/vipdoc/sz/minline/sz000001.lc1")
        assert reader.file_path_to_symbol(p) == "000001.SZ"


# ============================================================
# Provider 能力声明与 availability 测试
# ============================================================

class TestProviderBasics:
    def test_datasets_declaration(self):
        """Provider 声明 daily / minute / adj_factor 三个数据集。"""
        provider = TdxProvider()
        assert "daily" in provider.config.datasets
        assert "minute" in provider.config.datasets
        assert "adj_factor" in provider.config.datasets
        # 未声明 realtime / depth5 / financial
        assert "realtime" not in provider.config.datasets
        assert "depth5" not in provider.config.datasets
        assert "financial" not in provider.config.datasets

    def test_name(self):
        """Provider name 为 tdx。"""
        provider = TdxProvider()
        assert provider.name == "tdx"
        assert provider.builtin is True

    def test_probe_config_empty(self):
        """probe_config: 空 vipdoc_dir 返回 False。"""
        ok, msg = probe_config({})
        assert not ok
        assert "不能为空" in msg

    def test_probe_config_nonexistent(self):
        """probe_config: 不存在的路径返回 False。"""
        ok, msg = probe_config({"vipdoc_dir": "/nonexistent/path/xyz"})
        assert not ok

    def test_probe_config_valid(self, tmp_path):
        """probe_config: 有效路径(含 sh/lday)返回 True。"""
        vipdoc = tmp_path / "vipdoc"
        (vipdoc / "sh" / "lday").mkdir(parents=True)
        ok, msg = probe_config({"vipdoc_dir": str(vipdoc)})
        assert ok


# ============================================================
# Provider get_daily 端到端测试
# ============================================================

class TestProviderGetDaily:
    def test_get_daily_from_file(self, tmp_path, monkeypatch):
        """端到端: 构造 vipdoc 目录 + .day 文件, get_daily 返回正确数据。"""
        vipdoc = tmp_path / "vipdoc"
        (vipdoc / "sh" / "lday").mkdir(parents=True)
        day_file = vipdoc / "sh" / "lday" / "sh600519.day"
        day_file.write_bytes(
            _make_day_record(20260101, 168500, 170000, 167000, 169500, 1.2e9, 500000)
            + _make_day_record(20260102, 169500, 171000, 169000, 170500, 1.5e9, 600000)
        )

        # mock 配置
        from app.plugins.tdx import config as tdx_config
        monkeypatch.setattr(tdx_config, "get_plugin_config", lambda: {"vipdoc_dir": str(vipdoc), "gbbq_path": ""})
        monkeypatch.setattr("app.plugins.tdx.provider.get_vipdoc_dir", lambda: vipdoc)

        provider = TdxProvider()
        df = provider.get_daily(["600519.SH"], start_time=date(2026, 1, 1), end_time=date(2026, 1, 2))
        assert len(df) == 2
        assert "symbol" in df.columns
        assert "date" in df.columns
        assert "open" in df.columns
        assert "close" in df.columns
        assert "volume" in df.columns
        # volume 已转手
        assert df["volume"].to_list()[0] == 5000.0

    def test_get_daily_missing_symbol(self, tmp_path, monkeypatch):
        """请求不存在的 symbol 返回空 DataFrame, 不报错。"""
        vipdoc = tmp_path / "vipdoc"
        (vipdoc / "sh" / "lday").mkdir(parents=True)

        monkeypatch.setattr("app.plugins.tdx.provider.get_vipdoc_dir", lambda: vipdoc)

        provider = TdxProvider()
        df = provider.get_daily(["999999.SH"])
        assert df.is_empty()

    def test_get_daily_no_config(self, monkeypatch):
        """未配置 vipdoc 目录返回空 DataFrame。"""
        monkeypatch.setattr("app.plugins.tdx.provider.get_vipdoc_dir", lambda: None)
        provider = TdxProvider()
        df = provider.get_daily(["600519.SH"])
        assert df.is_empty()
