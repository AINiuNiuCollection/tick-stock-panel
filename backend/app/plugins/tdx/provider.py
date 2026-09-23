"""通达信本地数据内置数据源 provider。

方法签名对齐 custom.GenericHTTPProvider(service 分流点按这套签名调用),
注入 custom loader 注册表后, 各 service 无需改动即可路由到本 provider。

实现数据集:
  - daily       A 股日K, 读取 .day 二进制文件(不复权原始价)
  - minute      A 股分钟K, 读取 .lc1(1分钟) / .lc5(5分钟)
  - adj_factor  除权因子, 读取 gbbq 文件 + 日K前收盘推导单事件比值

未声明 realtime / depth5 / financial → provider_has_dataset 为 False, 自动回退 tickflow。

单位与口径 (CONTRIBUTING §3.1, 不可凭字段名推断):
  - .day 价格为 int32 ×100 (分), 此处 ÷100 转浮点元
  - .day/.lc1/.lc5 volume 为股, 本项目日K/分钟契约均为手 → 统一 ÷100
  - amount 单位元, 直接透传
  - 日K取不复权原始价: 前复权由 indicators.pipeline 用本地 adj_factor 计算
  - ex_factor 为单事件比值(非累积), 累积链由 pipeline._apply_adj_factor 构建
  - 分钟 datetime 为北京墙钟 naive (通达信已是北京墙钟, 直接组合)
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import date, datetime
from pathlib import Path

import polars as pl

from app.plugins.tdx import reader
from app.plugins.tdx.config import TdxConfig, get_gbbq_path, get_plugin_config, get_vipdoc_dir

logger = logging.getLogger(__name__)

# 只声明真实提供的数据集; 其余数据集 provider_has_dataset 返回 False → 回退 tickflow
_DATASETS = ("daily", "minute", "adj_factor")


def availability() -> tuple[bool, str]:
    """loader 启动自检: vipdoc 目录已配置且存在才注册为可切换数据源。不抛异常。"""
    vipdoc = get_vipdoc_dir()
    if vipdoc is None:
        return False, "未配置 vipdoc 目录或目录不存在(可在下方输入框配置通达信安装路径下的 vipdoc 文件夹)"
    # 检查至少有一个交易所子目录
    has_subdir = any((vipdoc / ex / "lday").exists() for ex in ("sh", "sz", "bj"))
    if not has_subdir:
        return False, f"vipdoc 目录下未找到 sh/lday 等子目录, 请确认路径正确: {vipdoc}"
    return True, "ok"


def probe_config(config: dict) -> tuple[bool, str]:
    """设置页保存配置时先探后存: 验证路径有效性。不落盘。"""
    vipdoc = (config.get("vipdoc_dir") or "").strip()
    if not vipdoc:
        return False, "vipdoc 目录不能为空"
    p = Path(vipdoc)
    if not p.exists():
        return False, f"目录不存在: {vipdoc}"
    if not p.is_dir():
        return False, f"路径不是目录: {vipdoc}"
    has_subdir = any((p / ex / "lday").exists() for ex in ("sh", "sz", "bj"))
    if not has_subdir:
        return False, f"目录下未找到 sh/lday 等子目录, 请确认是 vipdoc 目录: {vipdoc}"
    return True, "ok"


class TdxProvider:
    """通达信本地数据 provider。

    纯文件读取, 无网络请求, 无 API Key。配置通过 preferences.json 的 plugin_config 存储。
    """

    name = "tdx"
    builtin = True

    def __init__(self):
        self.config = TdxConfig()

    def close(self) -> None:
        """无资源需清理。"""
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
        """读取 .day 文件 → 日K DataFrame。

        返回 canonical schema: [symbol, asset_type, source, date, open, high, low, close,
        volume, amount, pre_close, change_pct]
        """
        vipdoc = get_vipdoc_dir()
        if vipdoc is None:
            return pl.DataFrame()

        start_d = _to_date(start_time)
        end_d = _to_date(end_time)

        frames = []
        for symbol in symbols:
            day_path = reader.symbol_to_file_path(vipdoc, symbol, ".day")
            if day_path is None or not day_path.exists():
                continue
            try:
                df = reader.read_day_file(day_path, symbol)
            except Exception as e:
                logger.warning("读取 %s 失败: %s", day_path, e)
                continue
            if df.is_empty():
                continue
            if start_d is not None:
                df = df.filter(pl.col("date") >= start_d)
            if end_d is not None:
                df = df.filter(pl.col("date") <= end_d)
            if not df.is_empty():
                frames.append(df)

        if not frames:
            return pl.DataFrame()

        combined = pl.concat(frames)
        # 调 normalizer 补 pre_close / change_pct / asset_type / source
        from app.data_providers.normalizer import normalize_daily
        result = normalize_daily(combined, source="tdx")
        if asset_type and "asset_type" not in result.columns:
            result = result.with_columns(pl.lit(asset_type).alias("asset_type"))
        if on_chunk_done:
            on_chunk_done(result)
        return result

    def iter_daily(
        self,
        symbols: list[str],
        start_time: date | str | None = None,
        end_time: date | str | None = None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[pl.DataFrame], None] | None = None,
    ) -> Iterator[pl.DataFrame]:
        """有界分批迭代日K, 每个 symbol 一批。"""
        vipdoc = get_vipdoc_dir()
        if vipdoc is None:
            return

        start_d = _to_date(start_time)
        end_d = _to_date(end_time)

        for symbol in symbols:
            day_path = reader.symbol_to_file_path(vipdoc, symbol, ".day")
            if day_path is None or not day_path.exists():
                continue
            try:
                df = reader.read_day_file(day_path, symbol)
            except Exception as e:
                logger.warning("读取 %s 失败: %s", day_path, e)
                continue
            if df.is_empty():
                continue
            if start_d is not None:
                df = df.filter(pl.col("date") >= start_d)
            if end_d is not None:
                df = df.filter(pl.col("date") <= end_d)
            if df.is_empty():
                continue
            from app.data_providers.normalizer import normalize_daily
            result = normalize_daily(df, source="tdx")
            if asset_type and "asset_type" not in result.columns:
                result = result.with_columns(pl.lit(asset_type).alias("asset_type"))
            if on_chunk_done:
                on_chunk_done(result)
            yield result

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
        """读取 .lc1/.lc5 文件 → 分钟K DataFrame。

        返回 canonical schema: [symbol, asset_type, source, datetime, open, high, low, close,
        volume, amount, freq]
        """
        vipdoc = get_vipdoc_dir()
        if vipdoc is None:
            return pl.DataFrame()

        ext = ".lc1" if freq in ("1m", "1min") else ".lc5"
        start_dt = _to_datetime(start_time)
        end_dt = _to_datetime(end_time)

        frames = []
        for symbol in symbols:
            lc_path = reader.symbol_to_file_path(vipdoc, symbol, ext)
            if lc_path is None or not lc_path.exists():
                continue
            try:
                df = reader.read_lc_file(lc_path, symbol, freq)
            except Exception as e:
                logger.warning("读取 %s 失败: %s", lc_path, e)
                continue
            if df.is_empty():
                continue
            if start_dt is not None:
                df = df.filter(pl.col("datetime") >= start_dt)
            if end_dt is not None:
                df = df.filter(pl.col("datetime") <= end_dt)
            if not df.is_empty():
                frames.append(df)

        if not frames:
            return pl.DataFrame()

        combined = pl.concat(frames)
        # 补 asset_type / source 列
        combined = combined.with_columns([
            pl.lit(asset_type).alias("asset_type"),
            pl.lit("tdx").alias("source"),
        ])
        if on_chunk_done:
            on_chunk_done(combined)
        return combined

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
        """读取 gbbq + 日K前收盘 → 单事件比值 ex_factor。

        返回 canonical schema: [symbol, asset_type, source, trade_date, ex_factor]
        """
        vipdoc = get_vipdoc_dir()
        if vipdoc is None:
            return pl.DataFrame()

        gbbq_path = get_gbbq_path(vipdoc)
        if gbbq_path is None or not gbbq_path.exists():
            logger.warning("gbbq 文件不存在, 无法计算除权因子")
            return pl.DataFrame()

        try:
            events = reader.read_gbbq_file(gbbq_path)
        except Exception as e:
            logger.warning("读取 gbbq 失败: %s", e)
            return pl.DataFrame()

        if events.is_empty():
            return pl.DataFrame()

        # 过滤目标 symbols
        if symbols:
            symbol_set = set(symbols)
            events = events.filter(pl.col("symbol").is_in(list(symbol_set)))

        # 过滤日期范围
        start_d = _to_date(start_time)
        end_d = _to_date(end_time)
        if start_d is not None:
            events = events.filter(pl.col("trade_date") >= start_d)
        if end_d is not None:
            events = events.filter(pl.col("trade_date") <= end_d)

        if events.is_empty():
            return pl.DataFrame()

        # 读取相关 symbol 的日K前收盘
        # 为所有涉及到的 symbol 读取 .day 文件
        involved_symbols = events.select("symbol").unique().to_series().to_list()
        daily_frames = []
        for symbol in involved_symbols:
            day_path = reader.symbol_to_file_path(vipdoc, symbol, ".day")
            if day_path is None or not day_path.exists():
                continue
            try:
                df = reader.read_day_file(day_path, symbol)
                daily_frames.append(df)
            except Exception as e:
                logger.warning("读取 %s 失败: %s", day_path, e)
                continue

        if not daily_frames:
            logger.warning("无法读取日K文件, 无法计算除权因子")
            return pl.DataFrame()

        daily_close = pl.concat(daily_frames).select(["symbol", "date", "close"])

        # 计算单事件比值
        ex_factor_df = reader.compute_ex_factor(events, daily_close)

        if ex_factor_df.is_empty():
            return pl.DataFrame()

        # 调 normalizer 补 asset_type / source
        from app.data_providers.normalizer import normalize_adj_factors
        result = normalize_adj_factors(ex_factor_df, source="tdx")
        if asset_type and "asset_type" not in result.columns:
            result = result.with_columns(pl.lit(asset_type).alias("asset_type"))
        if on_chunk_done:
            on_chunk_done(result)
        return result

    # ============================================================
    # 可选: test_dataset (设置页"试拉"按钮)
    # ============================================================

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        """设置页"试拉"按钮: 尝试读取少量数据验证可用性。"""
        vipdoc = get_vipdoc_dir()
        if vipdoc is None:
            return {"ok": False, "error": "未配置 vipdoc 目录"}

        test_symbols = symbols or ["600519.SH", "000001.SZ"]
        try:
            if dataset == "daily":
                df = self.get_daily(test_symbols, asset_type="stock")
                return {
                    "ok": True,
                    "rows": len(df),
                    "columns": df.columns,
                    "sample": df.head(3).to_dicts() if not df.is_empty() else [],
                }
            elif dataset == "minute":
                df = self.get_minute(test_symbols, asset_type="stock", freq="1m")
                return {
                    "ok": True,
                    "rows": len(df),
                    "columns": df.columns,
                    "sample": df.head(3).to_dicts() if not df.is_empty() else [],
                }
            elif dataset == "adj_factor":
                df = self.get_adj_factors(test_symbols, asset_type="stock")
                return {
                    "ok": True,
                    "rows": len(df),
                    "columns": df.columns,
                    "sample": df.head(3).to_dicts() if not df.is_empty() else [],
                }
            else:
                return {"ok": False, "error": f"不支持的数据集: {dataset}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ============================================================
# 辅助函数
# ============================================================

def _to_date(value) -> date | None:
    """将多种日期输入归一为 date | None。"""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _to_datetime(value) -> datetime | None:
    """将多种 datetime 输入归一为 datetime | None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
