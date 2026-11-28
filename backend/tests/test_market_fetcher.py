"""fetcher 单测 — 分类启发/过滤构造逻辑 (纯函数, 不碰网络, P3-T2)。"""
from __future__ import annotations

from datetime import date

from app.custom.market.fetcher import (
    _DETAIL_URL,
    build_draft_events,
    classify,
    fetch_policy_drafts,
)


def _item(**kw):
    base = {
        "code": "20261128A1234567",
        "title": "央行宣布降准0.5个百分点释放流动性",
        "summary": "中国人民银行决定下调金融机构存款准备金率",
        "showTime": "2026-11-28 10:00:00",
    }
    assert set(kw) <= {"code", "title", "summary", "showTime"}, f"非法覆盖键: {set(kw) - {'code', 'title', 'summary', 'showTime'}}"
    base.update(kw)
    return base


# ---------- classify ----------


def test_classify_each_category():
    cases = [
        ("央行降准", "货币政策"),
        ("财政部减税降费", "财政政策"),
        ("证监会发布减持新规", "监管政策"),
        ("中央经济工作会议召开", "会议定调"),
        ("美联储宣布加息", "外部事件"),
        ("数字经济产业政策发布", "产业政策"),
    ]
    for title, category in cases:
        cat, _ = classify(title, "")
        assert cat == category, f"{title} -> {cat}, 期望 {category}"


def test_classify_irrelevant_returns_none():
    assert classify("某公司发布新款手机", "") == (None, "neutral")
    assert classify("", "")[0] is None


def test_classify_direction():
    # 降准 = positive
    assert classify("央行降准释放流动性", "")[1] == "positive"
    # 加征关税 = negative
    assert classify("美联储加息叠加贸易制裁", "")[1] == "negative"
    # 只有中性词
    assert classify("央行公开市场操作公告", "")[1] == "neutral"
    # 正负同现: 负面优先级在实现中为 elif, 正面词+负面词 -> negative
    cat, direction = classify("降准但外围市场收紧", "")
    assert cat == "货币政策"
    assert direction == "negative"


# ---------- build_draft_events ----------


def test_build_draft_events_happy_path():
    out = build_draft_events([_item()], since=date(2026, 11, 1))
    assert len(out) == 1
    ev = out[0]
    assert ev["id"] == "em-20261128A1234567"
    assert ev["date"] == "2026-11-28"
    assert ev["category"] == "货币政策"
    assert ev["importance"] == "minor"  # 固定 minor, 人工审核再定级
    assert ev["direction"] == "positive"
    assert ev["status"] == "draft"
    assert ev["source"] == _DETAIL_URL.format(code="20261128A1234567")
    assert ev["fetch_code"] == "20261128A1234567"
    assert ev["fetch_at"]  # 自动填


def test_build_draft_events_filters():
    since = date(2026, 11, 1)
    items = [
        _item(),                                     # 通过 (对照)
        _item(code="", title="x"),                   # 无 code
        _item(title="太短"),                          # 标题过短
        _item(showTime="2026-10-01 09:00:00"),       # 早于 since
        _item(showTime="bad-date"),                  # 非法日期
        _item(title="某手机新品发布会的预热消息长标题", summary="不相关"),  # 分类 None
        _item(showTime=""),                          # 无 showTime
    ]
    out = build_draft_events(items, since=since)
    assert len(out) == 1
    assert out[0]["fetch_code"] == "20261128A1234567"


def test_build_draft_events_fetch_at_passthrough():
    out = build_draft_events([_item()], since=None, fetch_at="2026-11-28T12:00:00")
    assert out[0]["fetch_at"] == "2026-11-28T12:00:00"


def test_build_draft_events_dedup_not_needed():
    # 同 code 条目: fetch 层去重 (seen), build 层不去重 — 这里验证两条不同 code 都保留
    out = build_draft_events(
        [_item(), _item(code="20261128B7654321", title="财政部发布专项债新政支持基建", summary="专项债")],        since=date(2026, 11, 1),
    )
    assert len(out) == 2
    assert {e["category"] for e in out} == {"货币政策", "财政政策"}


# ---------- fetch_policy_drafts (mock 网络层) ----------


def test_fetch_policy_drafts_pipeline(monkeypatch):
    captured = {}

    def fake_fetch(pages, page_size=50):
        captured["pages"] = pages
        return [_item()]

    import app.custom.market.fetcher as f

    monkeypatch.setattr(f, "fetch_em_fastnews", fake_fetch)
    out = fetch_policy_drafts(pages=3, since_days=7)
    assert captured["pages"] == 3
    assert len(out) == 1
    assert out[0]["status"] == "draft"
