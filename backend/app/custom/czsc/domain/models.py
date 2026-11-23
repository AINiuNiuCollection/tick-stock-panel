"""缠论领域模型 — 与 czsc 原生对象解耦的稳定数据结构。

设计:
    - 所有字段在 adapter 层一次性快照, 后续 domain/application 不再触碰原生对象。
    - `raw_mark` / `raw_direction` 保留 czsc 原始字符串, 供 API 输出兼容旧前端;
      `mark` / `direction` 是归一化值 ("top"/"bottom", "up"/"down") 供算法使用。
    - 笔的 `range_sdt/range_edt` 是"按分型包含"的区间 (fx_a.raw_bars[0] ~ fx_b.raw_bars[-1]),
      与 `sdt/edt` (分型中心 K 线) 不同, 背驰切片用前者。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Fx:
    """分型快照。"""

    dt: datetime
    mark: str  # "top" / "bottom" / "unknown"
    high: float
    low: float
    raw_mark: str
    raw_fx: str


@dataclass(frozen=True)
class Bi:
    """笔快照。"""

    sdt: datetime
    edt: datetime
    range_sdt: datetime
    range_edt: datetime
    direction: str  # "up" / "down" / "unknown"
    raw_direction: str
    high: float
    low: float
    length: int
    power: float | None
    start_mark: str
    end_mark: str
    start_price: float
    end_price: float


@dataclass(frozen=True)
class Zs:
    """中枢快照 (严格按缠师第 18/20 课构造)。"""

    sdt: datetime
    edt: datetime
    zd: float
    zg: float
    gg: float
    dd: float
    valid: bool
    bis: tuple[Bi, ...] = field(default_factory=tuple)

    @property
    def direction(self) -> str:
        return self.bis[0].direction if self.bis else "unknown"


@dataclass(frozen=True)
class MacdPoint:
    """MACD 单点, 与 bars 同序对齐。"""

    dt: str
    dif: float | None
    dea: float | None
    macd: float | None


@dataclass(frozen=True)
class BsPoint:
    """缠论买卖点 (一/二/三类)。"""

    dt: str
    type: str
    direction: str  # "买" / "卖"
    price: float
    bi_direction: str
    zs_index: int
    macd_area_prev: float | None
    macd_area_cur: float | None
    dif_peak_prev: float | None
    dif_peak_cur: float | None
    dea_peak_prev: float | None
    dea_peak_cur: float | None
    divergence_type: str
    divergence_pass: list[str]
    macd_area_mode: str
    # 判定口径标注: 让调用方知道该点是在何种定义下成立的, 不把工程近似
    # 冒充缠师原文严格口径。取值: "strict" / "practical" / "n/a"(三买三卖
    # 只凭位置, 与重叠口径无关)。带默认值, 不破坏既有调用方与前端契约。
    definition_mode: str = "n/a"
    # 区间套下钻 (缠师第27课): 次级别背驰确认信息, 无次级别数据时为 None。
    # 带默认值, 不破坏既有调用方与前端契约。
    level: str = "日线"
    nest_confirmed: bool | None = None
    nest_level: str | None = None
    nest_ratio: float | None = None
    nest_note: str | None = None
    # 定律一 (第17课): 二买/二卖是否被次级别一买/一卖确认。
    # True=次级别结构通过; False=有数据但结构不通过; None=未验证
    # (无更低级别/数据不可得/无验证器)。B1/S1/B3/S3 恒 None。
    sublevel_verified: bool | None = None


class DtIndex:
    """dt 字符串 → bars 下标查找, 兼容 T/空格分隔与微秒差异。

    原 `_find_dt_idx` 在未命中时会线性扫描全部 bars (O(n)); 本类预先建立
    date 级索引, 把兜底也降为 O(1)。
    """

    __slots__ = ("_bars", "_date10", "_exact")

    def __init__(self, dts: list[str]) -> None:
        self._exact: dict[str, int] = {}
        self._date10: dict[str, int] = {}
        self._bars = dts
        for i, dt in enumerate(dts):
            self._exact.setdefault(dt, i)
            key = dt[:10]
            self._date10.setdefault(key, i)

    @classmethod
    def from_bars(cls, bars: list[object]) -> DtIndex:
        return cls([str(b.dt) for b in bars])

    def find(self, dt: str | datetime | date) -> int | None:
        dt_str = dt.isoformat() if isinstance(dt, (datetime, date)) else str(dt)
        if dt_str in self._exact:
            return self._exact[dt_str]
        norm = dt_str.replace("T", " ")
        if norm in self._exact:
            return self._exact[norm]
        if len(norm) >= 19 and norm[:19] in self._exact:
            return self._exact[norm[:19]]
        if len(norm) >= 10:
            if norm[:10] in self._exact:
                return self._exact[norm[:10]]
            return self._date10.get(norm[:10])
        return None
