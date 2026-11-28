"""/api/market 事件库 — 存储/加载/校验/增量合并 (P3-T1)。"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.custom.market.events import (
    CATEGORIES,
    PolicyEvent,
    load_events,
    load_fixed_calendar,
    merge_fetched,
)

GOOD = {
    "id": "2024-09-24-fabuhui",
    "date": "2024-09-24",
    "title": "国新办金融支持经济高质量发展发布会",
    "category": "货币政策",
    "importance": "major",
    "direction": "positive",
    "source": "https://www.gov.cn/lianbo/202409/24.htm",
    "note": "",
}


def _write_events(tmp_path, events):
    (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "policy" / "policy_events.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False), encoding="utf-8"
    )


def test_load_valid_event(tmp_path):
    _write_events(tmp_path, [GOOD])
    evs = load_events(tmp_path)
    assert len(evs) == 1
    assert evs[0].date == date(2024, 9, 24)
    assert evs[0].status == "approved"  # 缺省 approved


@pytest.mark.parametrize(
    "patch",
    [
        {"category": "不存在的类别"},
        {"importance": "huge"},
        {"direction": "up"},
        {"status": "pending"},
        {"date": "1989-01-01"},
        {"title": ""},
    ],
)
def test_load_invalid_event_skipped(tmp_path, patch):
    bad = dict(GOOD)
    bad.update(patch)
    _write_events(tmp_path, [bad])
    assert load_events(tmp_path) == []


def test_is_countable_rules():
    def ev(**kw):
        d = dict(GOOD)
        # id 必须不同避免误解, 但 from_dict 不查重, 直接构造即可
        e = PolicyEvent.from_dict(d)
        for k, v in kw.items():
            setattr(e, k, v)
        return e

    assert ev().status == "approved"
    from app.custom.market.events import is_countable

    assert is_countable(ev()) is True
    assert is_countable(ev(importance="medium")) is False  # medium 不进统计
    assert is_countable(ev(status="draft")) is False  # 草稿不进统计
    assert is_countable(ev(source="")) is False  # 无 source 标灰排除


def test_categories_stable():
    assert CATEGORIES == ("货币政策", "财政政策", "产业政策", "监管政策", "会议定调", "外部事件")


def test_fixed_calendar(tmp_path):
    (tmp_path / "policy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "policy" / "fixed_calendar.json").write_text(
        json.dumps(
            {
                "entries": [
                    {"date": "2026-03-05", "title": "十四届全国人大四次会议", "kind": "两会"},
                    {"date": "bad-date", "title": "broken"},  # 非法条目跳过
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cal = load_fixed_calendar(tmp_path)
    assert len(cal) == 1
    assert cal[0].kind == "两会"


def test_merge_fetched_incremental(tmp_path):
    _write_events(tmp_path, [GOOD])
    fetched = [
        {
            "id": "2026-11-28-em-001",
            "date": "2026-11-28",
            "title": "央行发布新规",
            "category": "监管政策",
            "importance": "medium",
            "direction": "neutral",
            "source": "https://example.com/1",
            "status": "draft",
            "fetch_code": "20261128X",
            "fetch_at": "2026-11-28T12:00:00",
        },
        # 人工改过 status 的旧条目 (带 fetch_code), 再抓到同 code 必须跳过
        {
            "id": "old",
            "date": "2026-11-20",
            "title": "旧条目",
            "category": "会议定调",
            "importance": "minor",
            "direction": "neutral",
            "source": "https://example.com/old",
            "fetch_code": "OLDCODE",
            "fetch_at": "",
        },
    ]
    # 先把带 fetch_code 的条目放入库中 (status=approved 已人工审核)
    base = json.loads((tmp_path / "policy" / "policy_events.json").read_text(encoding="utf-8"))
    base["events"].append(dict(fetched[1], **{"status": "approved"}))
    (tmp_path / "policy" / "policy_events.json").write_text(
        json.dumps(base, ensure_ascii=False), encoding="utf-8"
    )

    added, skipped = merge_fetched(tmp_path, [fetched[0], fetched[1]])
    assert added == 1
    assert skipped == ["OLDCODE"]
    evs = load_events(tmp_path)
    codes = {e.fetch_code for e in evs}
    assert {"", "20261128X", "OLDCODE"} <= codes
    # 人工修改的条目未被覆盖
    old = next(e for e in evs if e.fetch_code == "OLDCODE")
    assert old.status == "approved"
    # 新条目为 draft
    new = next(e for e in evs if e.fetch_code == "20261128X")
    assert new.status == "draft"
