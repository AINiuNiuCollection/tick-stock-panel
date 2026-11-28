"""政策事件自动抓取器 — 东财全球快讯 → 关键词过滤 → draft 候选 (P3-T2)。

抓取源 (2026-11-28 实探): 东财 getFastNewsList
    https://np-listapi.eastmoney.com/comm/web/getFastNewsList
    分页键 = 上一页最后一条的 realSort; 详情页 = /finance.eastmoney.com/a/{code}.html
    百度经济日历 403 风控不可用, 不接。

设计定位 (设计 §2.1 用户裁定 2026-11-28: 自动抓取优先 + 人工修正):
    抓取只产出 status=draft 候选 — 政策方向的定性以人工审核为准,
    统计层 (events.is_countable) 只认 approved+major, draft 永不进统计。

分类/方向规则为关键词启发式, 只用于减少人工初审工作量, 不做定性的最终权威。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
_DETAIL_URL = "https://finance.eastmoney.com/a/{code}.html"
_TIMEOUT = 15.0

# category 启发规则 (按优先级, 先中先得)
_CATEGORY_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "降准", "降息", "逆回购", "MLF", "LPR", "存款准备金", "再贷款",
            "央行", "中国人民银行", "货币政策",
        ),
        "货币政策",
    ),
    (("专项债", "国债", "财政", "减税", "免税", "退税", "财政政策", "财政部"), "财政政策"),
    (("证监会", "注册制", "IPO", "印花税", "减持", "再融资", "融券", "退市", "监管"), "监管政策"),
    (
        ("政治局会议", "中央经济工作会议", "国常会", "国务院常务会议", "两会", "政府工作报告", "五年规划"),
        "会议定调",
    ),
    (("关税", "贸易战", "制裁", "美联储", "FOMC", "加息", "外围市场", "地缘"), "外部事件"),
    (("产业政策", "行业规划", "补贴", "新兴产业", "专精特新", "数字经济"), "产业政策"),
)

# direction 启发规则
_POSITIVE_WORDS = ("降准", "降息", "减税", "免税", "退税", "支持", "刺激", "宽松", "利好", "加力")
_NEGATIVE_WORDS = ("加征关税", "制裁", "收紧", "加息", "利空", "打压", "限制", "调查", "冲突")


def fetch_em_fastnews(pages: int = 40, page_size: int = 50) -> list[dict]:
    """抓取东财全球快讯 (倒序翻页), 返回原始条目列表。

    pages×page_size=2000 条约覆盖数个交易日, 供关键词过滤后取政策类候选。
    """
    items: list[dict] = []
    sort_end = ""
    seen: set[str] = set()
    with httpx.Client(timeout=_TIMEOUT, verify=False, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for page in range(pages):
            try:
                resp = client.get(
                    _API_URL,
                    params={
                        "client": "web",
                        "biz": "web_724",
                        "fastColumn": "102",
                        "sortEnd": sort_end,
                        "pageSize": page_size,
                        "req_trace": "1",
                    },
                )
                resp.raise_for_status()
                data = resp.json().get("data") or {}
            except Exception as exc:  # noqa: BLE001
                logger.warning("eastmoney fastnews fetch failed (page %s): %s", page, exc)
                break
            batch = data.get("fastNewsList") or []
            if not batch:
                break
            for it in batch:
                code = str(it.get("code") or "")
                if not code or code in seen:
                    continue
                seen.add(code)
                items.append(it)
            nxt = str(batch[-1].get("realSort") or "")
            if not nxt:
                break
            sort_end = nxt
    return items


def classify(title: str, summary: str) -> tuple[str | None, str]:
    """关键词启发式分类 — 返回 (category | None 不相关, direction)。"""
    text = f"{title} {summary}"
    for words, category in _CATEGORY_RULES:
        if any(w in text for w in words):
            direction = "neutral"
            if any(w in text for w in _POSITIVE_WORDS) and not any(
                w in text for w in _NEGATIVE_WORDS
            ):
                direction = "positive"
            elif any(w in text for w in _NEGATIVE_WORDS):
                direction = "negative"
            return category, direction
    return None, "neutral"


def build_draft_events(
    items: list[dict],
    since: date | None = None,
    fetch_at: str | None = None,
) -> list[dict]:
    """原始快讯 → draft 候选事件字典列表 (供 events.merge_fetched 增量合并)。

    过滤: 关键词不相关 / 早于 since / 标题过短(噪声) 的条目丢弃。
    importance 固定 minor — 人工审核时再定级 (major 才进统计)。
    """
    fetch_at = fetch_at or datetime.now().isoformat(timespec="seconds")
    out: list[dict] = []
    for it in items:
        title = (it.get("title") or "").strip()
        summary = (it.get("summary") or "").strip()
        show_time = (it.get("showTime") or "").strip()
        code = str(it.get("code") or "").strip()
        if not title or len(title) < 8 or not code or not show_time:
            continue
        category, direction = classify(title, summary)
        if category is None:
            continue
        try:
            event_date = date.fromisoformat(show_time[:10])
        except ValueError:
            continue
        if since and event_date < since:
            continue
        out.append(
            {
                "id": f"em-{code}",
                "date": event_date.isoformat(),
                "title": title,
                "category": category,
                "importance": "minor",
                "direction": direction,
                "source": _DETAIL_URL.format(code=code),
                "note": summary[:200],
                "status": "draft",
                "fetch_code": code,
                "fetch_at": fetch_at,
            }
        )
    return out


def fetch_policy_drafts(
    pages: int = 40,
    since_days: int = 7,
) -> list[dict]:
    """一站式抓取: 东财快讯 → 关键词过滤 → draft 候选。"""
    since = date.today() - timedelta(days=since_days)
    return build_draft_events(fetch_em_fastnews(pages=pages), since=since)
