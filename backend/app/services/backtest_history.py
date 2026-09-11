"""回测历史记录存储 — 每次运行回测后自动保存完整结果+参数。

存储模式: 每条记录单独一个 JSON 文件 + 一个索引文件存元信息列表。
- data/backtest_history/records.json  — 索引(元信息列表, 轻量)
- data/backtest_history/{record_id}.json — 完整记录(config + labels + stats + result)

保留最近 100 条, 超出自动删除最旧记录及其文件。

与 CandidateStore 同模式(文件存储 + 线程锁 + 原子写入), 但:
- CandidateStore 存的是 config + metrics 摘要(无净值/交易);
- 本服务存的是完整回测结果(含 equity_curve/trades/per_symbol_stats), 供分析页回看。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_RECORDS = 100
MAX_NAME_LENGTH = 120
HISTORY_DIR = "backtest_history"
INDEX_FILE = "records.json"

_lock = threading.RLock()


def _history_dir(data_dir: Path) -> Path:
    return Path(data_dir) / HISTORY_DIR


def _index_path(data_dir: Path) -> Path:
    return _history_dir(data_dir) / INDEX_FILE


def _record_path(data_dir: Path, record_id: str) -> Path:
    return _history_dir(data_dir) / f"{record_id}.json"


class BacktestHistoryStore:
    """回测历史记录文件存储。"""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)

    # ───────────────────────── 公开方法 ─────────────────────────

    def list(self) -> list[dict[str, Any]]:
        """返回记录元信息列表(按 created_at 降序), 不含完整 result。"""
        with _lock:
            return self._load_index()

    def get(self, record_id: str) -> dict[str, Any] | None:
        """返回某条记录的完整数据(含 result)。"""
        with _lock:
            p = _record_path(self.data_dir, record_id)
            if not p.exists():
                return None
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("backtest_history: failed to read %s: %s", record_id, e)
                return None

    def save(
        self,
        *,
        result: dict[str, Any],
        labels: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """保存一条回测记录, 返回元信息。自动保留最近 MAX_RECORDS 条。

        - result: 完整的 StrategyBacktestResult (dict 化)
        - labels: 参数中文名称映射 (param_labels/signal_labels/factor_labels/strategy_name)
        - name: 自定义名称, 默认用时间戳
        """
        with _lock:
            now = datetime.now()
            record_id = f"bt_{now.strftime('%Y%m%d_%H%M%S')}_{now.microsecond // 1000:03d}"
            display_name = (name or now.strftime("%Y-%m-%d %H:%M:%S")).strip()[:MAX_NAME_LENGTH]

            config = result.get("config", {})
            stats = result.get("stats", {})
            strategy_info = result.get("strategy_info", {})
            strategy_name = labels.get("strategy_name") if labels else None
            if not strategy_name:
                strategy_name = strategy_info.get("name", config.get("strategy_id", ""))

            # 元信息(索引条目): 轻量, 用于列表展示
            meta = {
                "id": record_id,
                "name": display_name,
                "created_at": now.isoformat(),
                "strategy_name": strategy_name,
                "strategy_id": config.get("strategy_id", ""),
                "start": config.get("start"),
                "end": config.get("end"),
                "total_return": stats.get("total_return"),
                "max_drawdown": stats.get("max_drawdown"),
                "sharpe": stats.get("sharpe"),
                "n_trades": stats.get("n_trades"),
                "win_rate": stats.get("win_rate"),
                "elapsed_ms": result.get("elapsed_ms"),
            }

            # 完整记录(单独文件): 含全部数据供分析页回看
            full_record = {
                "id": record_id,
                "name": display_name,
                "created_at": now.isoformat(),
                "config": config,
                "labels": labels or {},
                "stats": stats,
                "result": result,
            }

            # 写完整记录文件
            self._write_record(record_id, full_record)

            # 更新索引
            index = self._load_index()
            index.insert(0, meta)
            # 超容量: 删除最旧记录
            if len(index) > MAX_RECORDS:
                removed = index[MAX_RECORDS:]
                index = index[:MAX_RECORDS]
                for old in removed:
                    self._delete_record_file(old["id"])

            self._write_index(index)
            return meta

    def rename(self, record_id: str, name: str) -> dict[str, Any] | None:
        """重命名记录, 返回更新后的元信息。"""
        clean = name.strip()[:MAX_NAME_LENGTH]
        if not clean:
            raise ValueError("名称不能为空")
        with _lock:
            index = self._load_index()
            for item in index:
                if item["id"] == record_id:
                    item["name"] = clean
                    self._write_index(index)
                    # 同步更新完整记录文件中的 name
                    full = self.get(record_id)
                    if full:
                        full["name"] = clean
                        self._write_record(record_id, full)
                    return item
            return None

    def delete(self, record_id: str) -> bool:
        """删除记录, 返回是否删除成功。"""
        with _lock:
            index = self._load_index()
            remaining = [item for item in index if item["id"] != record_id]
            if len(remaining) == len(index):
                return False
            self._write_index(remaining)
            self._delete_record_file(record_id)
            return True

    # ───────────────────────── 内部方法 ─────────────────────────

    def _load_index(self) -> list[dict[str, Any]]:
        p = _index_path(self.data_dir)
        if not p.exists():
            return []
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [item for item in raw if isinstance(item, dict) and "id" in item]
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("backtest_history: index corrupted: %s", e)
            return []

    def _write_index(self, items: list[dict[str, Any]]) -> None:
        d = _history_dir(self.data_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = _index_path(self.data_dir)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(items, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(tmp, p)

    def _write_record(self, record_id: str, record: dict[str, Any]) -> None:
        d = _history_dir(self.data_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = _record_path(self.data_dir, record_id)
        tmp = p.with_suffix(".json.tmp")
        # allow_nan=True: 回测结果中可能有 NaN (如 stats 中某些指标缺失)
        tmp.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=True, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, p)

    def _delete_record_file(self, record_id: str) -> None:
        p = _record_path(self.data_dir, record_id)
        p.unlink(missing_ok=True)
