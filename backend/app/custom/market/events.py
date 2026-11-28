"""政策事件库 — 存储 / 加载 / 校验 (设计 §2.1)。

数据获取双层:
    1. 自动抓取 (优先): 东财全球快讯 → fetcher.py 关键词过滤 → status=draft 候选;
    2. 人工修正: 直接编辑 data/policy/policy_events.json (改 status/direction/importance)。

存储: data/policy/policy_events.json (人工确认 + 自动候选统一存放, 增量合并不覆盖
人工修改过的条目) + data/policy/fixed_calendar.json (可预期政策窗口, 不进效果统计)。

可信度铁律 (设计 §2.1):
    - 无 source 的条目 excluded=True (页面标灰), 排除出统计;
    - 统计只用 status=approved 且 importance=major;
    - status: draft(自动抓取待审核) / approved(人工确认) / rejected(否决)。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

CATEGORIES = (
    "货币政策",
    "财政政策",
    "产业政策",
    "监管政策",
    "会议定调",
    "外部事件",
)
IMPORTANCES = ("major", "medium", "minor")
DIRECTIONS = ("positive", "negative", "neutral")
STATUSES = ("draft", "approved", "rejected")


@dataclass
class PolicyEvent:
    """一条政策事件 (人工确认或自动抓取候选)。"""

    id: str
    date: date
    title: str
    category: str  # CATEGORIES 之一
    importance: str  # IMPORTANCES 之一, major 才进统计
    direction: str  # DIRECTIONS 之一
    source: str = ""  # 可溯源链接, 必填 — 无 source 页面标灰并排除出统计
    note: str = ""
    status: str = "approved"  # draft/approved/rejected
    fetch_code: str = ""  # 抓取源条目 code (去重键), 人工录入为空
    fetch_at: str = ""  # 抓取时间 ISO, 人工录入为空

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "title": self.title,
            "category": self.category,
            "importance": self.importance,
            "direction": self.direction,
            "source": self.source,
            "note": self.note,
            "status": self.status,
            "fetch_code": self.fetch_code,
            "fetch_at": self.fetch_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyEvent":
        raw = d["date"]
        dt = date.fromisoformat(raw) if isinstance(raw, str) else raw
        return cls(
            id=d["id"],
            date=dt,
            title=d["title"],
            category=d.get("category", "会议定调"),
            importance=d.get("importance", "minor"),
            direction=d.get("direction", "neutral"),
            source=d.get("source", ""),
            note=d.get("note", ""),
            status=d.get("status", "approved"),
            fetch_code=d.get("fetch_code", ""),
            fetch_at=d.get("fetch_at", ""),
        )


@dataclass
class FixedCalendarEntry:
    """固定政策窗口 (两会/政治局/央行例会/FOMC) — 临近事件卡片与日历效应, 不进统计。"""

    date: date
    title: str
    kind: str  # 两会/政治局会议/央行例会/FOMC...
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "title": self.title,
            "kind": self.kind,
            "note": self.note,
        }


def _events_path(root: Path) -> Path:
    return root / "policy" / "policy_events.json"


def _calendar_path(root: Path) -> Path:
    return root / "policy" / "fixed_calendar.json"


def load_events(data_root: Path | str) -> list[PolicyEvent]:
    """加载事件库 — 逐条校验, 非法条目跳过并告警 (不整体失败)。"""
    path = _events_path(Path(data_root))
    if not path.exists():
        return []
    events: list[PolicyEvent] = []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("events") if isinstance(raw, dict) else raw
    for d in items or []:
        try:
            ev = PolicyEvent.from_dict(d)
        except Exception as exc:  # noqa: BLE001
            logger.warning("policy event invalid, skipped: %s (%s)", d.get("id"), exc)
            continue
        problems = _validate(ev)
        if problems:
            logger.warning("policy event invalid, skipped: %s (%s)", ev.id, "; ".join(problems))
            continue
        events.append(ev)
    return events


def _validate(ev: PolicyEvent) -> list[str]:
    problems: list[str] = []
    if not ev.id or not ev.title:
        problems.append("id/title 不能为空")
    if ev.category not in CATEGORIES:
        problems.append(f"category 非法: {ev.category!r}")
    if ev.importance not in IMPORTANCES:
        problems.append(f"importance 非法: {ev.importance!r}")
    if ev.direction not in DIRECTIONS:
        problems.append(f"direction 非法: {ev.direction!r}")
    if ev.status not in STATUSES:
        problems.append(f"status 非法: {ev.status!r}")
    if ev.date and ev.date < date(1990, 12, 19):
        problems.append("date 早于上证指数发布日")
    return problems


def load_fixed_calendar(data_root: Path | str) -> list[FixedCalendarEntry]:
    """加载固定政策窗口日历。"""
    path = _calendar_path(Path(data_root))
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("entries") if isinstance(raw, dict) else raw
    out: list[FixedCalendarEntry] = []
    for d in items or []:
        try:
            raw_date = d["date"]
            out.append(
                FixedCalendarEntry(
                    date=date.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date,
                    title=d["title"],
                    kind=d.get("kind", ""),
                    note=d.get("note", ""),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("fixed calendar entry invalid, skipped: %s (%s)", d, exc)
    return out


def is_countable(ev: PolicyEvent) -> bool:
    """是否计入统计: approved + major + 有 source (设计 §2.1 铁律)。"""
    return ev.status == "approved" and ev.importance == "major" and bool(ev.source.strip())


def merge_fetched(data_root: Path | str, fetched: list[dict]) -> tuple[int, list[str]]:
    """把抓取候选增量合并进事件库 (T2 调用)。

    合并规则 (不覆盖人工修改):
        - 已存在同 fetch_code 的条目: 跳过 (不管其现 status, 人工改过的不动);
        - 新 fetch_code: 以 status=draft 追加, 供人工审核。
    返回 (新增条数, 跳过的 code 列表)。
    """
    path = _events_path(Path(data_root))
    existing_raw: dict = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"events": []}
    )
    events: list[dict] = existing_raw.get("events", [])
    existing_codes = {e.get("fetch_code") for e in events if e.get("fetch_code")}
    added = 0
    skipped: list[str] = []
    for cand in fetched:
        code = cand.get("fetch_code") or ""
        if not code:
            continue
        if code in existing_codes:
            skipped.append(code)
            continue
        entry = dict(cand)
        entry.setdefault("status", "draft")
        events.append(entry)
        existing_codes.add(code)
        added += 1
    existing_raw["events"] = events
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(existing_raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return added, skipped
